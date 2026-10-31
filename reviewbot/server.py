"""The local web server.

  POST /webhook          GitHub sends events here (via smee.io locally)
  GET  /setup            one-click GitHub App creation
  GET  /dashboard        review metrics
  GET  /api/stats        the numbers behind the dashboard
  GET  /health           for Docker health checks

Run locally with:  uvicorn reviewbot.server:app --host 0.0.0.0 --port 8000
On AWS the webhook is handled by lambdas/webhook_handler.py instead.
"""

import html
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from reviewbot.config import load_settings
from reviewbot.job_queue import JobQueue
from reviewbot.signature import verify_signature
from reviewbot.stats import compute_stats
from reviewbot.storage import Storage
from reviewbot.webhooks import jobs_from_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reviewbot.server")

DASHBOARD_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"

_queue = None
_storage = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts."""
    settings = load_settings()
    ensure_smee_channel(settings)
    try:
        get_storage()
    except Exception as error:
        logger.warning("DynamoDB not ready yet: %s", error)
    yield


app = FastAPI(title="ReviewBot", lifespan=lifespan)


def get_queue():
    global _queue
    if _queue is None:
        _queue = JobQueue(load_settings())
    return _queue


def get_storage():
    global _storage
    if _storage is None:
        _storage = Storage(load_settings())
        _storage.create_tables_if_missing()
    return _storage


def ensure_smee_channel(settings) -> str:
    """Creates a free smee.io channel once and saves its URL. The smee
    container forwards GitHub webhooks from that URL to this server."""
    if settings.smee_url:
        return settings.smee_url
    smee_file = Path(settings.secrets_file).parent / "smee_url"
    if smee_file.exists():
        return smee_file.read_text().strip()
    try:
        response = requests.head("https://smee.io/new", allow_redirects=False, timeout=15)
        url = response.headers.get("Location", "")
        if url.startswith("https://smee.io/"):
            smee_file.parent.mkdir(parents=True, exist_ok=True)
            smee_file.write_text(url)
            logger.info("Created smee channel %s", url)
            return url
    except requests.RequestException as error:
        logger.warning("Could not create smee channel: %s", error)
    return ""


# ----------------------------------------------------------------------
# Webhook
# ----------------------------------------------------------------------
@app.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
):
    settings = load_settings()
    body = await request.body()
    if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    jobs = jobs_from_event(x_github_event, payload)
    for job in jobs:
        get_queue().send(job)
    return {"queued": len(jobs)}


@app.get("/health")
def health():
    return {"ok": True}


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------
@app.get("/")
def root():
    settings = load_settings()
    if not settings.github_app_id:
        return RedirectResponse("/setup")
    return RedirectResponse("/dashboard")


@app.get("/dashboard")
def dashboard():
    return FileResponse(DASHBOARD_FILE)


@app.get("/api/stats")
def api_stats():
    storage = get_storage()
    return compute_stats(storage.list_reviews(), storage.list_comments(), storage.list_repo_configs())


# ----------------------------------------------------------------------
# One-click GitHub App setup (GitHub "App manifest" flow)
# ----------------------------------------------------------------------
PAGE_STYLE = """
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 640px; margin: 60px auto; padding: 0 16px;
         color: #1f2328; line-height: 1.55; }
  h1 { font-size: 26px; } code { background: #f2f3f5; padding: 2px 6px; border-radius: 4px; }
  button, .button { background: #1f883d; color: white; border: 0; padding: 12px 20px; border-radius: 6px;
           font-size: 16px; cursor: pointer; text-decoration: none; display: inline-block; }
  input { padding: 10px; font-size: 15px; width: 100%; box-sizing: border-box; margin: 6px 0 16px;
          border: 1px solid #d0d7de; border-radius: 6px; }
  .muted { color: #59636e; font-size: 14px; }
</style>
"""


def build_manifest(settings, app_name: str, smee_url: str) -> dict:
    return {
        "name": app_name,
        "url": "https://github.com",
        "hook_attributes": {"url": smee_url, "active": True},
        "redirect_url": f"{settings.public_url}/setup/callback",
        "public": False,
        "default_permissions": {
            "pull_requests": "write",
            "contents": "write",  # write is only needed by the sample-repo seeding script
            "issues": "write",  # used for the risk label
            "metadata": "read",
        },
        "default_events": ["pull_request", "push"],
    }


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    settings = load_settings()
    if settings.github_app_id:
        install_url = settings.extra.get("app_html_url", "") + "/installations/new"
        return f"""{PAGE_STYLE}<h1>✅ GitHub App is set up</h1>
        <p>App ID <code>{html.escape(settings.github_app_id)}</code>.</p>
        <p><a class="button" href="{html.escape(install_url)}">Install it on a repository</a></p>
        <p class="muted">Then open a pull request. <a href="/dashboard">Dashboard →</a></p>"""

    smee_url = ensure_smee_channel(settings)
    if not smee_url:
        return f"{PAGE_STYLE}<h1>Could not create a smee.io channel</h1><p>Check your internet connection and refresh.</p>"

    suggested_name = f"reviewbot-{secrets.token_hex(3)}"
    return f"""{PAGE_STYLE}
    <h1>🤖 Create your ReviewBot GitHub App</h1>
    <p>This creates a private GitHub App under your account with the right permissions and webhook URL.
       GitHub will ask you to confirm, then send you back here.</p>
    <form id="form" method="post">
      <label>App name (must be unique on GitHub)</label>
      <input id="name" value="{suggested_name}">
      <input type="hidden" name="manifest" id="manifest">
      <button type="submit">Create GitHub App</button>
    </form>
    <p class="muted">Webhooks will arrive through <code>{html.escape(smee_url)}</code></p>
    <script>
      document.getElementById('form').addEventListener('submit', async function (event) {{
        event.preventDefault();
        const name = document.getElementById('name').value;
        const response = await fetch('/setup/manifest?name=' + encodeURIComponent(name));
        document.getElementById('manifest').value = JSON.stringify(await response.json());
        this.action = 'https://github.com/settings/apps/new?state=reviewbot';
        this.submit();
      }});
    </script>"""


@app.get("/setup/manifest")
def setup_manifest(name: str):
    settings = load_settings()
    return build_manifest(settings, name, ensure_smee_channel(settings))


@app.get("/setup/callback", response_class=HTMLResponse)
def setup_callback(code: str):
    settings = load_settings()
    response = requests.post(
        f"{settings.github_api_url}/app-manifests/{code}/conversions",
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    if response.status_code != 201:
        return f"{PAGE_STYLE}<h1>Setup failed</h1><pre>{html.escape(response.text)}</pre>"

    data = response.json()
    saved = {
        "app_id": data["id"],
        "slug": data["slug"],
        "html_url": data["html_url"],
        "private_key": data["pem"],
        "webhook_secret": data["webhook_secret"],
        "client_id": data.get("client_id", ""),
    }
    secrets_path = Path(settings.secrets_file)
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(json.dumps(saved, indent=2))
    os.chmod(secrets_path, 0o600)
    logger.info("Saved GitHub App %s credentials", data["slug"])
    return RedirectResponse(f"{data['html_url']}/installations/new")

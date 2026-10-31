"""Everything that talks to the GitHub REST API.

How GitHub App authentication works:
1. We sign a short-lived JWT with the App's private key. This proves
   "I am the App".
2. We exchange that JWT for an installation access token. This proves
   "I am the App, acting on the repos where I was installed".
3. All further calls use the installation token.
"""

import base64
import logging
import time

import jwt
import requests

from reviewbot.config import Settings

logger = logging.getLogger(__name__)


class GitHubError(Exception):
    pass


class GitHubClient:
    def __init__(self, settings: Settings, installation_id: int):
        self.settings = settings
        self.installation_id = installation_id
        self.api = settings.github_api_url.rstrip("/")
        self._token = None
        self._token_expires_at = 0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,  # a minute in the past to allow for clock drift
            "exp": now + 9 * 60,  # GitHub allows at most 10 minutes
            "iss": self.settings.github_app_id,
        }
        return jwt.encode(payload, self.settings.github_private_key, algorithm="RS256")

    def _installation_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        url = f"{self.api}/app/installations/{self.installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {self._app_jwt()}",
            "Accept": "application/vnd.github+json",
        }
        response = requests.post(url, headers=headers, timeout=20)
        if response.status_code != 201:
            raise GitHubError(f"Could not get installation token: {response.status_code} {response.text}")
        self._token = response.json()["token"]
        self._token_expires_at = time.time() + 55 * 60
        return self._token

    def _request(self, method: str, path: str, accept: str = "application/vnd.github+json", **kwargs):
        url = path if path.startswith("http") else f"{self.api}{path}"
        headers = {
            "Authorization": f"Bearer {self._installation_token()}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if response.status_code >= 400:
            raise GitHubError(f"{method} {path} failed: {response.status_code} {response.text[:500]}")
        return response

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------
    def get_pull_request(self, repo: str, number: int) -> dict:
        return self._request("GET", f"/repos/{repo}/pulls/{number}").json()

    def get_pull_request_diff(self, repo: str, number: int) -> str:
        response = self._request("GET", f"/repos/{repo}/pulls/{number}", accept="application/vnd.github.v3.diff")
        return response.text

    def list_pull_request_files(self, repo: str, number: int) -> list:
        files = []
        page = 1
        while True:
            response = self._request(
                "GET", f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100, "page": page}
            )
            batch = response.json()
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    def get_file_content(self, repo: str, path: str, ref: str) -> str | None:
        try:
            response = self._request("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        except GitHubError:
            return None
        data = response.json()
        if isinstance(data, list) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def get_tree(self, repo: str, ref: str) -> list:
        response = self._request("GET", f"/repos/{repo}/git/trees/{ref}", params={"recursive": "1"})
        return [item for item in response.json().get("tree", []) if item.get("type") == "blob"]

    def get_blob(self, repo: str, sha: str) -> str:
        data = self._request("GET", f"/repos/{repo}/git/blobs/{sha}").json()
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def get_repo(self, repo: str) -> dict:
        return self._request("GET", f"/repos/{repo}").json()

    # ------------------------------------------------------------------
    # Posting reviews
    # ------------------------------------------------------------------
    def create_review(self, repo: str, number: int, commit_sha: str, body: str, comments: list) -> dict:
        payload = {"commit_id": commit_sha, "body": body, "event": "COMMENT", "comments": comments}
        try:
            return self._request("POST", f"/repos/{repo}/pulls/{number}/reviews", json=payload).json()
        except GitHubError as error:
            # If GitHub rejects an inline comment (e.g. a line outside the
            # diff) we still post the summary so the developer gets value.
            logger.warning("Review with inline comments failed, posting summary only: %s", error)
            payload["comments"] = []
            return self._request("POST", f"/repos/{repo}/pulls/{number}/reviews", json=payload).json()

    def list_review_comments(self, repo: str, number: int, review_id: int) -> list:
        response = self._request("GET", f"/repos/{repo}/pulls/{number}/reviews/{review_id}/comments")
        return response.json()

    def set_risk_label(self, repo: str, number: int, risk_level: str) -> None:
        label = f"risk: {risk_level}"
        colors = {"low": "2da44e", "medium": "d4a72c", "high": "cf222e"}
        try:
            self._request("POST", f"/repos/{repo}/labels", json={"name": label, "color": colors.get(risk_level, "888888")})
        except GitHubError:
            pass  # label already exists
        try:
            current = self._request("GET", f"/repos/{repo}/issues/{number}/labels").json()
            for existing in current:
                if existing["name"].startswith("risk: ") and existing["name"] != label:
                    self._request("DELETE", f"/repos/{repo}/issues/{number}/labels/{existing['name']}")
            self._request("POST", f"/repos/{repo}/issues/{number}/labels", json={"labels": [label]})
        except GitHubError as error:
            logger.warning("Could not set risk label: %s", error)

    def get_comment_reactions(self, repo: str, comment_id: int) -> list:
        response = self._request("GET", f"/repos/{repo}/pulls/comments/{comment_id}/reactions")
        return response.json()

    # ------------------------------------------------------------------
    # Used only by the sample-repo seeding script
    # ------------------------------------------------------------------
    def put_file(self, repo: str, path: str, content: str, message: str, branch: str, sha: str | None = None):
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        return self._request("PUT", f"/repos/{repo}/contents/{path}", json=payload).json()

    def get_file_sha(self, repo: str, path: str, ref: str) -> str | None:
        try:
            return self._request("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref}).json()["sha"]
        except GitHubError:
            return None

    def get_branch_sha(self, repo: str, branch: str) -> str | None:
        try:
            return self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}").json()["object"]["sha"]
        except GitHubError:
            return None

    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        self._request("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": from_sha})

    def open_pull_request(self, repo: str, title: str, head: str, base: str, body: str) -> dict:
        payload = {"title": title, "head": head, "base": base, "body": body}
        return self._request("POST", f"/repos/{repo}/pulls", json=payload).json()


def get_repo_installation_id(settings: Settings, repo: str) -> int:
    """Finds the installation of our App on one repository."""
    client = GitHubClient(settings, installation_id=0)
    headers = {"Authorization": f"Bearer {client._app_jwt()}", "Accept": "application/vnd.github+json"}
    response = requests.get(f"{client.api}/repos/{repo}/installation", headers=headers, timeout=20)
    if response.status_code != 200:
        raise GitHubError(f"The App is not installed on {repo}: {response.status_code} {response.text}")
    return response.json()["id"]


def list_app_installations(settings: Settings) -> list:
    """Uses the App JWT (not an installation token) to list installations."""
    client = GitHubClient(settings, installation_id=0)
    headers = {"Authorization": f"Bearer {client._app_jwt()}", "Accept": "application/vnd.github+json"}
    response = requests.get(f"{client.api}/app/installations", headers=headers, timeout=20)
    if response.status_code != 200:
        raise GitHubError(f"Could not list installations: {response.status_code} {response.text}")
    return response.json()

"""Decides what to do with each job taken from the queue.

The same function is used by the local worker (worker.py) and by the AWS
Lambda worker (lambdas/worker_handler.py).
"""

import logging

from reviewbot.config import Settings
from reviewbot.feedback import sync_feedback
from reviewbot.github_review import index_repo_job, review_pull_request
from reviewbot.llm import LLMClient
from reviewbot.retrieval.embedder import get_embedder
from reviewbot.retrieval.vector_store import get_vector_store
from reviewbot.storage import Storage

logger = logging.getLogger(__name__)


class JobRunner:
    """Creates the expensive objects (DB connection, embedding model) once
    and reuses them for every job."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings)
        self.store = get_vector_store(settings.database_url)
        self.embedder = get_embedder(settings.embedding_model)
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = LLMClient(self.settings)
        return self._llm

    def run(self, job: dict) -> dict:
        job_type = job.get("type")
        if job_type == "review_pr":
            return review_pull_request(self.settings, job, self.llm, self.store, self.embedder, self.storage)
        if job_type == "index_repo":
            return index_repo_job(self.settings, job, self.store, self.embedder)
        if job_type == "sync_feedback":
            return sync_feedback(self.settings, self.storage)
        logger.warning("Unknown job type: %s", job_type)
        return {"ignored": job_type}

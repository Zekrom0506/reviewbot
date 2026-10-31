"""Builds and updates the code index for a repository.

Runs on every push to the default branch. Only files whose git blob SHA
changed since the last run are re-embedded, so updates are cheap.
"""

import logging

from reviewbot.retrieval.chunker import chunk_file, should_index

logger = logging.getLogger(__name__)
EMBED_BATCH_SIZE = 64


def index_files(store, embedder, repo: str, files: dict) -> int:
    """Index {path: content} directly. Used by the eval script and tests."""
    total = 0
    for path, content in files.items():
        if not should_index(path):
            continue
        chunks = chunk_file(path, content)
        if not chunks:
            continue
        embeddings = embedder.embed([chunk.content for chunk in chunks])
        store.replace_file(repo, path, chunks, embeddings)
        total += len(chunks)
    return total


def index_repository(github, store, embedder, repo: str, ref: str) -> dict:
    tree = github.get_tree(repo, ref)
    known_hashes = store.file_hashes(repo)
    wanted = [item for item in tree if should_index(item["path"], item.get("size", 0))]

    updated_files = 0
    total_chunks = 0
    for item in wanted:
        path = item["path"]
        if known_hashes.get(path) == item["sha"]:
            continue  # unchanged since last index
        content = github.get_blob(repo, item["sha"])
        chunks = chunk_file(path, content)
        embeddings = []
        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[start:start + EMBED_BATCH_SIZE]
            embeddings.extend(embedder.embed([chunk.content for chunk in batch]))
        store.replace_file(repo, path, chunks, embeddings)
        store.set_file_hash(repo, path, item["sha"])
        updated_files += 1
        total_chunks += len(chunks)

    store.remove_files_not_in(repo, {item["path"] for item in wanted})
    store.set_indexed_commit(repo, ref)
    logger.info("Indexed %s@%s: %d files updated, %d chunks", repo, ref[:7], updated_files, total_chunks)
    return {"files_updated": updated_files, "chunks": total_chunks}

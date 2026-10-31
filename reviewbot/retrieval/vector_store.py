"""Where embeddings are stored and searched.

PgVectorStore    - Postgres with the pgvector extension (used in Docker / prod)
InMemoryVectorStore - a plain Python list, used in tests and the eval script

Both offer the same methods, so the rest of the code does not care which
one it gets.
"""

import logging
import math

from reviewbot.retrieval.chunker import CodeChunk
from reviewbot.retrieval.embedder import EMBEDDING_SIZE

logger = logging.getLogger(__name__)


def cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    def __init__(self):
        self.rows = []  # list of (repo, chunk, embedding)
        self.indexed_commits = {}

    def replace_file(self, repo: str, path: str, chunks: list, embeddings: list) -> None:
        self.rows = [row for row in self.rows if not (row[0] == repo and row[1].path == path)]
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self.rows.append((repo, chunk, embedding))

    def remove_files_not_in(self, repo: str, keep_paths: set) -> None:
        self.rows = [row for row in self.rows if row[0] != repo or row[1].path in keep_paths]

    def search(self, repo: str, embedding: list, limit: int, exclude_path: str | None = None) -> list:
        scored = []
        for row_repo, chunk, row_embedding in self.rows:
            if row_repo != repo or chunk.path == exclude_path:
                continue
            scored.append((cosine_similarity(embedding, row_embedding), chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]

    def find_text(self, repo: str, text: str, limit: int) -> list:
        results = [chunk for row_repo, chunk, _ in self.rows if row_repo == repo and text in chunk.content]
        return results[:limit]

    def chunk_count(self, repo: str) -> int:
        return sum(1 for row in self.rows if row[0] == repo)

    def get_indexed_commit(self, repo: str) -> str | None:
        return self.indexed_commits.get(repo)

    def set_indexed_commit(self, repo: str, sha: str) -> None:
        self.indexed_commits[repo] = sha

    def file_hashes(self, repo: str) -> dict:
        return {}

    def set_file_hash(self, repo: str, path: str, blob_sha: str) -> None:
        pass


class PgVectorStore:
    def __init__(self, database_url: str):
        import psycopg
        from pgvector.psycopg import register_vector

        self.connection = psycopg.connect(database_url, autocommit=True)
        self.connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.connection)
        self.connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS code_chunks (
                id BIGSERIAL PRIMARY KEY,
                repo TEXT NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                start_line INT NOT NULL,
                end_line INT NOT NULL,
                content TEXT NOT NULL,
                embedding vector({EMBEDDING_SIZE}) NOT NULL
            )
            """
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS code_chunks_repo ON code_chunks (repo)")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS code_chunks_embedding ON code_chunks USING hnsw (embedding vector_cosine_ops)"
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS indexed_files (
                repo TEXT NOT NULL,
                path TEXT NOT NULL,
                blob_sha TEXT NOT NULL,
                PRIMARY KEY (repo, path)
            )
            """
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS indexed_repos (repo TEXT PRIMARY KEY, commit_sha TEXT NOT NULL)"
        )

    def replace_file(self, repo: str, path: str, chunks: list, embeddings: list) -> None:
        import numpy

        with self.connection.transaction():
            self.connection.execute("DELETE FROM code_chunks WHERE repo = %s AND path = %s", (repo, path))
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                self.connection.execute(
                    """INSERT INTO code_chunks (repo, path, name, start_line, end_line, content, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (repo, chunk.path, chunk.name, chunk.start_line, chunk.end_line, chunk.content,
                     numpy.array(embedding, dtype=numpy.float32)),
                )

    def remove_files_not_in(self, repo: str, keep_paths: set) -> None:
        rows = self.connection.execute("SELECT DISTINCT path FROM code_chunks WHERE repo = %s", (repo,)).fetchall()
        for (path,) in rows:
            if path not in keep_paths:
                self.connection.execute("DELETE FROM code_chunks WHERE repo = %s AND path = %s", (repo, path))
                self.connection.execute("DELETE FROM indexed_files WHERE repo = %s AND path = %s", (repo, path))

    def search(self, repo: str, embedding: list, limit: int, exclude_path: str | None = None) -> list:
        import numpy

        rows = self.connection.execute(
            """SELECT path, name, start_line, end_line, content FROM code_chunks
               WHERE repo = %s AND path <> %s
               ORDER BY embedding <=> %s LIMIT %s""",
            (repo, exclude_path or "", numpy.array(embedding, dtype=numpy.float32), limit),
        ).fetchall()
        return [CodeChunk(*row) for row in rows]

    def find_text(self, repo: str, text: str, limit: int) -> list:
        rows = self.connection.execute(
            """SELECT path, name, start_line, end_line, content FROM code_chunks
               WHERE repo = %s AND strpos(content, %s) > 0 LIMIT %s""",
            (repo, text, limit),
        ).fetchall()
        return [CodeChunk(*row) for row in rows]

    def chunk_count(self, repo: str) -> int:
        return self.connection.execute("SELECT count(*) FROM code_chunks WHERE repo = %s", (repo,)).fetchone()[0]

    def get_indexed_commit(self, repo: str) -> str | None:
        row = self.connection.execute("SELECT commit_sha FROM indexed_repos WHERE repo = %s", (repo,)).fetchone()
        return row[0] if row else None

    def set_indexed_commit(self, repo: str, sha: str) -> None:
        self.connection.execute(
            """INSERT INTO indexed_repos (repo, commit_sha) VALUES (%s, %s)
               ON CONFLICT (repo) DO UPDATE SET commit_sha = EXCLUDED.commit_sha""",
            (repo, sha),
        )

    def file_hashes(self, repo: str) -> dict:
        rows = self.connection.execute("SELECT path, blob_sha FROM indexed_files WHERE repo = %s", (repo,)).fetchall()
        return {path: sha for path, sha in rows}

    def set_file_hash(self, repo: str, path: str, blob_sha: str) -> None:
        self.connection.execute(
            """INSERT INTO indexed_files (repo, path, blob_sha) VALUES (%s, %s, %s)
               ON CONFLICT (repo, path) DO UPDATE SET blob_sha = EXCLUDED.blob_sha""",
            (repo, path, blob_sha),
        )


def get_vector_store(database_url: str):
    if database_url:
        return PgVectorStore(database_url)
    logger.warning("DATABASE_URL not set; using in-memory vector store (data is lost on restart)")
    return InMemoryVectorStore()

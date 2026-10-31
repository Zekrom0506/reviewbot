"""Turns text into vectors (lists of numbers) so similar code ends up close
together.

We use FastEmbed, which runs a small embedding model (bge-small, 384
numbers per text) on the CPU for free. If FastEmbed is not installed, a
simple "hashing" embedder is used instead so tests still run offline.
"""

import hashlib
import logging
import math
import re

logger = logging.getLogger(__name__)

EMBEDDING_SIZE = 384
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class HashingEmbedder:
    """Very small fallback: every word is hashed into one of 384 buckets."""

    def embed(self, texts: list) -> list:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_SIZE
            words = TOKEN_PATTERN.findall(text.lower())
            # also split snake_case and camelCase into parts
            parts = []
            for word in words:
                parts.extend(piece for piece in re.split(r"_|(?<=[a-z])(?=[A-Z])", word) if piece)
            for token in words + parts:
                bucket = int(hashlib.md5(token.encode(), usedforsecurity=False).hexdigest(), 16) % EMBEDDING_SIZE
                vector[bucket] += 1.0
            length = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / length for value in vector])
        return vectors


class FastEmbedEmbedder:
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list) -> list:
        return [list(map(float, vector)) for vector in self.model.embed(texts)]


_cached_embedder = None


def get_embedder(model_name: str):
    global _cached_embedder
    if _cached_embedder is not None:
        return _cached_embedder
    try:
        _cached_embedder = FastEmbedEmbedder(model_name)
        logger.info("Using FastEmbed model %s", model_name)
    except Exception as error:
        logger.warning("FastEmbed unavailable (%s); using hashing embedder", error)
        _cached_embedder = HashingEmbedder()
    return _cached_embedder

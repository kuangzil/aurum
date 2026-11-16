"""Explicit embedding adapters; no automatic lexical fallback in production."""
import hashlib
import math
import re
from threading import Lock
from typing import Protocol


class Embeddings(Protocol):
    model_id: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbeddings:
    def __init__(self, model: str):
        self.model_id = model
        self._model = None
        self._lock = Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                # Provision once using the documented setup command, never download on a chat request.
                self._model = SentenceTransformer(self.model_id, local_files_only=True, device='cpu')
            return self._model.encode(texts, normalize_embeddings=True).tolist()


class FakeEmbeddings:
    """Deterministic token hashing ONLY for explicit offline tests; not semantic AI."""
    model_id = 'test-only-token-hash-v1'

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vector = [0.0] * 256
            for token in re.findall(r'\w+', text.lower()):
                vector[int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], 'big') % 256] += 1
            norm = math.sqrt(sum(x*x for x in vector)) or 1
            result.append([x / norm for x in vector])
        return result

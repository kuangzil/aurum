"""Bounded process-local context cache, unrelated to a transformer's KV cache."""
from collections import OrderedDict
from dataclasses import dataclass
import math
from threading import Lock
from uuid import uuid4


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1
    denom = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(a*b for a, b in zip(left, right)) / denom if denom else 0


@dataclass
class Entry:
    session_id: str
    query: str
    vector: list[float]
    revision: tuple
    hits: list[tuple[str, float]]


class SemanticCache:
    def __init__(self, max_entries: int, threshold: float):
        self.max_entries, self.threshold = max_entries, threshold
        self.entries: OrderedDict[str, Entry] = OrderedDict()
        self._lock = Lock()

    def get(self, session_id: str, query: str, vector: list[float], revision: tuple):
        with self._lock:
            for key, entry in list(self.entries.items()):
                if entry.session_id == session_id and entry.revision != revision:
                    del self.entries[key]
            candidates = [(key, entry, cosine(vector, entry.vector)) for key, entry in self.entries.items()
                          if entry.session_id == session_id and entry.revision == revision]
            candidates.sort(key=lambda item: (item[1].query == query, item[2]), reverse=True)
            for key, entry, score in candidates:
                exact = entry.query == query
                if exact or score >= self.threshold:
                    self.entries.move_to_end(key)
                    return list(entry.hits), 'exact' if exact else 'semantic'
        return None

    def put(self, session_id: str, query: str, vector: list[float], revision: tuple,
            hits: list[tuple[str, float]]) -> None:
        if not hits:
            return
        with self._lock:
            for key, entry in list(self.entries.items()):
                if entry.session_id == session_id and (entry.query == query or entry.revision != revision):
                    del self.entries[key]
            self.entries[str(uuid4())] = Entry(session_id, query, vector, revision, list(hits))
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)

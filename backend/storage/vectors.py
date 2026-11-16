from pathlib import Path
from threading import Lock

from backend.storage.embeddings import Embeddings


class ChromaMemory:
    def __init__(self, path: Path, embeddings: Embeddings):
        self.path = path
        self.embeddings = embeddings
        self._collection = None
        self._lock = Lock()

    @property
    def collection(self):
        with self._lock:
            if self._collection is None:
                import chromadb
                from chromadb.config import Settings
                client = chromadb.PersistentClient(path=str(self.path), settings=Settings(anonymized_telemetry=False))
                collection = client.get_or_create_collection(
                    'aurum_conversation_memory', embedding_function=None,
                    metadata={'embedding_model': self.embeddings.model_id},
                    configuration={'hnsw': {'space': 'cosine'}},
                )
                if (collection.metadata or {}).get('embedding_model') != self.embeddings.model_id:
                    raise ValueError('Embedding model changed: use a new Chroma directory and reindex SQLite messages')
                self._collection = collection
            return self._collection

    def upsert(self, message: dict) -> None:
        self.collection.upsert(
            ids=[message['message_id']], documents=[message['content']],
            embeddings=self.embeddings.embed([message['content']]),
            metadatas=[{key: message[key] for key in ('session_id', 'role', 'created_at_utc')} |
                       {'source': 'conversation', 'type': 'message'}],
        )

    def search(self, session_id: str, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        result = self.collection.query(query_embeddings=[vector], n_results=top_k,
                                       where={'session_id': session_id}, include=['distances'])
        return [(message_id, 1.0 - distance) for message_id, distance in
                zip(result['ids'][0], result['distances'][0])]

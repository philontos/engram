import os
from typing import Optional
import numpy as np
import hnswlib
from pathlib import Path

VECTOR_INDEX_PATH = os.getenv("VECTOR_INDEX_PATH", "./data/vectors")
MAX_ELEMENTS = 100_000
DIM_FILE = f"{VECTOR_INDEX_PATH}/dim.txt"


class VectorStore:
    def __init__(self):
        Path(VECTOR_INDEX_PATH).mkdir(parents=True, exist_ok=True)
        self.index_path = f"{VECTOR_INDEX_PATH}/index.bin"
        self.index: Optional[hnswlib.Index] = None
        self.dim: Optional[int] = None

        if Path(DIM_FILE).exists():
            self.dim = int(Path(DIM_FILE).read_text().strip())
            self._load_or_init()

    def _load_or_init(self):
        self.index = hnswlib.Index(space="cosine", dim=self.dim)
        if Path(self.index_path).exists():
            self.index.load_index(self.index_path, max_elements=MAX_ELEMENTS)
        else:
            self.index.init_index(max_elements=MAX_ELEMENTS, ef_construction=200, M=16)
        self.index.set_ef(50)

    def add(self, vector_id: int, embedding: list[float]):
        if self.dim is None:
            self.dim = len(embedding)
            Path(DIM_FILE).write_text(str(self.dim))
            self._load_or_init()

        self.index.add_items(
            np.array([embedding], dtype=np.float32),
            np.array([vector_id]),
        )
        self.index.save_index(self.index_path)

    def search(self, embedding: list[float], k: int = 5) -> list[int]:
        if self.index is None or self.index.get_current_count() == 0:
            return []
        labels, _ = self.index.knn_query(
            np.array([embedding], dtype=np.float32),
            k=min(k, self.index.get_current_count()),
        )
        return labels[0].tolist()


_store: Optional[VectorStore] = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store

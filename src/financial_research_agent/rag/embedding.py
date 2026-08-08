from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class BgeEmbeddingModel:
    """Lazy BGE encoder with a dimension discovered from the running model."""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        self.model_name = model_name
        self._model = None
        self._dimension: int | None = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            probe = self.encode(["向量维度探测"])
            self._dimension = int(probe.shape[1])
        return self._dimension

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            dimension = self._dimension or self.dimension
            return np.empty((0, dimension), dtype=np.float32)
        vectors = self._load().encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        result = np.asarray(vectors, dtype=np.float32)
        if result.ndim != 2:
            raise RuntimeError("embedding model returned an invalid shape")
        self._dimension = int(result.shape[1])
        return result

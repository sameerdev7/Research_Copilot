from __future__ import annotations

import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.EMBEDDING_MODEL_NAME)


# loads the model now instead of on the first request
def warm_up() -> None:
    try:
        _model()
    except Exception:  # noqa: BLE001 - e.g. offline on first run; it will retry on first use
        logger.warning("embedding model warm-up failed", exc_info=True)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def is_loaded() -> bool:
    return _model.cache_info().currsize > 0

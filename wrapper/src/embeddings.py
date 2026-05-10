"""Lazy fastembed loader. The model is downloaded on first use (~120MB,
cached in ~/.cache/fastembed/) and reused for the rest of the process
lifetime.

We pick a small bilingual model (English + Russian) because HappyCake's
customer base is bilingual and the maintainer's tai-memory project uses
the same family — keeping the architectural lineage explicit.

Falls back gracefully: if fastembed import or model download fails, every
public function returns None / empty list and callers must handle that —
memory remains useful via the exact-key path in wrapper/src/memory.py.
"""
from __future__ import annotations
import logging
import os
import threading
from typing import Optional

log = logging.getLogger("happycake.embeddings")

# 384-dim, ~120MB cached. Same family as tai-memory.
MODEL_NAME = os.environ.get(
    "HAPPYCAKE_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

_model = None
_model_lock = threading.Lock()
_disabled = False


def _try_load():
    """Load fastembed lazily. Sets _disabled to True on any failure so we
    don't hammer it on every call."""
    global _model, _disabled
    if _disabled or _model is not None:
        return _model
    with _model_lock:
        if _disabled or _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding  # type: ignore
            _model = TextEmbedding(model_name=MODEL_NAME)
            log.info("loaded fastembed model %s", MODEL_NAME)
        except Exception as e:
            log.warning("fastembed unavailable (%s) — semantic recall disabled", e)
            _disabled = True
            _model = None
    return _model


def embed(text: str) -> Optional[list[float]]:
    """Return a single embedding vector or None if the model is unavailable."""
    if not text:
        return None
    m = _try_load()
    if m is None:
        return None
    try:
        # fastembed returns a generator; take the first.
        gen = m.embed([text])
        for vec in gen:
            return [float(x) for x in vec.tolist()] if hasattr(vec, "tolist") else [float(x) for x in vec]
    except Exception as e:
        log.warning("embed() failed: %s", e)
        return None
    return None


def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Return embeddings for many texts in one model pass. Same fallback rules."""
    if not texts:
        return []
    m = _try_load()
    if m is None:
        return [None] * len(texts)
    try:
        out: list[Optional[list[float]]] = []
        for vec in m.embed(texts):
            out.append([float(x) for x in vec.tolist()] if hasattr(vec, "tolist") else [float(x) for x in vec])
        # If lengths mismatch (model failed mid-batch), pad with None.
        while len(out) < len(texts):
            out.append(None)
        return out
    except Exception as e:
        log.warning("embed_batch() failed: %s", e)
        return [None] * len(texts)


def warm() -> bool:
    """Pre-load the model so the first chat call doesn't pay the download cost.
    Returns True if the model is ready; False otherwise."""
    return embed("warm-up") is not None

"""Optional lazy-loaded cross-encoder reranking for retrieved passages."""

import logging
import os
from threading import Lock


log = logging.getLogger("rag-chatbot.reranker")
_model = None
_model_failed = False
_model_lock = Lock()


def rerank_passages(question, passages):
    """Score query/passage pairs; return None if the model is unavailable."""
    global _model, _model_failed
    model_name = os.getenv("RAG_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2").strip()
    if not model_name or model_name.lower() in {"off", "none", "disabled"} or _model_failed:
        return None
    try:
        if _model is None:
            with _model_lock:
                if _model is None and not _model_failed:
                    from sentence_transformers import CrossEncoder
                    _model = CrossEncoder(model_name, max_length=512)
        if _model is None:
            return None
        pairs = [(question, passage[:2200]) for passage in passages]
        scores = _model.predict(pairs, batch_size=16, show_progress_bar=False)
        return [float(score) for score in scores]
    except Exception:
        _model_failed = True
        log.exception(
            "Cross-encoder reranker unavailable; using hybrid semantic and lexical ranking. "
            "Set RAG_RERANKER_MODEL=off to disable it explicitly."
        )
        return None

import os
import numpy as np

from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")


def create_embeddings(text, progress_callback=None):
    values = [text] if isinstance(text, str) else list(text)
    batch_size = max(1, int(os.getenv("RAG_EMBED_BATCH_SIZE", "64")))
    batches = []
    total = len(values)
    for start in range(0, total, batch_size):
        batch = values[start:start + batch_size]
        batches.append(model.encode(
            batch,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ))
        if progress_callback:
            progress_callback(min(start + len(batch), total), total)
    return np.concatenate(batches, axis=0) if batches else np.empty((0, 0), dtype=np.float32)

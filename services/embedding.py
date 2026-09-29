import os

from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")


def create_embeddings(text):
    embeddings = model.encode(
        text,
        batch_size=max(1, int(os.getenv("RAG_EMBED_BATCH_SIZE", "64"))),
        normalize_embeddings=True,
        convert_to_numpy=True
    )

    return embeddings

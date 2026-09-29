import numpy as np

from services.embedding import model


def retrieve_chunks(question: str, index, chunks: list[str], top_k: int = 5):
    """
    Retrieves the most relevant chunks for a user's question.
    """

    question_embedding = model.encode([question])

    distances, indices = index.search(
        question_embedding.astype("float32"),
        top_k
    )

    retrieved_chunks = [chunks[i] for i in indices[0]]

    return retrieved_chunks
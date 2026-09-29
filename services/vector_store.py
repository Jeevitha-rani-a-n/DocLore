import faiss
import numpy as np

def create_vector_store(embeddings):
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings.astype("float32"))

    return index

def search_vector_store(index, query_embedding, k=3):
    distances, indices = index.search(
        query_embedding.astype("float32"),
        k
    )

    return distances, indices
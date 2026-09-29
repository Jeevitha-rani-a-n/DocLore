"""Hybrid lexical utilities for more robust document question retrieval."""

import difflib
import math
import re
from collections import Counter
from difflib import SequenceMatcher


TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
STOP_WORDS = {
    "a", "about", "after", "again", "all", "also", "am", "an", "and", "any",
    "are", "as", "at", "be", "because", "been", "before", "being", "between",
    "both", "but", "by", "can", "could", "did", "do", "does", "each", "for",
    "from", "had", "has", "have", "he", "her", "here", "hers", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "me", "more", "most",
    "my", "of", "on", "or", "our", "ours", "please", "she", "some", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "to", "under", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "would",
    "you", "your", "yours", "document", "documents", "handbook", "handbooks", "pdf",
    "page", "pages",
}
COMMON_QUERY_CORRECTIONS = {
    "abt": "about", "becasue": "because", "becuase": "because",
    "definately": "definitely", "interpert": "interpret", "recieve": "receive",
    "recieved": "received", "seperate": "separate", "teh": "the",
    "thier": "their", "tht": "that", "waht": "what", "wat": "what",
    "wher": "where", "whre": "where", "wich": "which", "wht": "what",
}


def tokenize(text):
    # Treat hyphenated role names as their component words too: a question that
    # says "vice chancellor" must match PDF text written as "vice-chancellor".
    text = re.sub(r"(?<=[\w])[-\u2010\u2011\u2012\u2013\u2014](?=[\w])", " ", text or "")
    return [term.casefold().strip("'-") for term in TOKEN_RE.findall(text) if term.strip("'-")]


def build_retrieval_metadata(chunks):
    """Precompute token counts and document frequencies once at PDF upload."""
    chunk_counts = [
        Counter(tokenize(re.sub(r"^\[Page\s+\d+\]\s*", "", chunk, flags=re.IGNORECASE)))
        for chunk in chunks
    ]
    document_frequency = Counter()
    vocabulary_frequency = Counter()
    lengths = []
    for counts in chunk_counts:
        document_frequency.update(counts.keys())
        vocabulary_frequency.update(counts)
        lengths.append(sum(counts.values()))
    return {
        "chunk_counts": chunk_counts,
        "document_frequency": document_frequency,
        "vocabulary_frequency": vocabulary_frequency,
        "vocabulary": sorted(vocabulary_frequency),
        "lengths": lengths,
        "average_length": sum(lengths) / max(len(lengths), 1),
        "chunk_count": len(chunks),
    }


def normalize_query(question, metadata):
    """Correct clear misspellings only when the document vocabulary supports it."""
    vocabulary = metadata.get("vocabulary", []) if metadata else []
    if not vocabulary:
        return question

    corrected = []
    for token in TOKEN_RE.findall(question):
        normalized = token.casefold().strip("'-")
        if normalized in COMMON_QUERY_CORRECTIONS:
            corrected.append(COMMON_QUERY_CORRECTIONS[normalized])
            continue
        if (not normalized.isalpha() or len(normalized) < 4 or normalized in STOP_WORDS
                or normalized in metadata["vocabulary_frequency"]):
            corrected.append(token)
            continue

        minimum_ratio = 0.88 if len(normalized) < 6 else 0.82
        candidates = difflib.get_close_matches(normalized, vocabulary, n=4, cutoff=minimum_ratio)
        if not candidates:
            corrected.append(token)
            continue
        best = max(
            candidates,
            key=lambda candidate: (
                SequenceMatcher(None, normalized, candidate).ratio(),
                math.log1p(metadata["vocabulary_frequency"][candidate]),
            ),
        )
        corrected.append(best if best != normalized else token)
    return _replace_query_tokens(question, corrected)


def _replace_query_tokens(question, corrected_tokens):
    token_iter = iter(corrected_tokens)
    return TOKEN_RE.sub(lambda _match: next(token_iter), question)


def bm25_scores(query_variants, metadata):
    """Return BM25 scores and lexical coverage for each chunk."""
    chunk_counts = metadata.get("chunk_counts", [])
    count = len(chunk_counts)
    if not count:
        return [], []

    document_frequency = metadata["document_frequency"]
    lengths = metadata["lengths"]
    average_length = max(metadata["average_length"], 1.0)
    scores = [0.0] * count
    coverages = [0.0] * count
    variants = [
        set(term for term in tokenize(query) if term not in STOP_WORDS)
        for query in query_variants
    ]
    variants = [terms for terms in variants if terms]
    if not variants:
        return scores, coverages

    for index, frequencies in enumerate(chunk_counts):
        length_norm = 1.5 * (1.0 - 0.75 + 0.75 * lengths[index] / average_length)
        for query_terms in variants:
            matched = query_terms.intersection(frequencies)
            coverage = len(matched) / len(query_terms)
            score = 0.0
            for term in matched:
                term_frequency = frequencies[term]
                doc_frequency = document_frequency[term]
                inverse_frequency = math.log1p((count - doc_frequency + 0.5) / (doc_frequency + 0.5))
                score += inverse_frequency * (term_frequency * 2.5) / (term_frequency + length_norm)
            scores[index] = max(scores[index], score)
            coverages[index] = max(coverages[index], coverage)

    maximum = max(scores)
    if maximum > 0:
        scores = [score / maximum for score in scores]
    return scores, coverages

import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
NOT_FOUND = "I couldn't find that information in the uploaded document."


def generate_response(question: str, context: str, normalized_question: str | None = None) -> str:
    """
    Generates an answer using the retrieved document context.
    """
    if not context.strip():
        # Nothing relevant was retrieved: no need to spend an LLM call.
        return NOT_FOUND

    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is missing. Add it to your .env file and restart.")

    options = {}
    if "gpt-oss" in GROQ_MODEL:
        # Reasoning tokens count toward the limit; keep them small so the answer is not cut off.
        options["reasoning_effort"] = "low"

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0,
        top_p=1,
        max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "2048")),
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer ONLY using the provided context. "
                    "Never use outside knowledge. "
                    "The context may contain several passages, each starting with a page label. "
                    "Treat the search interpretation as a spelling correction only; preserve the user's intended meaning. "
                    "Support factual claims with the supplied page labels, and combine passages only when the question needs it. "
                    "If the context only partly answers the question, say what it supports and what is missing. "
                    "Do not infer details from a weak or unrelated passage. "
                    "For direct who/what questions, identify the exact matching person, role, or fact in the passages and answer directly. "
                    "Treat hyphenated and unhyphenated forms of the same title as equivalent, such as 'vice-chancellor' and 'vice chancellor'. "
                    "For broad questions (summaries, key points, author, title) combine the passages carefully. "
                    "Use Markdown (short lists, bold) when it helps readability. "
                    f"If the answer isn't present, reply exactly: '{NOT_FOUND}'"
                )
            },
            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\nQuestion as written:\n{question}"
                    + (f"\n\nSearch interpretation (corrected against document terms):\n{normalized_question}"
                       if normalized_question and normalized_question.casefold() != question.casefold() else "")
                )
            }
        ],
        **options
    )

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("The model returned an empty answer. Try again or raise GROQ_MAX_TOKENS.")
    return content

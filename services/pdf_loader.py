import re
from pypdf import PdfReader


def extract_pages(pdf_path: str) -> list[str]:
    """Return the cleaned text of every page (empty string for pages with no text).

    The list index + 1 is the page number, so page-aware retrieval stays correct.
    """
    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("This PDF is password-protected.")

    pages = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
        page_text = re.sub(r"(?<=\w)-\n(?=[a-z])", "", page_text)
        lines = [re.sub(r"[\t ]+", " ", line).strip() for line in page_text.split("\n")]
        page_text = "\n".join(line for line in lines if line)
        page_text = re.sub(r"\n{3,}", "\n\n", page_text)
        pages.append(page_text.strip())
    return pages


def extract_text(pdf_path: str) -> str:
    return "\n\n".join(page for page in extract_pages(pdf_path) if page)

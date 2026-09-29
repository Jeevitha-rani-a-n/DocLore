"""Create a PDF copy with a markup annotation over a retrieved passage."""

import math
import re
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight
from pypdf.generic import ArrayObject, FloatObject


STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been",
    "before", "being", "between", "could", "does", "each", "from", "have",
    "into", "more", "most", "only", "other", "over", "same", "some",
    "such", "than", "that", "their", "there", "these", "they", "this",
    "those", "through", "under", "very", "what", "when", "where", "which",
    "while", "with", "would", "your", "the", "for", "was", "were", "will",
    "has", "had", "his", "her", "its", "our", "you", "she", "him", "them",
    "then", "not", "but", "can", "may", "all", "any", "who", "how", "why",
    "did", "from", "been", "being", "a", "an", "as", "at", "by", "in", "is",
    "it", "of", "on", "or", "to", "be", "if", "we", "he", "i", "me", "my",
}


def _content_terms(text):
    return {
        term.lower() for term in re.findall(r"[\w'-]+", text)
        if len(term) > 2 and term.lower() not in STOP_WORDS
    }


def _fragment_width(text, font_dictionary, font_size, horizontal_scale):
    if font_dictionary:
        try:
            font = font_dictionary.get_object()
            widths = font.get("/Widths")
            first_char = int(font.get("/FirstChar", 0))
            if widths:
                width = sum(
                    float(widths[ord(char) - first_char])
                    for char in text
                    if 0 <= ord(char) - first_char < len(widths)
                ) / 1000
                if width > 0:
                    return width * font_size * horizontal_scale
        except (AttributeError, IndexError, TypeError, ValueError):
            pass
    return max(len(text) * font_size * 0.5 * horizontal_scale, font_size * 0.5)


def highlighted_pdf(pdf_path, citation_texts):
    """Return a copy with passages from all citations highlighted."""
    if isinstance(citation_texts, str):
        citation_texts = [citation_texts]

    reader = PdfReader(pdf_path)
    terms_by_page = {}
    for citation_text in citation_texts[:3]:
        page_match = re.search(r"\[Page (\d+)\]\s*", citation_text, re.IGNORECASE)
        if not page_match:
            continue
        page_index = int(page_match.group(1)) - 1
        if not 0 <= page_index < len(reader.pages):
            continue
        source_text = citation_text[page_match.end():].removesuffix("...")
        source_terms = _content_terms(source_text)
        if source_terms:
            terms_by_page.setdefault(page_index, set()).update(source_terms)
    if not terms_by_page:
        return None

    segments_by_page = {}
    for page_index, source_terms in terms_by_page.items():
        page = reader.pages[page_index]
        segments = []

        def collect_segment(text, user_matrix, text_matrix, font_dictionary, font_size):
            terms = _content_terms(text)
            if len(terms) < 3:
                return
            overlap = len(terms & source_terms)
            threshold = max(2, math.ceil(len(terms) * 0.3))
            if overlap < threshold:
                return

            cm = [float(value) for value in user_matrix]
            tm = [float(value) for value in text_matrix]
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            horizontal_scale = math.hypot(cm[0], cm[1]) or 1.0
            vertical_scale = math.hypot(cm[2], cm[3]) or 1.0
            height = max(abs(float(font_size)) * vertical_scale, 4.0)
            width = _fragment_width(text, font_dictionary, abs(float(font_size)), horizontal_scale)
            segments.append((x, y, width, height))

        page.extract_text(visitor_text=collect_segment)
        if segments:
            segments_by_page[page_index] = segments

    if not segments_by_page:
        return None

    writer = PdfWriter(clone_from=reader)
    added = 0
    for page_index, segments in segments_by_page.items():
        bounds = reader.pages[page_index].mediabox
        page_left, page_bottom = float(bounds.left), float(bounds.bottom)
        page_right, page_top = float(bounds.right), float(bounds.top)
        for x, baseline, width, height in segments[:80]:
            left = max(page_left, x - 1.5)
            right = min(page_right, x + width + 1.5)
            bottom = max(page_bottom, baseline - height * 0.25)
            top = min(page_top, baseline + height * 0.85)
            if right <= left or top <= bottom:
                continue
            quad_points = ArrayObject([
                FloatObject(left), FloatObject(bottom),
                FloatObject(right), FloatObject(bottom),
                FloatObject(left), FloatObject(top),
                FloatObject(right), FloatObject(top),
            ])
            annotation = Highlight(
                rect=(left, bottom, right, top),
                quad_points=quad_points,
                highlight_color="70d9c0",
            )
            writer.add_annotation(page_number=page_index, annotation=annotation)
            added += 1

    if not added:
        return None
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output

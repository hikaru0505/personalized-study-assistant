"""
Extract page-tagged text from a PDF file using pypdf.

Returning per-page text (instead of one flat string) is what makes
page-numbered source citations and "jump to page N" possible elsewhere
in the app.
"""

from typing import List, Dict
from pypdf import PdfReader


def extract_pages(pdf_path: str) -> List[Dict]:
    """
    Returns a list like [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]
    Pages with no extractable text (e.g. scanned/image-only pages) are
    included with an empty string rather than skipped, so page numbers
    stay aligned with the actual PDF.
    """
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text() or ""
        pages.append({"page": i + 1, "text": page_text})
    return pages


def extract_text(pdf_path: str) -> str:
    """Flat full-document text, for callers that don't need page boundaries
    (e.g. the summary generator)."""
    return "\n".join(p["text"] for p in extract_pages(pdf_path) if p["text"])

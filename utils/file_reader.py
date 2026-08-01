"""
Single entry point for extracting page-tagged text from an uploaded study
document, dispatching to pdf_reader or docx_reader by extension.
"""

import os
from typing import List, Dict

from utils.pdf_reader import extract_pages as extract_pdf_pages
from utils.docx_reader import extract_pages as extract_docx_pages

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def is_allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def extract_pages(filepath: str) -> List[Dict]:
    """
    Returns [{"page": n, "text": "..."}, ...]. For DOCX this is always a
    single "page" (see docx_reader for why).
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return extract_pdf_pages(filepath)
    elif ext == ".docx":
        return extract_docx_pages(filepath)
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Please upload a .pdf or .docx file.")


def extract_text(filepath: str) -> str:
    """Flat full-document text (all pages joined), for summary/quiz generation."""
    return "\n".join(p["text"] for p in extract_pages(filepath) if p["text"])

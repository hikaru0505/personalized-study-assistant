"""
Build and load a per-document FAISS vector store, with page numbers carried
through as chunk metadata so retrieved chunks can be cited by page.

Previously this project used one single shared "faiss_index/" folder that
got overwritten by every upload. Now each document gets its own folder
(faiss_index/<doc_id>/), which is what makes the document library and
reopening past uploads possible - you can hold multiple documents'
indexes at once instead of only ever having the most recent one.
"""

import os
from typing import List, Dict

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import FastEmbedEmbeddings

FAISS_ROOT = "faiss_index"
os.makedirs(FAISS_ROOT, exist_ok=True)

# FastEmbed (ONNX Runtime) instead of sentence-transformers/HuggingFaceEmbeddings
# (PyTorch). Same LangChain Embeddings interface and no API key needed, but
# without PyTorch's ~400-600MB import/runtime footprint - PyTorch alone was
# enough to blow past a 512MB hosting limit (e.g. Render's free/Starter
# tiers) before a single request was even served. BAAI/bge-small-en-v1.5
# (FastEmbed's default model) is a similarly-sized, similarly-performing
# small embedding model, so retrieval quality is comparable.
_embeddings = FastEmbedEmbeddings()


def _index_path(doc_id: str) -> str:
    return os.path.join(FAISS_ROOT, doc_id)


def create_vector_store(doc_id: str, pages: List[Dict]) -> FAISS:
    """
    pages: [{"page": n, "text": "..."}, ...]

    Splits each page's text into overlapping chunks (chunk_size=600,
    chunk_overlap=150 - small enough that a single fact/definition stays
    intact rather than diluted inside a large chunk), tagging every chunk
    with which page it came from, then saves the FAISS index under this
    document's own folder.
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=150)

    all_chunks: List[str] = []
    all_metadata: List[dict] = []
    chunk_idx = 0

    for page in pages:
        if not page["text"].strip():
            continue
        page_chunks = splitter.split_text(page["text"])
        for chunk in page_chunks:
            all_chunks.append(chunk)
            all_metadata.append({"chunk_index": chunk_idx, "page": page["page"]})
            chunk_idx += 1

    if not all_chunks:
        raise ValueError("No extractable text found in this document.")

    db = FAISS.from_texts(all_chunks, _embeddings, metadatas=all_metadata)
    db.save_local(_index_path(doc_id))
    return db


def load_vector_store(doc_id: str) -> FAISS:
    return FAISS.load_local(
        _index_path(doc_id),
        _embeddings,
        allow_dangerous_deserialization=True,
    )


def delete_vector_store(doc_id: str) -> None:
    import shutil
    path = _index_path(doc_id)
    if os.path.isdir(path):
        shutil.rmtree(path)
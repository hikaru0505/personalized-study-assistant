"""
Answer a user's question using retrieved document chunks (RAG).
"""

from utils.llm_config import llm


def answer_question(docs_with_scores, question: str, chat_history_text: str = ""):
    """
    docs_with_scores: list of (Document, distance) tuples from
        FAISS.similarity_search_with_score - lower distance = more similar.
    question: the user's natural-language question (already rewritten to be
        standalone if this is a follow-up - see utils/chat_memory.py)
    chat_history_text: optional short transcript of prior Q&A on this
        document, included so the model's tone/answer stays consistent
        with the conversation so far (retrieval itself uses the
        standalone rewritten question, not this raw history).

    Returns:
        (answer_text, sources) where `sources` is a list of dicts:
        [{"chunk_index": int, "page": int, "snippet": str, "relevance": int}, ...]
    """
    docs = [doc for doc, _score in docs_with_scores]
    distances = [score for _doc, score in docs_with_scores]

    context = "\n\n".join(
        f"[Source {i + 1} - page {doc.metadata.get('page', '?')}]\n{doc.page_content}"
        for i, doc in enumerate(docs)
    )

    history_block = f"\nPrior conversation on this document:\n{chat_history_text}\n" if chat_history_text else ""

    prompt = f"""
    Use the following context to answer the question. Sources are ordered
    from most to least relevant.
    If the answer isn't contained in the context, say you don't know
    instead of making something up.
    {history_block}
    Context:
    {context}

    Question:
    {question}

    Answer:
    """

    response = llm.invoke(prompt)
    answer = response.content

    if distances:
        min_d, max_d = min(distances), max(distances)
        spread = max_d - min_d
        relevances = [
            100 if spread == 0 else round(100 * (max_d - d) / spread)
            for d in distances
        ]
    else:
        relevances = []

    sources = [
        {
            "chunk_index": doc.metadata.get("chunk_index", i),
            "page": doc.metadata.get("page", 1),
            "snippet": doc.page_content[:300].strip() + (
                "..." if len(doc.page_content) > 300 else ""
            ),
            "relevance": relevances[i] if i < len(relevances) else None,
        }
        for i, doc in enumerate(docs)
    ]

    return answer, sources

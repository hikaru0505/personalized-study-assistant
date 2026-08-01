"""
Resolve follow-up questions against prior conversation turns.

Example: user asks "Explain LangChain", gets an answer, then asks
"Give an example." Taken on its own, "give an example" retrieves nothing
useful from the vector store - there's no keyword to match against. This
module asks the LLM to rewrite the follow-up into a standalone question
first ("Give an example of LangChain"), and *that* rewritten question is
what actually gets used for retrieval + the final answer.
"""

from typing import List, Dict
from utils.llm_config import llm

REWRITE_PROMPT = """
Given the recent conversation history and a new follow-up question, rewrite
the follow-up into a fully standalone question that makes sense with no
prior context. If the follow-up is already standalone, return it unchanged.

Respond with ONLY the rewritten question text - no quotes, no commentary.

Conversation history:
{history}

Follow-up question:
{question}

Standalone question:
"""


def rewrite_followup(history: List[Dict], question: str) -> str:
    """
    history: list of {"question": ..., "answer": ...} dicts, oldest first.
    Only the last 3 turns are used - older context rarely helps and just
    adds tokens/latency.
    """
    if not history:
        return question

    recent = history[-3:]
    history_text = "\n".join(
        f"Q: {turn['question']}\nA: {turn['answer'][:300]}" for turn in recent
    )

    prompt = REWRITE_PROMPT.format(history=history_text, question=question)
    response = llm.invoke(prompt)
    rewritten = response.content.strip().strip('"')

    # Guard against a degenerate/empty rewrite - fall back to the original
    return rewritten if rewritten else question


def format_history_for_prompt(history: List[Dict], max_turns: int = 3) -> str:
    """A short transcript to give the final answer prompt some conversational
    continuity (separate from the retrieval rewrite above)."""
    if not history:
        return ""
    recent = history[-max_turns:]
    return "\n".join(
        f"Q: {turn['question']}\nA: {turn['answer'][:300]}" for turn in recent
    )

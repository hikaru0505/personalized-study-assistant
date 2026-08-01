"""
Generate flashcards as structured data (question/answer/topic per card)
instead of a single text blob - this is what makes per-card spaced
repetition tracking possible (each card needs a stable identity to attach
review history to).
"""

import json
import re
from typing import List, Optional

from utils.llm_config import llm

FLASHCARD_PROMPT = """
Generate {num_cards} flashcards for studying the following content.
Tag each with a short "topic" label (2-4 words).
{focus_note}
Content:
{content}

Respond with ONLY a valid JSON array and nothing else - no markdown fences,
no commentary. Match this schema exactly:

[
  {{"topic": "...", "question": "...", "answer": "..."}}
]
"""


def _extract_json_array(raw: str) -> str:
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
        if match:
            return match.group(0)
        raise


def generate_flashcards(content: str, num_cards: int = 10,
                         focus_topics: Optional[List[str]] = None) -> List[dict]:
    """
    Returns a list of {"topic": str, "question": str, "answer": str} dicts.
    focus_topics: sub-topics the student struggled with on a past quiz -
    when provided, most cards are weighted toward reinforcing those.
    """
    focus_note = ""
    if focus_topics:
        topics_str = ", ".join(focus_topics)
        focus_note = (
            f"\nThe student previously struggled with these topics: {topics_str}. "
            f"Weight most of the flashcards toward reinforcing those topics.\n"
        )

    prompt = FLASHCARD_PROMPT.format(num_cards=num_cards, focus_note=focus_note, content=content)
    response = llm.invoke(prompt)

    try:
        json_str = _extract_json_array(response.content)
        cards = json.loads(json_str)
    except (json.JSONDecodeError, AttributeError):
        return []

    valid_cards = []
    for c in cards:
        if isinstance(c, dict) and "question" in c and "answer" in c:
            c.setdefault("topic", "General")
            valid_cards.append(c)
    return valid_cards

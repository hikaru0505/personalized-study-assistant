"""
Generate a structured, gradeable quiz with a mix of question types and a
configurable difficulty level.

Supported question types:
    mcq           - 4 options, one correct
    true_false    - options are always {"A": "True", "B": "False"}
    fill_blank    - a sentence with a blank; graded by an LLM comparison
                    against the expected answer (exact string matching is
                    too brittle for free-text answers)
    short_answer  - a short free-text answer; also LLM-graded
    match         - a small set of left/right pairs; graded by comparing
                    the student's selected right-hand choice for each left
                    item against the correct mapping
"""

import json
import re
from typing import List

from utils.llm_config import llm

DIFFICULTY_GUIDANCE = {
    "easy": "Use simple, direct recall questions with obvious wording. Avoid trick questions.",
    "medium": "Mix recall with light application - some questions should require connecting two ideas.",
    "hard": "Favor application and analysis questions over simple recall. Include some questions that "
            "require distinguishing between similar/adjacent concepts.",
}

QUIZ_PROMPT = """
You are creating a quiz for a student studying the content below.

Content:
{content}

Difficulty: {difficulty}
{difficulty_guidance}

Generate exactly {num_questions} questions using this MIX of question types
(include all of these types across the set, roughly evenly):
- "mcq": 4 options under keys A-D, one correct
- "true_false": exactly 2 options, {{"A": "True", "B": "False"}}
- "fill_blank": a "question" containing a blank shown as "_____", and an
  "answer_text" holding the exact word/phrase that fills the blank
- "short_answer": an open-ended question and an "answer_text" holding a
  concise model answer (1 sentence)
- "match": a "pairs" list of 3-4 {{"left": "...", "right": "..."}} objects
  that the student must match correctly

Tag every question with a short "topic" label (2-4 words) describing the
sub-topic it tests, so related questions share the same topic label.

Respond with ONLY a valid JSON array and nothing else - no markdown code
fences, no commentary. Each item must include a "type" field and match one
of these shapes:

[
  {{"type": "mcq", "topic": "...", "question": "...", "options": {{"A":"..","B":"..","C":"..","D":".."}}, "correct_answer": "A"}},
  {{"type": "true_false", "topic": "...", "question": "...", "options": {{"A":"True","B":"False"}}, "correct_answer": "A"}},
  {{"type": "fill_blank", "topic": "...", "question": "... _____ ...", "answer_text": "..."}},
  {{"type": "short_answer", "topic": "...", "question": "...", "answer_text": "..."}},
  {{"type": "match", "topic": "...", "question": "Match the following:", "pairs": [{{"left":"..","right":".."}}]}}
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


def generate_quiz(content: str, num_questions: int = 10, difficulty: str = "medium") -> List[dict]:
    """
    difficulty: "easy" | "medium" | "hard". ("adaptive" is resolved to one
    of these by the caller in app.py before this function is called, based
    on the student's past performance on this document.)
    """
    difficulty = difficulty if difficulty in DIFFICULTY_GUIDANCE else "medium"
    prompt = QUIZ_PROMPT.format(
        content=content,
        difficulty=difficulty,
        difficulty_guidance=DIFFICULTY_GUIDANCE[difficulty],
        num_questions=num_questions,
    )
    response = llm.invoke(prompt)

    try:
        json_str = _extract_json_array(response.content)
        questions = json.loads(json_str)
    except (json.JSONDecodeError, AttributeError):
        return []

    valid_questions = []
    for q in questions:
        if not isinstance(q, dict) or "question" not in q or "type" not in q:
            continue
        q.setdefault("topic", "General")
        valid_questions.append(q)

    return valid_questions

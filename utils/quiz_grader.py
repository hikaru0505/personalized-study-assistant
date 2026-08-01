"""
Grade a submitted quiz.

MCQ / True-False / Match are graded by exact comparison (deterministic,
no LLM call needed). Fill-in-the-blank and Short Answer are free text, so
exact string matching would unfairly mark correct-but-differently-worded
answers wrong - those are graded by a single batched LLM call instead of
one call per question (keeps latency/cost down).
"""

import json
import re
from typing import List, Dict

from utils.llm_config import llm

BATCH_GRADE_PROMPT = """
You are grading a student's short-answer quiz responses. For each item,
decide if the student's answer is substantively correct compared to the
expected answer (minor wording differences are fine; the core fact/idea
must be right).

Items:
{items}

Respond with ONLY a JSON array of booleans, one per item in the same
order, and nothing else. Example: [true, false, true]
"""


def _grade_mcq_like(question: dict, student_answer: str) -> bool:
    return student_answer == question.get("correct_answer")


def _grade_match(question: dict, student_answer: str) -> bool:
    """
    student_answer for a match question arrives as a JSON string mapping
    each left item's index to the chosen right-hand text, e.g.
    '{"0": "Definition A", "1": "Definition B"}'
    """
    try:
        student_map = json.loads(student_answer) if student_answer else {}
    except json.JSONDecodeError:
        return False

    pairs = question.get("pairs", [])
    if not pairs:
        return False

    for i, pair in enumerate(pairs):
        if student_map.get(str(i)) != pair.get("right"):
            return False
    return True


def grade_quiz(questions: List[dict], answers: Dict[str, str]) -> List[dict]:
    """
    questions: the quiz's question list (as generated/stored)
    answers: {"q0": "A", "q1": "some text", ...} keyed by "q{index}"

    Returns a list of per-question result dicts:
        {"index": i, "is_correct": bool, "student_answer": str}
    """
    results = [None] * len(questions)
    llm_grade_indices = []
    llm_grade_items = []

    for i, q in enumerate(questions):
        key = f"q{i}"
        student_answer = answers.get(key, "")
        qtype = q.get("type", "mcq")

        if qtype in ("mcq", "true_false"):
            results[i] = {"index": i, "is_correct": _grade_mcq_like(q, student_answer), "student_answer": student_answer}
        elif qtype == "match":
            results[i] = {"index": i, "is_correct": _grade_match(q, student_answer), "student_answer": student_answer}
        elif qtype in ("fill_blank", "short_answer"):
            llm_grade_indices.append(i)
            llm_grade_items.append({
                "question": q.get("question"),
                "expected_answer": q.get("answer_text", ""),
                "student_answer": student_answer,
            })
            results[i] = {"index": i, "is_correct": False, "student_answer": student_answer}  # placeholder
        else:
            results[i] = {"index": i, "is_correct": False, "student_answer": student_answer}

    if llm_grade_items:
        items_text = "\n".join(
            f"{n + 1}. Question: {item['question']}\n   Expected: {item['expected_answer']}\n   Student answered: {item['student_answer']}"
            for n, item in enumerate(llm_grade_items)
        )
        prompt = BATCH_GRADE_PROMPT.format(items=items_text)
        response = llm.invoke(prompt)

        try:
            cleaned = re.sub(r"^```(json)?|```$", "", response.content.strip(), flags=re.MULTILINE).strip()
            verdicts = json.loads(cleaned)
        except (json.JSONDecodeError, AttributeError):
            verdicts = [False] * len(llm_grade_items)

        for idx, verdict in zip(llm_grade_indices, verdicts):
            results[idx]["is_correct"] = bool(verdict)

    return results

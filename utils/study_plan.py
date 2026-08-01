"""
Create a day-by-day study plan as structured data (not a text blob), so
the UI can render progress checkboxes, a priority rating, and per-day
time estimates.

Kept deterministic/template-based (no LLM call) so it's instant - it's
still genuinely adaptive because the day content changes based on the
student's weak topics from their most recent quiz attempt.
"""

from typing import List, Optional


def _priority_stars(weak_topic_count: int) -> int:
    """More weak topics -> higher priority (more stars), capped 1-5."""
    return max(1, min(5, 2 + weak_topic_count))


def create_study_plan(topic: str, weak_topics: Optional[List[str]] = None) -> dict:
    """
    Returns:
        {
          "title": str,
          "priority": int (1-5),
          "estimated_minutes_per_day": int,
          "days": [{"day": 1, "title": str, "tasks": [str, ...]}, ...]
        }
    """
    weak_topics = weak_topics or []

    if weak_topics:
        primary = weak_topics[0]
        rest = weak_topics[1:] or [primary]
        days = [
            {"day": 1, "title": f'Deep-review "{primary}"',
             "tasks": [f'Re-read the summary section(s) covering "{primary}"',
                       f'Redo flashcards tagged "{primary}"']},
            {"day": 2, "title": "Review remaining weak topics",
             "tasks": [f'Cover: {", ".join(rest)}', "Redo flashcards for these topics"]},
            {"day": 3, "title": "Targeted flashcard drilling",
             "tasks": ["Run a spaced-repetition review session focused on weak topics"]},
            {"day": 4, "title": "Retake the quiz",
             "tasks": [f"Retake the quiz on {topic}", "Compare your score to your last attempt"]},
            {"day": 5, "title": "Full mock test",
             "tasks": ["Take a quiz covering all topics, not just the weak ones"]},
        ]
        title = f"Personalized Study Plan: {topic}"
    else:
        days = [
            {"day": 1, "title": "Learn the fundamentals", "tasks": [f"Read the summary of {topic}"]},
            {"day": 2, "title": "Study worked examples", "tasks": ["Go through flashcards once"]},
            {"day": 3, "title": "Practice", "tasks": ["Take the generated quiz"]},
            {"day": 4, "title": "Revise weak areas", "tasks": ["Re-read the summary; redo missed flashcards"]},
            {"day": 5, "title": "Mock test", "tasks": ["Take a full quiz under timed conditions"]},
        ]
        title = f"Study Plan: {topic}"

    return {
        "title": title,
        "priority": _priority_stars(len(weak_topics)),
        "estimated_minutes_per_day": 25,
        "days": days,
    }

"""
A simplified version of the SM-2 spaced-repetition algorithm (the one Anki
is originally based on).

Each flashcard review has 4 possible ratings from the student: Again, Hard,
Good, Easy. Based on the rating, we adjust:
  - ease_factor: how quickly the interval grows for this card (min 1.3)
  - interval_days: how many days until this card is due again
  - repetitions: consecutive successful (non-"Again") reviews in a row
"""

from datetime import datetime, timedelta, timezone

MIN_EASE = 1.3


def schedule_next_review(rating: str, ease_factor: float, interval_days: float, repetitions: int):
    """
    rating: "again" | "hard" | "good" | "easy"
    Returns (new_ease_factor, new_interval_days, new_repetitions, next_review_date_iso)
    """
    rating = rating.lower()

    if rating == "again":
        repetitions = 0
        interval_days = 1
        ease_factor = max(MIN_EASE, ease_factor - 0.2)
    elif rating == "hard":
        repetitions += 1
        interval_days = max(1, interval_days * 1.2)
        ease_factor = max(MIN_EASE, ease_factor - 0.15)
    elif rating == "good":
        repetitions += 1
        interval_days = interval_days * ease_factor if repetitions > 1 else 1
    elif rating == "easy":
        repetitions += 1
        interval_days = (interval_days * ease_factor * 1.3) if repetitions > 1 else 2
        ease_factor = ease_factor + 0.15
    else:
        raise ValueError(f"Unknown rating: {rating}")

    next_date = (datetime.now(timezone.utc) + timedelta(days=interval_days)).date().isoformat()
    return round(ease_factor, 2), round(interval_days, 2), repetitions, next_date

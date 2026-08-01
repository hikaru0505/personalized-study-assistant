"""
Small helper for stashing transient per-session data (the generated quiz
questions + document summary) between two separate HTTP requests:
  1) POST / -> generates and shows the quiz
  2) POST /quiz/submit -> needs the original quiz + summary to grade
     answers and regenerate adaptive study aids

Flask's built-in `session` is a signed cookie stored client-side, which is
too small/fragile to hold a full quiz + document summary. Instead we write
that data to a small JSON file per session id in `session_data/`, and only
keep the session id itself in the cookie.
"""

import json
import os

SESSION_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "session_data")
os.makedirs(SESSION_DIR, exist_ok=True)


def _path_for(session_id: str) -> str:
    # session_id is a uuid4 we generate ourselves, but sanitize defensively
    # anyway before using it as part of a filesystem path.
    safe_id = "".join(c for c in session_id if c.isalnum() or c == "-")
    return os.path.join(SESSION_DIR, f"{safe_id}.json")


def save_session_data(session_id: str, data: dict) -> None:
    with open(_path_for(session_id), "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_session_data(session_id: str) -> dict:
    path = _path_for(session_id)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

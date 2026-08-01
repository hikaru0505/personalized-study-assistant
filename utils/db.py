"""
SQLite persistence layer for the whole app.

Design notes:
- No full user-account system - each browser gets an anonymous session id
  (signed cookie, see app.py's get_session_id()), so history is tied to
  the browser rather than a login.
- Tables:
    documents        - one row per uploaded file, with cached summary
    pages            - page-level text per document (for keyword search
                       and page-numbered source citations)
    quizzes          - a generated quiz's questions (JSON), reusable/resumable
    quiz_attempts    - a graded attempt at a quiz
    flashcards       - individual flashcards generated for a document
    flashcard_reviews- per-user spaced-repetition scheduling state (SM-2 lite)
    chat_turns       - question/answer history per document (chat memory)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "study_assistant.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


EXPECTED_COLUMNS = {
    "documents": {"id", "session_id", "filename", "display_name", "file_ext",
                  "num_pages", "summary", "uploaded_at"},
    "quiz_attempts": {"id", "session_id", "document_id", "quiz_id", "document_name",
                       "difficulty", "score", "total", "duration_seconds",
                       "topic_breakdown", "weak_topics", "created_at"},
    "flashcards": {"id", "document_id", "question", "answer", "topic", "created_at"},
}


def _drop_outdated_tables(conn: sqlite3.Connection) -> None:
    """
    If a table from an older version of this schema already exists on disk
    (e.g. a quiz_attempts table from before per-document tracking was
    added) but is missing columns the current code expects, drop it so
    CREATE TABLE IF NOT EXISTS below recreates it fresh.

    This is a blunt "drop and recreate" rather than a real migration -
    appropriate for local dev/demo data where a git pull can move the
    schema forward, but not for data you actually need to keep. If you
    need to preserve real data across a schema change, back up
    study_assistant.db first.
    """
    existing_tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table, expected_cols in EXPECTED_COLUMNS.items():
        if table not in existing_tables:
            continue
        actual_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not expected_cols.issubset(actual_cols):
            conn.execute(f"DROP TABLE {table}")


def init_db() -> None:
    conn = get_connection()
    _drop_outdated_tables(conn)
    conn.commit()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            filename TEXT NOT NULL,        -- stored filename on disk
            display_name TEXT NOT NULL,    -- friendly name shown in the UI
            file_ext TEXT NOT NULL,
            num_pages INTEGER NOT NULL DEFAULT 1,
            summary TEXT,
            uploaded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quizzes (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            difficulty TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            quiz_id TEXT,
            document_name TEXT NOT NULL,
            difficulty TEXT,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            duration_seconds INTEGER,
            topic_breakdown TEXT NOT NULL,   -- JSON: {topic: {"correct": n, "total": n}}
            weak_topics TEXT NOT NULL,       -- JSON list
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            topic TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS flashcard_reviews (
            flashcard_id TEXT NOT NULL REFERENCES flashcards(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            ease_factor REAL NOT NULL DEFAULT 2.5,
            interval_days REAL NOT NULL DEFAULT 1,
            repetitions INTEGER NOT NULL DEFAULT 0,
            next_review_date TEXT NOT NULL,
            last_rating TEXT,
            PRIMARY KEY (flashcard_id, session_id)
        );

        CREATE TABLE IF NOT EXISTS chat_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

def create_document(doc_id: str, session_id: str, filename: str, display_name: str,
                     file_ext: str, num_pages: int, summary: str) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO documents
           (id, session_id, filename, display_name, file_ext, num_pages, summary, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_id, session_id, filename, display_name, file_ext, num_pages, summary, _now()),
    )
    conn.commit()
    conn.close()


def get_document(doc_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_documents(session_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents WHERE session_id = ? ORDER BY uploaded_at DESC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_document(doc_id: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Pages (for keyword search + page-numbered citations)
# --------------------------------------------------------------------------

def save_pages(doc_id: str, pages: List[dict]) -> None:
    conn = get_connection()
    conn.executemany(
        "INSERT INTO pages (document_id, page_number, text) VALUES (?, ?, ?)",
        [(doc_id, p["page"], p["text"]) for p in pages],
    )
    conn.commit()
    conn.close()


def get_pages(doc_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT page_number, text FROM pages WHERE document_id = ? ORDER BY page_number",
        (doc_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def search_pages(doc_id: str, query: str) -> List[dict]:
    """
    Simple case-insensitive keyword search across a document's FULL page
    text (the raw extracted text saved via save_pages() at upload time) -
    not the LLM-generated summary. This is intentionally a plain substring
    search, distinct from the semantic FAISS search used for RAG chat
    answers - worth explaining the difference if asked.
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return []
    matches = []
    for page in get_pages(doc_id):
        text = page["text"]
        idx = text.lower().find(query_lower)
        if idx != -1:
            start = max(0, idx - 60)
            end = min(len(text), idx + len(query_lower) + 60)
            snippet = ("..." if start > 0 else "") + text[start:end].strip() + ("..." if end < len(text) else "")
            matches.append({"page": page["page_number"], "snippet": snippet})
    return matches


# --------------------------------------------------------------------------
# Quizzes / attempts
# --------------------------------------------------------------------------

def save_quiz(quiz_id: str, document_id: str, difficulty: str, questions: list) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO quizzes (id, document_id, difficulty, questions_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (quiz_id, document_id, difficulty, json.dumps(questions), _now()),
    )
    conn.commit()
    conn.close()


def get_quiz(quiz_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
    conn.close()
    if not row:
        return None
    quiz = dict(row)
    quiz["questions"] = json.loads(quiz["questions_json"])
    return quiz


def get_latest_quiz(document_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM quizzes WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    quiz = dict(row)
    quiz["questions"] = json.loads(quiz["questions_json"])
    return quiz


def save_attempt(session_id: str, document_id: str, document_name: str, quiz_id: str,
                  difficulty: str, score: int, total: int, duration_seconds: Optional[int],
                  topic_breakdown: Dict[str, Dict[str, int]], weak_topics: List[str]) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO quiz_attempts
           (session_id, document_id, quiz_id, document_name, difficulty, score, total,
            duration_seconds, topic_breakdown, weak_topics, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, document_id, quiz_id, document_name, difficulty, score, total,
         duration_seconds, json.dumps(topic_breakdown), json.dumps(weak_topics), _now()),
    )
    conn.commit()
    conn.close()


def get_attempts(session_id: str, document_id: str = None) -> List[dict]:
    conn = get_connection()
    if document_id:
        rows = conn.execute(
            "SELECT * FROM quiz_attempts WHERE session_id = ? AND document_id = ? ORDER BY created_at ASC",
            (session_id, document_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM quiz_attempts WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    conn.close()
    attempts = []
    for row in rows:
        a = dict(row)
        a["topic_breakdown"] = json.loads(a["topic_breakdown"])
        a["weak_topics"] = json.loads(a["weak_topics"])
        attempts.append(a)
    return attempts


# --------------------------------------------------------------------------
# Flashcards + spaced repetition (SM-2 lite)
# --------------------------------------------------------------------------

def save_flashcards(document_id: str, cards: List[dict]) -> List[dict]:
    """cards: [{"id", "question", "answer", "topic"}, ...]. Returns the same
    list back for convenience (ids are generated by the caller)."""
    conn = get_connection()
    conn.executemany(
        "INSERT INTO flashcards (id, document_id, question, answer, topic, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(c["id"], document_id, c["question"], c["answer"], c.get("topic"), _now()) for c in cards],
    )
    conn.commit()
    conn.close()
    return cards


def get_flashcards(document_id: str) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM flashcards WHERE document_id = ? ORDER BY created_at ASC",
        (document_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_or_init_review_state(flashcard_id: str, session_id: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM flashcard_reviews WHERE flashcard_id = ? AND session_id = ?",
        (flashcard_id, session_id),
    ).fetchone()
    if row:
        conn.close()
        return dict(row)

    today = datetime.now(timezone.utc).date().isoformat()
    conn.execute(
        """INSERT INTO flashcard_reviews
           (flashcard_id, session_id, ease_factor, interval_days, repetitions, next_review_date, last_rating)
           VALUES (?, ?, 2.5, 1, 0, ?, NULL)""",
        (flashcard_id, session_id, today),
    )
    conn.commit()
    conn.close()
    return {
        "flashcard_id": flashcard_id, "session_id": session_id, "ease_factor": 2.5,
        "interval_days": 1, "repetitions": 0, "next_review_date": today, "last_rating": None,
    }


def save_review_state(flashcard_id: str, session_id: str, ease_factor: float,
                       interval_days: float, repetitions: int, next_review_date: str,
                       last_rating: str) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE flashcard_reviews
           SET ease_factor = ?, interval_days = ?, repetitions = ?,
               next_review_date = ?, last_rating = ?
           WHERE flashcard_id = ? AND session_id = ?""",
        (ease_factor, interval_days, repetitions, next_review_date, last_rating,
         flashcard_id, session_id),
    )
    conn.commit()
    conn.close()


def get_due_flashcards(document_id: str, session_id: str) -> List[dict]:
    """Flashcards for this document whose next_review_date is today or earlier
    (or that have never been reviewed yet)."""
    today = datetime.now(timezone.utc).date().isoformat()
    cards = get_flashcards(document_id)
    due = []
    for card in cards:
        state = get_or_init_review_state(card["id"], session_id)
        if state["next_review_date"] <= today:
            card_with_state = dict(card)
            card_with_state["review_state"] = state
            due.append(card_with_state)
    return due


# --------------------------------------------------------------------------
# Chat memory
# --------------------------------------------------------------------------

def save_chat_turn(session_id: str, document_id: str, question: str, answer: str, sources: list) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO chat_turns (session_id, document_id, question, answer, sources_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, document_id, question, answer, json.dumps(sources), _now()),
    )
    conn.commit()
    conn.close()


def get_chat_history(session_id: str, document_id: str, limit: int = 20) -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM chat_turns WHERE session_id = ? AND document_id = ?
           ORDER BY created_at ASC LIMIT ?""",
        (session_id, document_id, limit),
    ).fetchall()
    conn.close()
    turns = []
    for row in rows:
        t = dict(row)
        t["sources"] = json.loads(t["sources_json"]) if t["sources_json"] else []
        turns.append(t)
    return turns

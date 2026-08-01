"""
Personalized Study Assistant - Flask app.

See README.md for the full architecture. Quick map of what lives where:
  utils/db.py              - all persistence (documents, pages, quizzes,
                              attempts, flashcards, spaced-repetition state,
                              chat history)
  utils/file_reader.py     - PDF/DOCX -> page-tagged text
  utils/vector_store.py    - per-document FAISS index
  utils/chat_memory.py     - follow-up question rewriting
  utils/rag_chat.py        - RAG answer + page-numbered sources
  utils/quiz_generator.py  - mixed-type, difficulty-aware quiz generation
  utils/quiz_grader.py     - grades mcq/true_false/match/fill_blank/short_answer
  utils/flashcard_generator.py - structured flashcards
  utils/spaced_repetition.py   - SM-2-lite scheduling
  utils/study_plan.py      - adaptive, structured study plan
  utils/explain_styles.py  - ELI10 / interview / exam / technical reformatting
"""

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, flash, session, redirect, url_for,
    jsonify, Response, send_from_directory
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

from utils.file_reader import extract_pages, extract_text, is_allowed_file
from utils.vector_store import create_vector_store, load_vector_store, delete_vector_store
from utils.rag_chat import answer_question
from utils.chat_memory import rewrite_followup, format_history_for_prompt
from utils.quiz_generator import generate_quiz
from utils.quiz_grader import grade_quiz
from utils.flashcard_generator import generate_flashcards
from utils.spaced_repetition import schedule_next_review
from utils.summary_generator import generate_summary
from utils.study_plan import create_study_plan
from utils.explain_styles import explain
import utils.db as db

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

db.init_db()


# --------------------------------------------------------------------------
# Session helper
# --------------------------------------------------------------------------

def get_session_id() -> str:
    """Anonymous per-browser session id (signed cookie), used to track
    quiz history and progress without requiring an account."""
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


# --------------------------------------------------------------------------
# Document library + upload
# --------------------------------------------------------------------------

@app.route("/")
def home():
    session_id = get_session_id()
    documents = db.list_documents(session_id)
    return render_template("library.html", documents=documents)


def _resolve_difficulty(doc_id: str, session_id: str, requested: str) -> str:
    """Turn 'adaptive' into an actual easy/medium/hard level based on the
    student's average accuracy on this document so far."""
    if requested != "adaptive":
        return requested if requested in ("easy", "medium", "hard") else "medium"

    attempts = db.get_attempts(session_id, doc_id)
    if not attempts:
        return "medium"

    avg_pct = sum((a["score"] / a["total"]) * 100 for a in attempts if a["total"]) / len(attempts)
    if avg_pct < 50:
        return "easy"
    elif avg_pct < 75:
        return "medium"
    return "hard"


@app.route("/upload", methods=["POST"])
def upload():
    session_id = get_session_id()
    file = request.files.get("pdf")

    if not file or file.filename == "":
        flash("Please choose a PDF or DOCX file to upload.")
        return redirect(url_for("home"))

    if not is_allowed_file(file.filename):
        flash("Unsupported file type. Please upload a .pdf or .docx file.")
        return redirect(url_for("home"))

    filename = secure_filename(file.filename)
    doc_id = str(uuid.uuid4())
    stored_filename = f"{doc_id}_{filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)
    file.save(filepath)

    try:
        pages = extract_pages(filepath)
        full_text = "\n".join(p["text"] for p in pages if p["text"])

        if not full_text.strip():
            flash("Couldn't extract any text from that file (it may be scanned/image-only).")
            return redirect(url_for("home"))

        create_vector_store(doc_id, pages)
        summary = generate_summary(full_text)

        display_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()

        db.create_document(doc_id, session_id, stored_filename, display_name,
                            file_ext, len(pages), summary)
        db.save_pages(doc_id, pages)

        flash(f'"{display_name}" uploaded successfully.')
        return redirect(url_for("view_document", doc_id=doc_id))

    except Exception as exc:
        flash(f"Something went wrong while processing your file: {exc}")
        return redirect(url_for("home"))


@app.route("/documents/<doc_id>/delete", methods=["POST"])
def delete_document(doc_id):
    document = db.get_document(doc_id)
    if document and document["session_id"] == get_session_id():
        db.delete_document(doc_id)
        delete_vector_store(doc_id)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], document["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
        flash(f'"{document["display_name"]}" deleted.')
    return redirect(url_for("home"))


# --------------------------------------------------------------------------
# Document workspace (chat, summary, quiz/flashcard/study-plan launch points)
# --------------------------------------------------------------------------

@app.route("/document/<doc_id>")
def view_document(doc_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        flash("Document not found.")
        return redirect(url_for("home"))

    chat_history = db.get_chat_history(session_id, doc_id)
    attempts = db.get_attempts(session_id, doc_id)
    weak_topics = attempts[-1]["weak_topics"] if attempts else []
    study_plan = create_study_plan(document["display_name"], weak_topics)
    due_flashcards = db.get_due_flashcards(doc_id, session_id)
    total_flashcards = len(db.get_flashcards(doc_id))

    return render_template(
        "document.html",
        document=document,
        chat_history=chat_history,
        study_plan=study_plan,
        due_flashcard_count=len(due_flashcards),
        total_flashcard_count=total_flashcards,
        is_pdf=(document["file_ext"] == ".pdf"),
    )


@app.route("/document/<doc_id>/ask", methods=["POST"])
def ask_question(doc_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        flash("Document not found.")
        return redirect(url_for("home"))

    question = (request.form.get("question") or "").strip()
    if not question:
        flash("Please type a question.")
        return redirect(url_for("view_document", doc_id=doc_id))

    history = db.get_chat_history(session_id, doc_id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        standalone_question = executor.submit(rewrite_followup, history, question).result()

    db_store = load_vector_store(doc_id)
    docs_with_scores = db_store.similarity_search_with_score(standalone_question, k=8)
    history_text = format_history_for_prompt(history)
    answer, sources = answer_question(docs_with_scores, standalone_question, history_text)

    db.save_chat_turn(session_id, doc_id, question, answer, sources)

    return redirect(url_for("view_document", doc_id=doc_id) + "#chat-end")


# --------------------------------------------------------------------------
# Quiz
# --------------------------------------------------------------------------

@app.route("/document/<doc_id>/generate_quiz", methods=["POST"])
def generate_quiz_route(doc_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        flash("Document not found.")
        return redirect(url_for("home"))

    requested_difficulty = request.form.get("difficulty", "medium")
    difficulty = _resolve_difficulty(doc_id, session_id, requested_difficulty)

    questions = generate_quiz(document["summary"], difficulty=difficulty)
    if not questions:
        flash("Couldn't generate a quiz right now - please try again.")
        return redirect(url_for("view_document", doc_id=doc_id))

    quiz_id = str(uuid.uuid4())
    db.save_quiz(quiz_id, doc_id, difficulty, questions)
    return redirect(url_for("take_quiz", doc_id=doc_id, quiz_id=quiz_id))


@app.route("/document/<doc_id>/quiz/<quiz_id>")
def take_quiz(doc_id, quiz_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    quiz = db.get_quiz(quiz_id)
    if not document or not quiz or document["session_id"] != session_id:
        flash("Quiz not found.")
        return redirect(url_for("home"))

    return render_template("quiz.html", document=document, quiz=quiz)


@app.route("/quiz/<quiz_id>/submit", methods=["POST"])
def submit_quiz(quiz_id):
    session_id = get_session_id()
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        flash("Quiz not found.")
        return redirect(url_for("home"))

    document = db.get_document(quiz["document_id"])
    questions = quiz["questions"]

    answers = {f"q{i}": request.form.get(f"q{i}", "") for i in range(len(questions))}
    graded = grade_quiz(questions, answers)

    score = 0
    topic_breakdown = {}
    review = []

    for i, q in enumerate(questions):
        topic = q.get("topic", "General")
        result = graded[i]
        is_correct = result["is_correct"]

        topic_breakdown.setdefault(topic, {"correct": 0, "total": 0})
        topic_breakdown[topic]["total"] += 1
        if is_correct:
            topic_breakdown[topic]["correct"] += 1
            score += 1

        review.append({
            "type": q.get("type"),
            "question": q.get("question"),
            "options": q.get("options", {}),
            "pairs": q.get("pairs", []),
            "correct": q.get("correct_answer"),
            "answer_text": q.get("answer_text"),
            "student_answer": result["student_answer"],
            "is_correct": is_correct,
            "topic": topic,
        })

    total = len(questions)
    accuracy = round((score / total) * 100) if total else 0
    wrong = total - score

    weak_topics = [
        topic for topic, stats in topic_breakdown.items()
        if stats["total"] > 0 and (stats["correct"] / stats["total"]) < 0.6
    ]
    weakest_topic = None
    if topic_breakdown:
        weakest_topic = min(
            topic_breakdown.items(), key=lambda item: item[1]["correct"] / item[1]["total"]
        )[0]

    duration_seconds = None
    start_time_ms = request.form.get("start_time")
    if start_time_ms:
        try:
            duration_seconds = max(0, int((time.time() * 1000 - float(start_time_ms)) / 1000))
        except ValueError:
            duration_seconds = None

    db.save_attempt(session_id, quiz["document_id"], document["display_name"], quiz_id,
                     quiz["difficulty"], score, total, duration_seconds, topic_breakdown, weak_topics)

    adaptive_plan = create_study_plan(document["display_name"], weak_topics)
    adaptive_flashcards = None
    if weak_topics:
        cards = generate_flashcards(document["summary"], focus_topics=weak_topics)
        if cards:
            for c in cards:
                c["id"] = str(uuid.uuid4())
            db.save_flashcards(quiz["document_id"], cards)
            adaptive_flashcards = cards

    return render_template(
        "results.html",
        document=document,
        score=score, total=total, accuracy=accuracy, wrong=wrong,
        difficulty=quiz["difficulty"], duration_seconds=duration_seconds,
        weakest_topic=weakest_topic, review=review, weak_topics=weak_topics,
        adaptive_plan=adaptive_plan, adaptive_flashcards=adaptive_flashcards,
    )


# --------------------------------------------------------------------------
# Flashcards (spaced repetition)
# --------------------------------------------------------------------------

@app.route("/document/<doc_id>/generate_flashcards", methods=["POST"])
def generate_flashcards_route(doc_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        flash("Document not found.")
        return redirect(url_for("home"))

    cards = generate_flashcards(document["summary"])
    if not cards:
        flash("Couldn't generate flashcards right now - the AI response wasn't in the "
              "expected format. Please try again.")
        return redirect(url_for("view_document", doc_id=doc_id))

    for c in cards:
        c["id"] = str(uuid.uuid4())
    db.save_flashcards(doc_id, cards)
    flash(f"{len(cards)} flashcards generated successfully.")

    return redirect(url_for("review_flashcards", doc_id=doc_id))


@app.route("/document/<doc_id>/flashcards")
def review_flashcards(doc_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        flash("Document not found.")
        return redirect(url_for("home"))

    due_cards = db.get_due_flashcards(doc_id, session_id)
    return render_template("flashcards.html", document=document, due_cards=due_cards)


@app.route("/flashcards/<card_id>/review", methods=["POST"])
def review_flashcard(card_id):
    session_id = get_session_id()
    doc_id = request.form.get("doc_id")
    rating = request.form.get("rating", "good")

    state = db.get_or_init_review_state(card_id, session_id)
    ease, interval, reps, next_date = schedule_next_review(
        rating, state["ease_factor"], state["interval_days"], state["repetitions"]
    )
    db.save_review_state(card_id, session_id, ease, interval, reps, next_date, rating)

    return redirect(url_for("review_flashcards", doc_id=doc_id))


# --------------------------------------------------------------------------
# Progress dashboard
# --------------------------------------------------------------------------

def _compute_progress_stats(attempts: list) -> dict:
    if not attempts:
        return {}

    percentages = [round((a["score"] / a["total"]) * 100) if a["total"] else 0 for a in attempts]

    streak = 0
    for pct in reversed(percentages):
        if pct >= 70:
            streak += 1
        else:
            break

    return {
        "average_score": round(sum(percentages) / len(percentages)),
        "best_score": max(percentages),
        "current_streak": streak,
        "documents_studied": len({a["document_id"] for a in attempts}),
        "improvement": percentages[-1] - percentages[0],
    }


def _mastery_label(pct: int) -> dict:
    """Turn a raw percentage into an at-a-glance qualitative label, since a
    bare number takes an extra beat to interpret compared to a color + word."""
    if pct >= 80:
        return {"emoji": "🟢", "label": "Strong"}
    elif pct >= 50:
        return {"emoji": "🟡", "label": "Improving"}
    else:
        return {"emoji": "🔴", "label": "Needs Revision"}


def _compute_topic_mastery(attempts: list) -> list:
    """Aggregate correct/total per topic across every attempt, for a mastery bar chart."""
    totals = {}
    for a in attempts:
        for topic, stats in a["topic_breakdown"].items():
            totals.setdefault(topic, {"correct": 0, "total": 0})
            totals[topic]["correct"] += stats["correct"]
            totals[topic]["total"] += stats["total"]

    mastery = []
    for topic, stats in totals.items():
        pct = round(100 * stats["correct"] / stats["total"]) if stats["total"] else 0
        mastery.append({"topic": topic, "pct": pct, **_mastery_label(pct)})
    return sorted(mastery, key=lambda m: m["pct"], reverse=True)


def _compute_weekly_performance(attempts: list) -> list:
    """Average accuracy per day for the last 7 calendar days."""
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    by_day = {d.isoformat(): [] for d in days}

    for a in attempts:
        day = a["created_at"][:10]
        if day in by_day and a["total"]:
            by_day[day].append(round((a["score"] / a["total"]) * 100))

    return [
        {"label": d.strftime("%a"), "date": d.isoformat(),
         "avg": round(sum(scores) / len(scores)) if scores else None}
        for d, scores in zip(days, by_day.values())
    ]


def _compute_study_time(attempts: list) -> dict:
    """Sums of duration_seconds (only attempts that recorded a duration)."""
    today = datetime.now(timezone.utc).date().isoformat()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    today_secs = sum(a["duration_seconds"] or 0 for a in attempts if a["created_at"][:10] == today)
    week_secs = sum(a["duration_seconds"] or 0 for a in attempts if a["created_at"] >= week_ago)
    total_secs = sum(a["duration_seconds"] or 0 for a in attempts)

    def fmt(seconds):
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min"
        hours = minutes // 60
        return f"{hours} hr {minutes % 60} min"

    return {"today": fmt(today_secs), "week": fmt(week_secs), "total": fmt(total_secs)}


def _compute_achievements(attempts: list, documents: list) -> list:
    percentages = [round((a["score"] / a["total"]) * 100) if a["total"] else 0 for a in attempts]
    streak = 0
    for pct in reversed(percentages):
        if pct >= 70:
            streak += 1
        else:
            break

    badges = [
        {"name": "First Quiz", "icon": "🎯", "unlocked": len(attempts) >= 1},
        {"name": "5-Day Streak", "icon": "🔥", "unlocked": streak >= 5},
        {"name": "90%+ Score", "icon": "🏆", "unlocked": any(p >= 90 for p in percentages)},
        {"name": "Perfect Score", "icon": "💯", "unlocked": any(p == 100 for p in percentages)},
        {"name": "3+ Documents Studied", "icon": "📚", "unlocked": len(documents) >= 3},
    ]
    return badges


@app.route("/progress")
def progress():
    session_id = get_session_id()
    attempts = db.get_attempts(session_id)
    documents = db.list_documents(session_id)

    stats = _compute_progress_stats(attempts)
    topic_mastery = _compute_topic_mastery(attempts)
    weekly_performance = _compute_weekly_performance(attempts)
    has_weekly_data = any(d["avg"] is not None for d in weekly_performance)
    study_time = _compute_study_time(attempts)
    achievements = _compute_achievements(attempts, documents)

    # Strongest/weakest topic overall, for the richer history table
    strongest_topic = topic_mastery[0]["topic"] if topic_mastery else None
    weakest_topic_overall = topic_mastery[-1]["topic"] if topic_mastery else None
    questions_attempted = sum(a["total"] for a in attempts)

    return render_template(
        "progress.html",
        attempts=attempts,
        attempts_json=json.dumps(attempts),
        stats=stats,
        topic_mastery=topic_mastery,
        weekly_performance=weekly_performance,
        weekly_performance_json=json.dumps(weekly_performance),
        has_weekly_data=has_weekly_data,
        study_time=study_time,
        achievements=achievements,
        strongest_topic=strongest_topic,
        weakest_topic_overall=weakest_topic_overall,
        questions_attempted=questions_attempted,
        documents_count=len(documents),
    )


# --------------------------------------------------------------------------
# Search inside a document (AJAX)
# --------------------------------------------------------------------------

@app.route("/document/<doc_id>/search")
def search_document(doc_id):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        return jsonify({"error": "not found"}), 404

    query = request.args.get("q", "")
    results = db.search_pages(doc_id, query)
    return jsonify({"results": results})


# --------------------------------------------------------------------------
# AI explanation styles (AJAX)
# --------------------------------------------------------------------------

@app.route("/explain", methods=["POST"])
def explain_route():
    data = request.get_json(force=True, silent=True) or {}
    question = data.get("question", "")
    answer_text = data.get("answer", "")
    style = data.get("style", "technical")

    if not answer_text:
        return jsonify({"error": "no answer provided"}), 400

    reformatted = explain(answer_text, question, style)
    return jsonify({"text": reformatted})


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

@app.route("/export/<doc_id>/<kind>")
def export_document(doc_id, kind):
    session_id = get_session_id()
    document = db.get_document(doc_id)
    if not document or document["session_id"] != session_id:
        flash("Document not found.")
        return redirect(url_for("home"))

    name = document["display_name"]

    if kind == "summary":
        content = f"# Summary: {name}\n\n{document['summary']}"
    elif kind == "flashcards":
        cards = db.get_flashcards(doc_id)
        content = f"# Flashcards: {name}\n\n" + "\n\n".join(
            f"**Q:** {c['question']}\n**A:** {c['answer']}" for c in cards
        )
    elif kind == "study_plan":
        attempts = db.get_attempts(session_id, doc_id)
        weak_topics = attempts[-1]["weak_topics"] if attempts else []
        plan = create_study_plan(name, weak_topics)
        lines = [f"# {plan['title']}", f"Priority: {'*' * plan['priority']}", ""]
        for d in plan["days"]:
            lines.append(f"## Day {d['day']}: {d['title']}")
            lines.extend(f"- {t}" for t in d["tasks"])
            lines.append("")
        content = "\n".join(lines)
    elif kind == "notes":
        content = f"# Notes: {name}\n\n## Summary\n{document['summary']}"
    elif kind == "quiz":
        quiz = db.get_latest_quiz(doc_id)
        if not quiz:
            flash("No quiz has been generated for this document yet.")
            return redirect(url_for("view_document", doc_id=doc_id))
        lines = [f"# Quiz: {name} (difficulty: {quiz['difficulty']})", ""]
        for i, q in enumerate(quiz["questions"]):
            lines.append(f"**{i + 1}. [{q.get('topic', 'General')}] {q['question']}**")
            if q.get("options"):
                for letter, text in q["options"].items():
                    lines.append(f"- {letter}. {text}")
                lines.append(f"*Correct answer: {q.get('correct_answer')}*")
            elif q.get("answer_text"):
                lines.append(f"*Expected answer: {q['answer_text']}*")
            lines.append("")
        content = "\n".join(lines)
    else:
        flash("Unknown export type.")
        return redirect(url_for("view_document", doc_id=doc_id))

    filename = f"{name}_{kind}.md"
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------
# Serving uploaded files (for the embedded PDF viewer / "open at page N")
# --------------------------------------------------------------------------

@app.route("/files/<path:filename>")
def serve_file(filename):
    # send_from_directory already guards against path traversal outside
    # UPLOAD_FOLDER, but we double check the file actually belongs to a
    # document this session owns before serving it.
    session_id = get_session_id()
    documents = db.list_documents(session_id)
    if not any(d["filename"] == filename for d in documents):
        return "Not found", 404
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/healthz")
def healthz():
    """Simple health check endpoint for hosting platforms (Render/Railway/etc.)."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)

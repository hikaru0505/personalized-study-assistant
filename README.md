# Personalized Study Assistant

A RAG-based study tool that goes well beyond "chat with your PDF": a real
document library, spaced-repetition flashcards, adaptive multi-type quizzes,
follow-up-aware chat, and a progress dashboard with topic mastery, streaks,
and achievements - built with Flask, LangChain, FAISS, HuggingFace sentence
embeddings, and Groq's Llama 3.3 70B.

## Features

**Documents**
- Upload multiple PDFs/DOCX files, each gets its own FAISS index (per-document
  library, not a single shared/overwritten index)
- Page-numbered source citations with a relevance % per source
- Keyword search inside a document, with click-to-jump-to-page
- Split-screen view: the PDF on one side, chat/summary/quiz on the other
  (uses the browser's native PDF renderer via an iframe + `#page=N`
  fragment - simple and robust, no custom PDF.js integration needed)

**Chat**
- Follow-up questions are resolved against prior turns before retrieval -
  e.g. asking "Explain LangChain" then "Give an example" correctly
  retrieves an example *of LangChain*, not a generic example
- One-click answer reformatting: Explain Like I'm 10 / Interview / Exam
  Answer / Technical
- Ask by voice, and have answers read aloud (Web Speech API, no API key needed)

**Quizzes**
- Five question types per quiz: MCQ, true/false, fill-in-the-blank, short
  answer, and match-the-following
- Three difficulty levels, plus an "Adaptive" mode that sets difficulty
  based on your average score on that document so far
- Free-text answers (fill-blank/short-answer) are graded by a batched LLM
  call rather than brittle exact-string matching
- Full quiz analytics: accuracy, correct/wrong counts, weakest topic, time taken

**Flashcards**
- Real spaced repetition (a simplified SM-2, the algorithm Anki is based
  on): rate each card Again/Hard/Good/Easy and it's rescheduled accordingly
- After a quiz, new flashcards are generated focused specifically on
  whatever topics you scored under 60% on

**Progress dashboard**
- Topic mastery bars (aggregated across every attempt)
- Weekly performance line chart (last 7 days)
- Study time tracking: today / this week / total (measured from actual
  quiz-taking time, not idle browser time)
- Achievements/gamification badges
- Full attempt history with accuracy, difficulty, time, strongest/weakest topic

**Other**
- Dark mode (persisted per-browser)
- Export summary / flashcards / quiz / study plan as markdown downloads

## Architecture

```
Upload PDF/DOCX
   |
   v
file_reader.py --> pdf_reader.py / docx_reader.py   (page-tagged text)
   |
   v
vector_store.py --> per-document FAISS index (faiss_index/<doc_id>/)
   |
   v
db.py stores: documents, pages, quizzes, quiz_attempts,
              flashcards, flashcard_reviews, chat_turns
   |
   v
Chat:  chat_memory.py rewrites follow-ups --> rag_chat.py (Groq answer + page-cited sources)
Quiz:  quiz_generator.py (mixed types + difficulty) --> quiz_grader.py (mcq/tf/match
       exact match; fill-blank/short-answer batched LLM grading)
Cards: flashcard_generator.py --> spaced_repetition.py (SM-2-lite scheduling)
Plan:  study_plan.py (adaptive, structured day-by-day data)
   |
   v
/progress aggregates every attempt: topic mastery, weekly trend, streaks,
achievements, study time
```

## Project structure

```
study_assistant/
├── app.py                       # all Flask routes
├── requirements.txt / Procfile / render.yaml
├── .env.example
├── utils/
│   ├── llm_config.py             # single shared Groq client
│   ├── file_reader.py / pdf_reader.py / docx_reader.py   # page-tagged extraction
│   ├── vector_store.py           # per-document FAISS index + page metadata
│   ├── chat_memory.py            # follow-up question rewriting
│   ├── rag_chat.py               # RAG answer + page-cited, scored sources
│   ├── quiz_generator.py         # mixed-type, difficulty-aware quiz generation
│   ├── quiz_grader.py            # grading for all 5 question types
│   ├── flashcard_generator.py    # structured flashcards (JSON)
│   ├── spaced_repetition.py      # SM-2-lite scheduler
│   ├── study_plan.py             # adaptive, structured study plan
│   ├── explain_styles.py         # ELI10/interview/exam/technical reformatting
│   ├── summary_generator.py
│   └── db.py                     # all SQLite persistence
├── templates/                    # base.html + library/document/quiz/results/
│                                  # flashcards/progress
├── static/style.css, script.js   # dark mode, voice, AJAX search/explain,
│                                  # spaced-repetition UI, study-plan checkboxes
├── uploads/, faiss_index/        # gitignored, regenerated at runtime
└── study_assistant.db            # gitignored SQLite file
```

## Setup

```bash
git clone <this-repo-url>
cd study_assistant

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env
# then edit .env and add your real GROQ_API_KEY (https://console.groq.com/keys)

python app.py
```

Open http://127.0.0.1:5000 in your browser.

### Troubleshooting

- **`ModuleNotFoundError: No module named 'tf_keras'`** - some machines have
  both TensorFlow and PyTorch installed, and `transformers` tries to load a
  TensorFlow/Keras 3 integration this project doesn't need.
  Fix: `pip install tf-keras`, or `pip uninstall tensorflow tensorflow-intel`
  (everything here runs on the PyTorch backend).
- **`GROQ_API_KEY is not set`** - make sure `.env` (not `.env.example`) exists
  in the project root, and isn't accidentally saved as `.env.txt`.

## Deploying live

See [DEPLOYMENT.md](DEPLOYMENT.md) - a `Procfile` and `render.yaml` are
included for a free-tier Render deployment. Note that SQLite/FAISS storage
on most free hosting tiers is ephemeral (resets on redeploy) unless you
attach persistent storage - this tradeoff is explained in that file, and is
worth mentioning if it comes up in an interview.

## Retrieval tuning notes

Early versions of this project sometimes answered "I don't know" even when
a document clearly contained the answer. Root cause: default retrieval only
pulled the top 4 chunks by raw vector distance, and a 1000-character chunk
size occasionally diluted a short factual sentence inside a large,
topically-mixed chunk. Fixes applied:

- Retrieval widened to k=8 with `similarity_search_with_score`
- Chunk size reduced to 600 with proportionally more overlap (150)
- Each retrieved chunk's relevance is shown in the UI (normalized 0-100%
  within that result set - labelled "relevance", not a calibrated
  probability, since FAISS distances aren't true confidence scores)

## Known limitations / honest scope notes

- **No user accounts** - progress is tracked per anonymous browser session
  (a signed cookie), not a login. History won't follow you across devices
  or browsers. Adding real accounts (e.g. Flask-Login + a users table)
  would be a natural next step if that's ever needed.
- **SQLite + local FAISS folders** - great for a single-instance deployment
  or demo; a multi-instance production deployment would need Postgres +
  object storage instead (see DEPLOYMENT.md).
- **DOCX files have no real page numbers** - python-docx doesn't expose
  page boundaries the way PDFs do, so DOCX documents are treated as a
  single page for citation purposes. This is called out in the UI.
- **"Match the following" grading** requires the student to pick from a
  dropdown for each left-hand item rather than a drag-and-drop interface -
  a UX simplification, not a grading simplification (grading is exact).
- **Keyword search inside documents** is simple case-insensitive substring
  matching, not a full-text search engine - intentionally simple, and
  distinct from the semantic FAISS search used for RAG (worth explaining
  the difference between the two in a viva).

## License

MIT - see [LICENSE](LICENSE).

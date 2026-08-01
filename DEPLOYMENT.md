# Deploying live

This app is a standard Flask app with a `Procfile` and `render.yaml`, so it
deploys cleanly to any platform that supports Python + gunicorn (Render,
Railway, Fly.io, Heroku-compatible hosts). Steps below are for Render's
free tier since it needs no credit card for a small hobby deployment.

## 1. Push to GitHub
Make sure `.env` is **not** committed (check `.gitignore`), then push this
repo to a GitHub repository.

## 2. Deploy on Render
1. Go to https://dashboard.render.com -> "New +" -> "Blueprint"
2. Connect your GitHub repo - Render will detect `render.yaml` automatically
3. When prompted, paste in your `GROQ_API_KEY`
4. Click "Apply" - Render builds and deploys automatically

## 3. Important: SQLite + FAISS storage on a free-tier host
This project uses local SQLite (`study_assistant.db`) and local FAISS index
folders (`faiss_index/<doc_id>/`) for storage. On most free hosting tiers,
the filesystem is **ephemeral** - it resets on every redeploy/restart. That's
fine for a demo/portfolio deployment, but if you want data to actually
persist long-term in production, you have two realistic options:
  - Attach a persistent disk (Render's paid "Disk" add-on, or Railway
    volumes), and point `DB_PATH` / `FAISS_ROOT` at that mounted directory
  - Migrate to a managed database (e.g. Postgres via `psycopg2` +
    SQLAlchemy) and object storage (e.g. S3) for uploaded files/index data -
    a bigger change, but the "correct" production answer

For a placement/portfolio demo, the ephemeral free-tier setup is genuinely
fine - just mention this tradeoff if asked about production-readiness in
an interview, since it shows you understand the difference between a demo
deployment and a production one.

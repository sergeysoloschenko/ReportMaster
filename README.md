# ReportMaster WebApp

ReportMaster processes Outlook `.msg` emails, groups threads, generates AI-based category summaries, and builds a Word monthly report with attachments.

## Project Summary

ReportMaster is an internal reporting system that:
- accepts Outlook email exports (`.msg`)
- groups messages into discussion threads
- classifies/summarizes content with LLM APIs
- generates structured monthly reports for business use

## GitHub Workflow (Required)

- Canonical repository: `https://github.com/sergeysoloschenko/ReportMaster`
- All next changes must be committed in this git repo and pushed to GitHub (`main` or feature branch + PR).
- Do not deploy from ad-hoc local/server changes that are not in GitHub.
- Do not commit local virtual environments (`venv`, `.venv`) or other machine-specific artifacts.

## Deploy Policy

- Deploy only from GitHub repository state.
- On server, update code from GitHub first (`git pull`) and then run deployment commands (`docker compose up -d --build`).

## Architecture

- Backend: `FastAPI` (`src/webapp/backend/app.py`)
- Frontend: `React + Vite` (`webapp/frontend`)
- Processing pipeline: existing Python core in `src/parsers`, `src/analyzers`, `src/generators`
- Deployment: Docker Compose (`docker-compose.yml`)

## Local Development

### One-command localhost start (recommended)

```bash
make dev
```

This starts both:
- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

To stop both:

```bash
make dev-down
```

### 1) Python backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn src.webapp.backend.app:app --reload --host 0.0.0.0 --port 8000
```

### 2) React frontend

```bash
cd webapp/frontend
npm install
npm run dev
```

Frontend: `http://localhost:5173`  
Backend API: `http://localhost:8000`

## Production on Private Server (Docker)

1. Create env file:

```bash
cp .env.example .env
```

2. Set real `ANTHROPIC_API_KEY` in `.env`
3. Run:

```bash
docker compose up -d --build
```

4. Open:
- Web UI: `http://<server-ip>:8080`
- API health: `http://<server-ip>:8000/api/health`

## Limits and Operational Profile

- Recommended workload: up to `5` concurrent users
- Up to `50` `.msg` files per job

## Security/Quality Improvements Implemented

- Attachment filename sanitization and path traversal prevention
- Category deduplication (threads with same AI category are merged)
- Thread splitting improved by participant overlap + time gap
- Config loading no longer overwrites YAML sections blindly
- Added real pytest tests for core logic (`tests/test_core_logic.py`)

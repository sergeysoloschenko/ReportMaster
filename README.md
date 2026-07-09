# ReportMaster WebApp

ReportMaster processes Outlook `.msg` emails and supporting documents, deduplicates repeated content, groups threads, generates Codex-based summaries, and builds Word reports.

## Project Summary

ReportMaster is an internal reporting system that:
- accepts Outlook email exports (`.msg`) and standalone documents (`.pdf`, `.docx`, `.xlsx`, `.txt`, `.csv`, `.md`)
- extracts text from readable attachments when email body context is limited
- deduplicates repeated uploads, repeated messages, and repeated attachments before LLM analysis
- groups messages into discussion threads
- classifies default monthly email reports into fixed business directions
- supports custom prompt-based analysis for mixed source files
- runs analysis through a private Codex CLI worker
- generates structured monthly reports for business use

## Processing Modes

### Monthly `.msg` report

Default mode for monthly reporting. Upload Outlook `.msg` files for the reporting month. ReportMaster parses email chains, extracts relevant attachment text, removes duplicate content, and generates a report by fixed directions:

1. Договор с гостиничным оператором
2. Техническое сопровождение проектирования
3. Работа с консультантами проекта
4. Работа с архитектором проекта
5. Взаимодействие с Заказчиком/Инвестором
6. Прочее существенное

### Custom analysis

Prompt-based mode for arbitrary source files. Upload supported files (`.msg`, `.pdf`, `.docx`, `.xlsx`, `.txt`, `.csv`, `.md`) and enter a custom analysis/report prompt. ReportMaster extracts and deduplicates readable content, then applies the prompt to the prepared context.

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

2. Set private access and Codex worker settings in `.env`:

```bash
APP_PASSWORD=<strong-private-password>
APP_ALLOWED_ORIGINS=http://<server-ip>:8080
APP_COOKIE_SECURE=false

LLM_PROVIDER=codex
CODEX_COMMAND=codex
CODEX_MODEL_TRIAGE=
CODEX_MODEL_THREAD_INSIGHT=
CODEX_SANDBOX_MODE=read-only
CODEX_REASONING_TRIAGE=low
CODEX_REASONING_THREAD_INSIGHT=medium
CODEX_REASONING_SUMMARIZATION=high
CODEX_REASONING_CUSTOM_ANALYSIS=high
CODEX_TIMEOUT_SECONDS=1200
CODEX_MAX_PROMPT_CHARS=90000
CODEX_WORKDIR=/app
JOB_MAX_WORKERS=1
```

3. Build and start containers:

```bash
docker compose up -d --build
```

4. Sign in Codex inside the backend container once:

```bash
docker compose exec backend codex login --device-auth
```

Follow the printed browser URL and enter the device code with your ChatGPT Pro account. The login cache is stored in the mounted `./.codex` folder and survives container rebuilds. Treat this folder like a secret.

5. Open:
- Web UI: `http://<server-ip>:8080`
- API health: `http://<server-ip>:8000/api/health`

The web UI asks for `APP_PASSWORD` before uploads, job status, reports, or attachments are accessible. Without a domain, keep `APP_COOKIE_SECURE=false`; switch it to `true` only after HTTPS is configured.

## Limits and Operational Profile

- Recommended workload: one private user and one active Codex job by default
- No hard file-count limit in the API; processing is bounded by server disk, memory, and request upload size
- Document text extraction is capped by `MAX_DOCUMENT_CHARS` per file before LLM analysis
- Custom analysis is capped by `MAX_CUSTOM_SOURCES` and `MAX_CUSTOM_SOURCE_CHARS` before LLM analysis
- Monthly reports use staged Codex reasoning: low for relevance triage, medium for thread cards, high for direction summaries
- LLM analysis results are cached in `CACHE_FOLDER` by content hash to avoid repeated Codex runs
- Codex jobs run sequentially by default (`JOB_MAX_WORKERS=1`) to avoid competing with one user's ChatGPT/Codex limits

## Security/Quality Improvements Implemented

- v1.1.0: Two modes: fixed monthly `.msg` report and custom prompt-based analysis
- v1.1.0: Fixed monthly directions for Dusit, Dyer, consultants, client/investor, and other workstreams
- v1.1.0: Upload-level, message-level, attachment-level, and LLM-cache deduplication
- v1.1.0: Text extraction from standalone documents and supported email attachments
- Attachment filename sanitization and path traversal prevention
- Category deduplication (threads with same AI category are merged)
- Thread splitting improved by participant overlap + time gap
- Config loading no longer overwrites YAML sections blindly
- Added real pytest tests for core logic (`tests/test_core_logic.py`)

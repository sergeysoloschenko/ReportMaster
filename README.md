# ReportMaster WebApp

ReportMaster processes Outlook `.msg` emails and supporting documents, deduplicates repeated content, groups threads, generates AI-based summaries, and builds Word reports.

## Project Summary

ReportMaster is an internal reporting system that:
- accepts Outlook email exports (`.msg`) and standalone documents (`.pdf`, `.docx`, `.xlsx`, `.txt`, `.csv`, `.md`)
- extracts text from readable attachments when email body context is limited
- deduplicates repeated uploads, repeated messages, and repeated attachments before LLM analysis
- groups messages into discussion threads
- classifies default monthly email reports into fixed business directions
- supports custom prompt-based analysis for mixed source files
- generates structured monthly reports for business use

## Processing Modes

### Monthly `.msg` report

Default mode for monthly reporting. Upload Outlook `.msg` files for the reporting month. ReportMaster parses email chains, extracts relevant attachment text, removes duplicate content, and generates a report by fixed directions:

1. Договор управления с гостиничным оператором Dusit
2. Техническое сопровождение проектирования Dusit
3. Работа с консультантами проекта
4. Взаимодействие с Dyer
5. Взаимодействие с Заказчиком/Инвестором
6. Прочее

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

2. Set GigaChat credentials in `.env`:

```bash
GIGACHAT_AUTH_KEY=<base64(client_id:client_secret)>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_VERIFY_SSL=true
GIGACHAT_MODEL_CATEGORIZATION=GigaChat-2
GIGACHAT_MODEL_SUMMARIZATION=GigaChat-2-Max
```

Access token is requested automatically via OAuth (`/api/v2/oauth`) and refreshed by the backend.
3. Run:

```bash
docker compose up -d --build
```

4. Open:
- Web UI: `http://<server-ip>:8080`
- API health: `http://<server-ip>:8000/api/health`

## Limits and Operational Profile

- Recommended workload: up to `5` concurrent users
- No hard file-count limit in the API; processing is bounded by server disk, memory, and request upload size
- Document text extraction is capped by `MAX_DOCUMENT_CHARS` per file before LLM analysis
- Custom analysis is capped by `MAX_CUSTOM_SOURCES` and `MAX_CUSTOM_SOURCE_CHARS` before LLM analysis
- LLM analysis results are cached in `CACHE_FOLDER` by content hash to avoid repeated token spend

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

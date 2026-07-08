import logging
import os
import secrets
import shutil
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.processors.document_extractor import SUPPORTED_DOCUMENT_EXTENSIONS
from src.webapp.backend.job_manager import JobManager


logger = logging.getLogger(__name__)
app = FastAPI(title="ReportMaster API", version="1.1.0")
job_manager = JobManager()
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
SESSION_COOKIE = "reportmaster_session"
SESSION_TOKENS = set()
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("APP_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
SUPPORTED_UPLOAD_EXTENSIONS = {".msg", *SUPPORTED_DOCUMENT_EXTENSIONS}
MONTHLY_MODE = "monthly_msg_report"
CUSTOM_MODE = "custom_analysis"
SUPPORTED_MODES = {MONTHLY_MODE, CUSTOM_MODE}
UPLOAD_CHUNK_SIZE = 1024 * 1024

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    password: str


def require_auth(session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE)):
    if not APP_PASSWORD:
        return True
    if session and session in SESSION_TOKENS:
        return True
    raise HTTPException(status_code=401, detail="Authentication required")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/status")
def auth_status(session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE)):
    enabled = bool(APP_PASSWORD)
    return {
        "auth_enabled": enabled,
        "authenticated": not enabled or bool(session and session in SESSION_TOKENS),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    if not APP_PASSWORD:
        return {"authenticated": True}
    if not secrets.compare_digest(payload.password, APP_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = secrets.token_urlsafe(32)
    SESSION_TOKENS.add(token)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("APP_COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"},
        max_age=60 * 60 * 24 * 14,
    )
    return {"authenticated": True}


@app.post("/api/auth/logout")
def logout(response: Response, session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE)):
    if session:
        SESSION_TOKENS.discard(session)
    response.delete_cookie(key=SESSION_COOKIE)
    return {"authenticated": False}


@app.post("/api/jobs")
async def create_job(
    files: List[UploadFile] = File(...),
    report_month: Optional[str] = Form(default=None),
    mode: str = Form(default=MONTHLY_MODE),
    user_prompt: Optional[str] = Form(default=None),
    _: bool = Depends(require_auth),
):
    if mode not in SUPPORTED_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported mode: {mode}")

    allowed_extensions = {".msg"} if mode == MONTHLY_MODE else SUPPORTED_UPLOAD_EXTENSIONS
    supported_files = [
        f for f in files
        if f.filename and Path(f.filename).suffix.lower() in allowed_extensions
    ]
    if not supported_files:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=400, detail=f"Upload at least one supported file: {allowed}")

    if mode == CUSTOM_MODE and not (user_prompt or "").strip():
        raise HTTPException(status_code=400, detail="Custom analysis prompt is required")

    staging_dir = Path(job_manager.config["paths"]["temp"]) / "uploads" / uuid4().hex
    staging_dir.mkdir(parents=True, exist_ok=True)
    upload_paths = []
    names = []

    try:
        for index, file in enumerate(supported_files):
            original_name = Path(file.filename).name
            staged_path = staging_dir / f"{index:05d}_{original_name}"
            with staged_path.open("wb") as handle:
                while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                    handle.write(chunk)
            upload_paths.append(staged_path)
            names.append(original_name)

        job = job_manager.create_job_from_paths(
            upload_paths,
            names,
            report_month=report_month,
            mode=mode,
            user_prompt=user_prompt,
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return {"job_id": job.job_id, "status": job.status}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, _: bool = Depends(require_auth)):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "mode": job.mode,
        "status": job.status,
        "progress": job.progress,
        "step": job.step,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "stats": job.stats,
    }


@app.get("/api/jobs/{job_id}/report")
def download_report(job_id: str, _: bool = Depends(require_auth)):
    report_path = job_manager.get_report_path(job_id)
    if not report_path or not report_path.exists():
        raise HTTPException(status_code=404, detail="Report is not ready")
    return FileResponse(path=report_path, filename=report_path.name)


@app.get("/api/jobs/{job_id}/attachments.zip")
def download_attachments(job_id: str, _: bool = Depends(require_auth)):
    payload = job_manager.build_attachments_zip(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Attachments are not ready")
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="attachments_{job_id}.zip"'},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception):
    logger.exception("Unhandled API error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

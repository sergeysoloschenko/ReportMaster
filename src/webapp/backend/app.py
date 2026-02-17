import logging
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from src.webapp.backend.job_manager import JobManager


logger = logging.getLogger(__name__)
app = FastAPI(title="ReportMaster API", version="1.0.0")
job_manager = JobManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(
    files: List[UploadFile] = File(...),
    report_month: Optional[str] = Form(default=None),
):
    msg_files = [f for f in files if f.filename and f.filename.lower().endswith(".msg")]
    if not msg_files:
        raise HTTPException(status_code=400, detail="Upload at least one .msg file")
    if len(msg_files) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 files per run")

    payloads = []
    names = []
    for file in msg_files:
        payloads.append(await file.read())
        names.append(Path(file.filename).name)

    job = job_manager.create_job(payloads, names, report_month=report_month)
    return {"job_id": job.job_id, "status": job.status}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "step": job.step,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "stats": job.stats,
    }


@app.get("/api/jobs/{job_id}/report")
def download_report(job_id: str):
    report_path = job_manager.get_report_path(job_id)
    if not report_path or not report_path.exists():
        raise HTTPException(status_code=404, detail="Report is not ready")
    return FileResponse(path=report_path, filename=report_path.name)


@app.get("/api/jobs/{job_id}/attachments.zip")
def download_attachments(job_id: str):
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

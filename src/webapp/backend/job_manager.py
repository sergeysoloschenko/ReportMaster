import io
import logging
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from src.analyzers.categorizer import Categorizer
from src.analyzers.summarizer import Summarizer
from src.generators.attachment_manager import AttachmentManager
from src.generators.word_generator import WordReportGenerator
from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.utils.api_client import ClaudeAPIClient
from src.utils.config_loader import load_config


@dataclass
class JobState:
    job_id: str
    status: str = "queued"
    progress: int = 0
    step: str = "queued"
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None
    report_path: Optional[str] = None
    attachments_path: Optional[str] = None
    stats: Dict = field(default_factory=dict)


class JobManager:
    """
    In-memory job manager for small private deployment.
    Suitable for <=5 concurrent users and short-running tasks.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config = load_config()
        self.jobs: Dict[str, JobState] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=5)

    def create_job(self, files: List[bytes], filenames: List[str], report_month: Optional[str] = None) -> JobState:
        job_id = uuid4().hex
        job = JobState(job_id=job_id)
        with self.lock:
            self.jobs[job_id] = job

        input_dir = Path(self.config["paths"]["temp"]) / "jobs" / job_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        for data, filename in zip(files, filenames):
            safe_name = Path(filename).name
            if not safe_name.lower().endswith(".msg"):
                continue
            (input_dir / safe_name).write_bytes(data)

        self.executor.submit(self._run_job, job_id, report_month)
        return job

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self.lock:
            return self.jobs.get(job_id)

    def get_report_path(self, job_id: str) -> Optional[Path]:
        job = self.get_job(job_id)
        if not job or not job.report_path:
            return None
        return Path(job.report_path)

    def build_attachments_zip(self, job_id: str) -> Optional[bytes]:
        job = self.get_job(job_id)
        if not job or not job.attachments_path:
            return None

        attachments_dir = Path(job.attachments_path)
        if not attachments_dir.exists():
            return None

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in attachments_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(attachments_dir)))
        return buffer.getvalue()

    def _set_progress(self, job_id: str, step: str, progress: int, status: str = "processing", error: Optional[str] = None):
        with self.lock:
            job = self.jobs[job_id]
            job.step = step
            job.progress = progress
            job.status = status
            job.error = error
            if status in {"completed", "failed"}:
                job.finished_at = datetime.utcnow().isoformat()

    def _run_job(self, job_id: str, report_month: Optional[str]):
        self._set_progress(job_id, "initializing", 1, "processing")
        try:
            config = self.config
            input_dir = Path(config["paths"]["temp"]) / "jobs" / job_id / "input"
            files = list(input_dir.glob("*.msg"))
            if not files:
                raise RuntimeError("No .msg files uploaded")

            parser = MSGParser()
            thread_builder = ThreadBuilder(config)
            api_client = ClaudeAPIClient(config)
            categorizer = Categorizer(config, api_client)
            summarizer = Summarizer(config, api_client)
            word_generator = WordReportGenerator(config)
            attachment_manager = AttachmentManager(config)

            self._set_progress(job_id, "parsing", 10)
            messages = parser.parse_files(files)

            self._set_progress(job_id, "threading", 30)
            threads = thread_builder.build_threads(messages)

            self._set_progress(job_id, "categorization", 50)
            categories = categorizer.categorize_threads(threads)

            self._set_progress(job_id, "summarization", 70)
            summaries = summarizer.summarize_categories(categories)

            output_dir = Path(config["paths"]["output"]) / "jobs" / job_id
            output_dir.mkdir(parents=True, exist_ok=True)
            report_filename = f"Monthly_Report_{datetime.now().strftime('%Y_%m_%d_%H%M')}.docx"
            report_path = output_dir / report_filename

            self._set_progress(job_id, "report_generation", 85)
            word_generator.generate_report(
                summaries=summaries,
                output_path=report_path,
                report_month=report_month or datetime.now().strftime("%B %Y"),
            )

            self._set_progress(job_id, "attachments", 95)
            att_stats = attachment_manager.save_attachments(categories, output_dir)

            stats = {
                "total_messages": len(messages),
                "total_threads": len(threads),
                "total_categories": len(categories),
                "total_attachments": att_stats["total_attachments"],
                "report_size_kb": round(report_path.stat().st_size / 1024, 1),
            }

            with self.lock:
                job = self.jobs[job_id]
                job.report_path = str(report_path)
                job.attachments_path = str(output_dir / "Attachments")
                job.stats = stats

            self._set_progress(job_id, "completed", 100, status="completed")

        except Exception as exc:
            self.logger.exception("Job %s failed", job_id)
            self._set_progress(job_id, "failed", 100, status="failed", error=str(exc))

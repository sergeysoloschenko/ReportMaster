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
from src.processors.deduplicator import deduplicate_messages, deduplicate_uploads
from src.processors.document_extractor import DocumentExtractor, SUPPORTED_DOCUMENT_EXTENSIONS
from src.processors.source_document import SourceDocumentLoader
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

        input_dir = Path(self.config["paths"]["temp"]) / "jobs" / job_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        unique_uploads, upload_stats = deduplicate_uploads(zip(filenames, files))
        for filename, data, file_hash in unique_uploads:
            safe_name = Path(filename).name
            output_path = self._unique_input_path(input_dir, safe_name, file_hash)
            output_path.write_bytes(data)

        job.stats = {
            "uploaded_files": upload_stats.input_count,
            "unique_uploaded_files": upload_stats.unique_count,
            "duplicate_uploaded_files": upload_stats.duplicate_count,
        }

        with self.lock:
            self.jobs[job_id] = job

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
            files = [path for path in input_dir.iterdir() if path.is_file()]
            msg_files = [path for path in files if path.suffix.lower() == ".msg"]
            document_files = [path for path in files if path.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS]
            if not msg_files and not document_files:
                raise RuntimeError("No supported files uploaded")

            document_extractor = DocumentExtractor(max_chars=config.get("processing", {}).get("max_document_chars", 12000))
            parser = MSGParser(document_extractor=document_extractor)
            document_loader = SourceDocumentLoader(document_extractor=document_extractor)
            thread_builder = ThreadBuilder(config)
            api_client = ClaudeAPIClient(config)
            categorizer = Categorizer(config, api_client)
            summarizer = Summarizer(config, api_client)
            word_generator = WordReportGenerator(config)
            attachment_manager = AttachmentManager(config)

            self._set_progress(job_id, "parsing", 10)
            email_messages = parser.parse_files(msg_files)
            document_messages = document_loader.load_files(document_files)
            messages = [*email_messages, *document_messages]
            unique_messages, message_dedup_stats = deduplicate_messages(messages)
            if not unique_messages:
                raise RuntimeError("No readable unique content found in uploaded files")

            self._set_progress(job_id, "threading", 30)
            threads = thread_builder.build_threads(unique_messages)

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
                "uploaded_files": self.get_job(job_id).stats.get("uploaded_files", 0),
                "unique_uploaded_files": self.get_job(job_id).stats.get("unique_uploaded_files", 0),
                "duplicate_uploaded_files": self.get_job(job_id).stats.get("duplicate_uploaded_files", 0),
                "parsed_emails": len(email_messages),
                "parsed_documents": len(document_messages),
                "total_messages": len(unique_messages),
                "duplicate_messages": message_dedup_stats.duplicate_count,
                "total_threads": len(threads),
                "total_categories": len(categories),
                "total_attachments": att_stats["total_attachments"],
                "unique_attachments": att_stats.get("unique_attachments", att_stats["total_attachments"]),
                "duplicate_attachments": att_stats.get("duplicate_attachments", 0),
                "report_size_kb": round(report_path.stat().st_size / 1024, 1),
            }
            usage_stats = api_client.get_usage_stats()
            stats.update(
                {
                    "input_tokens": usage_stats.get("prompt_tokens", 0),
                    "output_tokens": usage_stats.get("completion_tokens", 0),
                    "total_tokens": usage_stats.get("total_tokens", 0),
                    "llm_cache_hits": usage_stats.get("cache_hits", 0),
                    "llm_cache_misses": usage_stats.get("cache_misses", 0),
                }
            )

            with self.lock:
                job = self.jobs[job_id]
                job.report_path = str(report_path)
                job.attachments_path = str(output_dir / "Attachments")
                job.stats = stats

            self._set_progress(job_id, "completed", 100, status="completed")

        except Exception as exc:
            self.logger.exception("Job %s failed", job_id)
            self._set_progress(job_id, "failed", 100, status="failed", error=str(exc))

    def _unique_input_path(self, input_dir: Path, filename: str, file_hash: str) -> Path:
        safe_name = Path(filename).name or f"upload_{file_hash[:12]}"
        output_path = input_dir / safe_name
        if not output_path.exists():
            return output_path

        stem = output_path.stem
        suffix = output_path.suffix
        return input_dir / f"{stem}_{file_hash[:12]}{suffix}"

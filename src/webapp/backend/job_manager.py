import io
import logging
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from src.analyzers.categorizer import ThreadCategory
from src.analyzers.monthly_directions import MonthlyDirectionCategorizer
from src.analyzers.summarizer import Summarizer
from src.analyzers.thread_insights import ThreadInsightAnalyzer
from src.generators.attachment_manager import AttachmentManager
from src.generators.word_generator import WordReportGenerator
from src.processors.deduplicator import deduplicate_messages, deduplicate_upload_paths, deduplicate_uploads
from src.processors.document_extractor import DocumentExtractor, SUPPORTED_DOCUMENT_EXTENSIONS
from src.processors.source_document import SourceDocumentLoader
from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.utils.api_client import ClaudeAPIClient
from src.utils.config_loader import load_config

MONTHLY_MODE = "monthly_msg_report"
CUSTOM_MODE = "custom_analysis"


@dataclass
class JobState:
    job_id: str
    mode: str = MONTHLY_MODE
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
        max_workers = int(self.config.get("processing", {}).get("job_max_workers", 1))
        self.executor = ThreadPoolExecutor(max_workers=max(1, max_workers))

    def create_job(
        self,
        files: List[bytes],
        filenames: List[str],
        report_month: Optional[str] = None,
        mode: str = MONTHLY_MODE,
        user_prompt: Optional[str] = None,
    ) -> JobState:
        job_id = uuid4().hex
        job = JobState(job_id=job_id, mode=mode)

        input_dir = Path(self.config["paths"]["temp"]) / "jobs" / job_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        unique_uploads, upload_stats = deduplicate_uploads(zip(filenames, files))
        for filename, data, file_hash in unique_uploads:
            safe_name = Path(filename).name
            output_path = self._unique_input_path(input_dir, safe_name, file_hash)
            output_path.write_bytes(data)

        job.stats = {
            "mode": mode,
            "uploaded_files": upload_stats.input_count,
            "unique_uploaded_files": upload_stats.unique_count,
            "duplicate_uploaded_files": upload_stats.duplicate_count,
        }

        with self.lock:
            self.jobs[job_id] = job

        self.executor.submit(self._run_job, job_id, report_month, mode, user_prompt)
        return job

    def create_job_from_paths(
        self,
        files: List[Path],
        filenames: List[str],
        report_month: Optional[str] = None,
        mode: str = MONTHLY_MODE,
        user_prompt: Optional[str] = None,
    ) -> JobState:
        job_id = uuid4().hex
        job = JobState(job_id=job_id, mode=mode)

        input_dir = Path(self.config["paths"]["temp"]) / "jobs" / job_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        unique_uploads, upload_stats = deduplicate_upload_paths(zip(filenames, files))
        for filename, path, file_hash in unique_uploads:
            safe_name = Path(filename).name
            output_path = self._unique_input_path(input_dir, safe_name, file_hash)
            shutil.move(str(path), output_path)

        job.stats = {
            "mode": mode,
            "uploaded_files": upload_stats.input_count,
            "unique_uploaded_files": upload_stats.unique_count,
            "duplicate_uploaded_files": upload_stats.duplicate_count,
        }

        with self.lock:
            self.jobs[job_id] = job

        self.executor.submit(self._run_job, job_id, report_month, mode, user_prompt)
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

    def _run_job(self, job_id: str, report_month: Optional[str], mode: str, user_prompt: Optional[str]):
        self._set_progress(job_id, "initializing", 1, "processing")
        try:
            config = self.config
            input_dir = Path(config["paths"]["temp"]) / "jobs" / job_id / "input"
            files = [path for path in input_dir.iterdir() if path.is_file()]
            msg_files = [path for path in files if path.suffix.lower() == ".msg"]
            document_files = [path for path in files if path.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS]
            if mode == MONTHLY_MODE and not msg_files:
                raise RuntimeError("Monthly report mode requires .msg files")
            if mode == CUSTOM_MODE and not msg_files and not document_files:
                raise RuntimeError("No supported files uploaded")

            document_extractor = DocumentExtractor(max_chars=config.get("processing", {}).get("max_document_chars", 12000))
            parser = MSGParser(document_extractor=document_extractor)
            document_loader = SourceDocumentLoader(document_extractor=document_extractor)
            thread_builder = ThreadBuilder(config)
            api_client = ClaudeAPIClient(config)
            insight_analyzer = ThreadInsightAnalyzer(config, api_client)
            summarizer = Summarizer(config, api_client)
            word_generator = WordReportGenerator(config)
            attachment_manager = AttachmentManager(config)

            self._set_progress(job_id, "parsing", 10)
            email_messages = parser.parse_files(msg_files)
            document_messages = document_loader.load_files(document_files) if mode == CUSTOM_MODE else []
            messages = [*email_messages, *document_messages]
            unique_messages, message_dedup_stats = deduplicate_messages(messages)
            if not unique_messages:
                raise RuntimeError("No readable unique content found in uploaded files")

            self._set_progress(job_id, "threading", 30)
            threads = thread_builder.build_threads(unique_messages)

            output_dir = Path(config["paths"]["output"]) / "jobs" / job_id
            output_dir.mkdir(parents=True, exist_ok=True)

            if mode == MONTHLY_MODE:
                self._set_progress(job_id, "thread_insights", 45)
                insights = insight_analyzer.analyze_threads(threads)

                self._set_progress(job_id, "direction_classification", 60)
                categories = MonthlyDirectionCategorizer().categorize_insights(insights)

                self._set_progress(job_id, "direction_summarization", 75)
                summaries = summarizer.summarize_monthly_categories_from_insights(categories)

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
                total_categories = len(categories)
                total_insights = len(insights)
            else:
                self._set_progress(job_id, "custom_analysis", 70)
                source_texts = self._collect_source_texts(unique_messages)
                analysis = api_client.run_custom_analysis(
                    user_prompt=(user_prompt or "").strip(),
                    source_texts=source_texts,
                    title="Пользовательский анализ",
                )

                report_filename = f"Custom_Analysis_{datetime.now().strftime('%Y_%m_%d_%H%M')}.docx"
                report_path = output_dir / report_filename

                self._set_progress(job_id, "report_generation", 85)
                word_generator.generate_custom_report(
                    analysis=analysis,
                    output_path=report_path,
                    report_month=report_month,
                )

                self._set_progress(job_id, "attachments", 95)
                custom_category = ThreadCategory("CUSTOM", "Исходные вложения", "Вложения из исходных писем")
                for thread in threads:
                    custom_category.add_thread(thread)
                att_stats = attachment_manager.save_attachments([custom_category], output_dir)
                total_categories = 0
                total_insights = 0

            stats = {
                "mode": mode,
                "uploaded_files": self.get_job(job_id).stats.get("uploaded_files", 0),
                "unique_uploaded_files": self.get_job(job_id).stats.get("unique_uploaded_files", 0),
                "duplicate_uploaded_files": self.get_job(job_id).stats.get("duplicate_uploaded_files", 0),
                "parsed_emails": len(email_messages),
                "parsed_documents": len(document_messages),
                "total_messages": len(unique_messages),
                "duplicate_messages": message_dedup_stats.duplicate_count,
                "total_threads": len(threads),
                "total_categories": total_categories,
                "total_insights": total_insights,
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
                    "codex_runs": usage_stats.get("codex_runs", 0),
                    "prompt_chars": usage_stats.get("prompt_chars", 0),
                    "output_chars": usage_stats.get("output_chars", 0),
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

    def _collect_source_texts(self, messages) -> List[str]:
        source_texts = []
        seen = set()
        max_sources = self.config.get("processing", {}).get("max_custom_sources", 80)
        max_chars = self.config.get("processing", {}).get("max_custom_source_chars", 5000)

        for message in messages:
            text = (getattr(message, "analysis_body", None) or getattr(message, "body", "") or "").strip()
            if not text:
                continue
            text_key = getattr(message, "normalized_body_hash", "") or text[:200]
            if text_key in seen:
                continue
            seen.add(text_key)
            title = getattr(message, "subject", None) or Path(getattr(message, "file_path", "")).name
            source_texts.append(f"[{title}]\n{text[:max_chars]}")
            if len(source_texts) >= max_sources:
                break

        return source_texts

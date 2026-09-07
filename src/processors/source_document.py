"""
Represent standalone uploaded documents as analysis messages.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.processors.deduplicator import hash_text
from src.processors.document_extractor import DocumentExtractor, ExtractedDocument


class SourceDocumentMessage:
    """A document-only input adapted to the email pipeline interface."""

    def __init__(self, path: Path, extracted: ExtractedDocument):
        self.logger = logging.getLogger(__name__)
        self.file_path = path
        self.msg_id = hashlib.md5(str(path).encode()).hexdigest()[:12]
        self.subject = f"Документ: {path.name}"
        self.sender = "Uploaded document"
        self.recipients: List[str] = []
        self.cc: List[str] = []
        self.date = datetime.fromtimestamp(path.stat().st_mtime)
        self.message_id = f"document:{extracted.content_hash}"
        self.in_reply_to = ""
        self.references: List[str] = []
        self.body = extracted.text
        self.html_body = ""
        self.analysis_body = extracted.text
        self.normalized_body_hash = hash_text(extracted.text)
        self.attachments: List[Dict] = []
        self.has_attachments = False
        self.extracted_attachment_count = 0

    @property
    def attachment_count(self) -> int:
        return 0

    def get_clean_body(self) -> str:
        return self.analysis_body


class SourceDocumentLoader:
    """Load standalone non-email documents into the common analysis pipeline."""

    def __init__(self, document_extractor: Optional[DocumentExtractor] = None):
        self.logger = logging.getLogger(__name__)
        self.document_extractor = document_extractor or DocumentExtractor()

    def load_files(self, paths: List[Path]) -> List[SourceDocumentMessage]:
        messages = []
        seen_hashes = set()

        for path in paths:
            extracted = self.document_extractor.extract_path(path)
            if not extracted.has_text:
                self.logger.info("Skipping document without extracted text: %s (%s)", path.name, extracted.skipped_reason)
                continue
            if extracted.content_hash in seen_hashes:
                self.logger.info("Skipping duplicate standalone document: %s", path.name)
                continue
            seen_hashes.add(extracted.content_hash)
            messages.append(SourceDocumentMessage(path, extracted))

        return messages

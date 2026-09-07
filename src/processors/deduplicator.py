"""
Content fingerprinting and deduplication helpers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple


@dataclass
class DeduplicationStats:
    input_count: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    duplicate_names: List[str] = field(default_factory=list)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text_for_hash(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[-=_]{3,}", " ", text)
    text = re.sub(r"(from|sent|to|subject|от|кому|тема):", " ", text)
    return text.strip()


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_text_for_hash(text).encode("utf-8")).hexdigest()


def normalize_subject_for_hash(subject: str) -> str:
    subject = normalize_text_for_hash(subject)
    prefixes = r"^(re|fw|fwd|aw|ответ|отв|пересл|переслано|перенаправлено)\s*:\s*"
    changed = True
    while changed:
        before = subject
        subject = re.sub(prefixes, "", subject).strip()
        changed = before != subject
    return subject


def deduplicate_uploads(files: Iterable[Tuple[str, bytes]]) -> Tuple[List[Tuple[str, bytes, str]], DeduplicationStats]:
    seen = set()
    unique = []
    stats = DeduplicationStats()

    for filename, data in files:
        stats.input_count += 1
        file_hash = hash_bytes(data)
        if file_hash in seen:
            stats.duplicate_count += 1
            stats.duplicate_names.append(Path(filename).name)
            continue
        seen.add(file_hash)
        unique.append((filename, data, file_hash))

    stats.unique_count = len(unique)
    return unique, stats


def deduplicate_upload_paths(files: Iterable[Tuple[str, Path]]) -> Tuple[List[Tuple[str, Path, str]], DeduplicationStats]:
    seen = set()
    unique = []
    stats = DeduplicationStats()

    for filename, path in files:
        stats.input_count += 1
        file_hash = hash_file(path)
        if file_hash in seen:
            stats.duplicate_count += 1
            stats.duplicate_names.append(Path(filename).name)
            continue
        seen.add(file_hash)
        unique.append((filename, path, file_hash))

    stats.unique_count = len(unique)
    return unique, stats


def deduplicate_messages(messages) -> Tuple[List, DeduplicationStats]:
    seen = set()
    unique = []
    stats = DeduplicationStats(input_count=len(messages))

    for message in messages:
        key = message_dedup_key(message)
        if key in seen:
            stats.duplicate_count += 1
            stats.duplicate_names.append(Path(getattr(message, "file_path", "")).name or getattr(message, "subject", "message"))
            continue
        seen.add(key)
        unique.append(message)

    stats.unique_count = len(unique)
    return unique, stats


def message_dedup_key(message) -> str:
    message_id = (getattr(message, "message_id", "") or "").strip().lower()
    if message_id:
        return f"message-id:{message_id}"

    date = getattr(message, "date", None)
    date_key = _date_key(date)
    subject = normalize_subject_for_hash(getattr(message, "subject", ""))
    sender = normalize_text_for_hash(getattr(message, "sender", ""))
    body_hash = getattr(message, "normalized_body_hash", "") or hash_text(getattr(message, "body", ""))
    return f"fallback:{subject}:{sender}:{date_key}:{body_hash}"


def _date_key(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    return str(value or "")

"""
Early LLM analysis of email threads before monthly report aggregation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.analyzers.monthly_directions import MONTHLY_DIRECTIONS
from src.parsers.thread_builder import EmailThread
from src.processors.deduplicator import hash_text, message_dedup_key
from src.utils.api_client import ClaudeAPIClient


@dataclass
class ThreadInsight:
    thread_id: str
    thread_hash: str
    subject: str
    direction_id: str
    direction_name: str
    summary: str
    actions: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)
    parties: List[str] = field(default_factory=list)
    date_range: str = "Н/Д"
    message_count: int = 0
    attachment_count: int = 0
    confidence: str = "medium"
    relevance_reason: str = ""
    triage_confidence: str = "medium"
    source_thread: Optional[EmailThread] = None

    @classmethod
    def from_llm(cls, thread: EmailThread, thread_hash: str, date_range: str, payload: Dict[str, Any]) -> "ThreadInsight":
        direction_id = _valid_direction_id(payload.get("direction_id"))
        direction_name = next(
            direction.name for direction in MONTHLY_DIRECTIONS if direction.direction_id == direction_id
        )
        return cls(
            thread_id=thread.thread_id,
            thread_hash=thread_hash,
            subject=thread.subject or payload.get("title", ""),
            direction_id=direction_id,
            direction_name=direction_name,
            summary=(payload.get("summary") or "").strip(),
            actions=_list_of_strings(payload.get("actions")),
            decisions=_list_of_strings(payload.get("decisions")),
            open_questions=_list_of_strings(payload.get("open_questions")),
            risks=_list_of_strings(payload.get("risks")),
            next_steps=_list_of_strings(payload.get("next_steps")),
            documents=_list_of_strings(payload.get("documents")),
            parties=_list_of_strings(payload.get("parties")),
            date_range=date_range,
            message_count=thread.message_count,
            attachment_count=thread.total_attachments,
            confidence=(payload.get("confidence") or "medium").strip(),
            relevance_reason=(payload.get("relevance_reason") or payload.get("reason") or "").strip(),
            triage_confidence=(payload.get("triage_confidence") or payload.get("confidence") or "medium").strip(),
            source_thread=thread,
        )


class ThreadInsightAnalyzer:
    """Create compact, cached LLM cards for each email thread."""

    def __init__(self, config: dict, api_client: ClaudeAPIClient):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.api_client = api_client
        processing_cfg = config.get("processing", {})
        self.max_thread_messages = processing_cfg.get("max_thread_insight_messages", 12)
        self.max_message_chars = processing_cfg.get("max_thread_insight_message_chars", 1800)
        self.max_attachment_chars = processing_cfg.get("max_thread_insight_attachment_chars", 1200)
        self.last_triage_stats = {
            "included_threads": 0,
            "excluded_threads": 0,
        }

    def analyze_threads(self, threads: List[EmailThread]) -> List[ThreadInsight]:
        insights = []
        self.last_triage_stats = {
            "included_threads": 0,
            "excluded_threads": 0,
        }
        for idx, thread in enumerate(threads, 1):
            self.logger.info("Analyzing thread insight %s/%s: %s", idx, len(threads), thread.subject[:80])
            insight = self.analyze_thread(thread)
            if insight is None:
                self.last_triage_stats["excluded_threads"] += 1
                continue
            self.last_triage_stats["included_threads"] += 1
            insights.append(insight)
        return insights

    def analyze_thread(self, thread: EmailThread) -> Optional[ThreadInsight]:
        thread_hash = self._thread_hash(thread)
        date_range = self._date_range(thread)
        payload = self._thread_payload(thread, thread_hash, date_range)
        triage = self._triage_thread(payload)
        if not _as_bool(triage.get("include_in_report"), default=True):
            self.logger.info(
                "Excluded thread from report: %s (%s)",
                thread.subject[:80],
                triage.get("reason") or triage.get("relevance_reason") or "not relevant",
            )
            return None

        payload["preliminary_triage"] = triage
        result = self.api_client.analyze_thread_insight(payload, self._directions_payload())
        result.setdefault("relevance_reason", triage.get("reason") or triage.get("relevance_reason") or "")
        result.setdefault("triage_confidence", triage.get("confidence") or "medium")
        return ThreadInsight.from_llm(thread, thread_hash, date_range, result)

    def _triage_thread(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if hasattr(self.api_client, "triage_thread_relevance"):
            return self.api_client.triage_thread_relevance(payload, self._directions_payload())
        return {
            "include_in_report": True,
            "direction_id": "DIR_006",
            "reason": "Triage API is unavailable; included conservatively.",
            "confidence": "low",
        }

    def _thread_payload(self, thread: EmailThread, thread_hash: str, date_range: str) -> Dict[str, Any]:
        messages = self._select_messages(thread.messages)
        return {
            "thread_id": thread.thread_id,
            "thread_hash": thread_hash,
            "subject": thread.subject,
            "date_range": date_range,
            "participants": sorted(thread.participants)[:30],
            "message_count": thread.message_count,
            "attachment_count": thread.total_attachments,
            "messages": [self._message_payload(message) for message in messages],
        }

    def _message_payload(self, message) -> Dict[str, Any]:
        body = (getattr(message, "analysis_body", None) or getattr(message, "body", "") or "").strip()
        attachments = []
        for attachment in getattr(message, "attachments", []) or []:
            item = {
                "filename": attachment.get("filename", "unnamed"),
                "size": attachment.get("size", 0),
            }
            extracted = (attachment.get("extracted_text") or "").strip()
            if extracted:
                item["text_excerpt"] = extracted[: self.max_attachment_chars]
            attachments.append(item)

        return {
            "date": message.date.isoformat() if getattr(message, "date", None) else "",
            "subject": getattr(message, "subject", ""),
            "sender": getattr(message, "sender", ""),
            "recipients": getattr(message, "recipients", [])[:10],
            "cc": getattr(message, "cc", [])[:10],
            "body_excerpt": body[: self.max_message_chars],
            "attachments": attachments[:12],
        }

    def _select_messages(self, messages: List[Any]) -> List[Any]:
        if len(messages) <= self.max_thread_messages:
            return list(messages)

        selected = []
        head_count = max(2, self.max_thread_messages // 3)
        tail_count = max(3, self.max_thread_messages // 3)
        selected.extend(messages[:head_count])

        middle_slots = self.max_thread_messages - head_count - tail_count
        middle = messages[head_count:-tail_count]
        important = [
            message for message in middle
            if getattr(message, "has_attachments", False)
            or self._looks_decision_like(getattr(message, "body", "") or "")
        ][:middle_slots]
        selected.extend(important)
        selected.extend(messages[-tail_count:])

        seen = set()
        unique = []
        for message in selected:
            key = message_dedup_key(message)
            if key in seen:
                continue
            seen.add(key)
            unique.append(message)
        return unique

    def _thread_hash(self, thread: EmailThread) -> str:
        keys = [message_dedup_key(message) for message in thread.messages]
        return hash_text("|".join(sorted(keys)))

    def _date_range(self, thread: EmailThread) -> str:
        dates = [message.date for message in thread.messages if getattr(message, "date", None)]
        if not dates:
            return "Н/Д"
        start = min(dates).strftime("%d.%m.%Y")
        end = max(dates).strftime("%d.%m.%Y")
        return f"{start}-{end}" if start != end else start

    def _directions_payload(self) -> List[Dict[str, str]]:
        return [
            {
                "direction_id": direction.direction_id,
                "name": direction.name,
                "description": direction.description,
            }
            for direction in MONTHLY_DIRECTIONS
        ]

    def _looks_decision_like(self, text: str) -> bool:
        lowered = (text or "").lower()
        markers = (
            "согласовано",
            "принято",
            "решили",
            "decision",
            "approved",
            "not approved",
            "requires revision",
            "требует доработ",
            "комментар",
        )
        return any(marker in lowered for marker in markers)


def _valid_direction_id(value: Any) -> str:
    direction_ids = {direction.direction_id for direction in MONTHLY_DIRECTIONS}
    value = (str(value or "")).strip()
    return value if value in direction_ids else "DIR_006"


def _list_of_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "да", "включить", "include"}:
            return True
        if normalized in {"false", "no", "0", "нет", "исключить", "exclude"}:
            return False
    return default

"""
Fixed monthly report directions for the default ReportMaster workflow.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List

from src.analyzers.categorizer import ThreadCategory
from src.parsers.thread_builder import EmailThread


@dataclass(frozen=True)
class ReportDirection:
    direction_id: str
    name: str
    description: str
    patterns: tuple[str, ...]


MONTHLY_DIRECTIONS = [
    ReportDirection(
        direction_id="DIR_001",
        name="Договор управления с гостиничным оператором Dusit",
        description="Переписка по согласованию, условиям, приложениям и статусу договора управления с Dusit.",
        patterns=(
            r"\bdusit\b",
            r"договор управлен",
            r"management agreement",
            r"hotel management agreement",
            r"operator agreement",
            r"гостиничн\w+ оператор",
        ),
    ),
    ReportDirection(
        direction_id="DIR_002",
        name="Техническое сопровождение проектирования Dusit",
        description="Технические требования Dusit, проектные комментарии, согласование решений и сопровождение проектирования.",
        patterns=(
            r"\bdusit\b.*(техничес|проект|design|technical|бренд|brand|standards)",
            r"(техничес|проект|design|technical|бренд|brand|standards).*\bdusit\b",
            r"brand standards",
            r"design review",
            r"technical requirement",
            r"техническ\w+ требован",
        ),
    ),
    ReportDirection(
        direction_id="DIR_003",
        name="Работа с консультантами проекта",
        description="Взаимодействие с проектными консультантами, согласование заданий, комментариев, материалов и статусов.",
        patterns=(
            r"консультант",
            r"consultant",
            r"архитект",
            r"проектиров",
            r"инженер",
            r"согласован\w+ тз",
            r"комментарии консульт",
        ),
    ),
    ReportDirection(
        direction_id="DIR_004",
        name="Взаимодействие с Dyer",
        description="Переписка и рабочие вопросы с Dyer Group.",
        patterns=(
            r"\bdyer\b",
            r"groupdyer",
            r"dyergroup",
        ),
    ),
    ReportDirection(
        direction_id="DIR_005",
        name="Взаимодействие с Заказчиком/Инвестором",
        description="Вопросы, согласования, отчётность и решения со стороны Заказчика или Инвестора.",
        patterns=(
            r"заказчик",
            r"инвестор",
            r"client",
            r"investor",
            r"порт геленджик",
            r"port-gdz",
            r"собственник",
        ),
    ),
    ReportDirection(
        direction_id="DIR_006",
        name="Прочее",
        description="Материалы, не отнесённые к основным направлениям отчёта.",
        patterns=(),
    ),
]


class MonthlyDirectionCategorizer:
    """Assign email threads to the fixed monthly report directions."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def categorize_threads(self, threads: List[EmailThread]) -> List[ThreadCategory]:
        categories = [
            ThreadCategory(direction.direction_id, direction.name, direction.description)
            for direction in MONTHLY_DIRECTIONS
        ]
        by_id: Dict[str, ThreadCategory] = {category.category_id: category for category in categories}

        for thread in threads:
            direction = self._classify_thread(thread)
            by_id[direction.direction_id].add_thread(thread)
            self.logger.info("Monthly direction: %s -> %s", thread.subject[:60], direction.name)

        return categories

    def categorize_insights(self, insights: List["ThreadInsight"]) -> List[ThreadCategory]:
        categories = [
            ThreadCategory(direction.direction_id, direction.name, direction.description)
            for direction in MONTHLY_DIRECTIONS
        ]
        by_id: Dict[str, ThreadCategory] = {category.category_id: category for category in categories}

        for insight in insights:
            category = by_id.get(insight.direction_id) or by_id["DIR_006"]
            category.add_insight(insight)
            self.logger.info("Monthly insight direction: %s -> %s", insight.subject[:60], category.name)

        return categories

    def _classify_thread(self, thread: EmailThread) -> ReportDirection:
        text = self._thread_text(thread)

        # Dyer is a specific counterparty and should win over generic consultant wording.
        for direction_id in ("DIR_004", "DIR_001", "DIR_002", "DIR_005", "DIR_003"):
            direction = next(item for item in MONTHLY_DIRECTIONS if item.direction_id == direction_id)
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in direction.patterns):
                if direction.direction_id == "DIR_001" and self._looks_like_dusit_technical(text):
                    continue
                return direction

        return MONTHLY_DIRECTIONS[-1]

    def _thread_text(self, thread: EmailThread) -> str:
        chunks = [thread.subject or ""]
        for participant in sorted(thread.participants):
            chunks.append(participant or "")
        for message in thread.messages[:8]:
            chunks.append(getattr(message, "analysis_body", None) or getattr(message, "body", "") or "")
            for attachment in getattr(message, "attachments", []) or []:
                chunks.append(attachment.get("filename", ""))
        return "\n".join(chunks).lower()

    def _looks_like_dusit_technical(self, text: str) -> bool:
        return bool(
            re.search(r"\bdusit\b", text, re.IGNORECASE)
            and re.search(r"техничес|проект|design|technical|brand|standard|чертеж|drawing", text, re.IGNORECASE)
        )

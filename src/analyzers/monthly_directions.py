"""Fixed report rows matching the contract report fragment supplied by the user."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List

from src.analyzers.categorizer import ThreadCategory
from src.parsers.thread_builder import EmailThread

if TYPE_CHECKING:
    from src.analyzers.thread_insights import ThreadInsight


@dataclass(frozen=True)
class ReportDirection:
    direction_id: str
    section_number: str
    name: str
    report_heading: str
    description: str
    writing_guidance: str
    patterns: tuple[str, ...]


MONTHLY_DIRECTIONS = [
    ReportDirection(
        direction_id="DIR_001",
        section_number="4.1",
        name="Договор управления с гостиничным оператором Dusit",
        report_heading="Договор управления с гостиничным оператором Dusit",
        description="Согласование HMA, финансовой модели, коммерческих условий, приложений и статуса договора управления с Dusit.",
        writing_guidance="Отразить влияние согласований и недостающих материалов на финализацию договора.",
        patterns=(
            r"\bdusit\b.*(договор|agreement|hma|term sheet|loi|финансов\w+ модел)",
            r"(договор|agreement|hma|term sheet|loi|финансов\w+ модел).*\bdusit\b",
            r"hotel management agreement",
            r"management agreement",
            r"договор.*оператор",
        ),
    ),
    ReportDirection(
        direction_id="DIR_002",
        section_number="4.2",
        name="Техническое взаимодействие с гостиничным оператором Dusit",
        report_heading="",
        description="Требования и решения Dusit по проектированию, стандартам, мокапам, F&B, FF&E, инженерным системам и эксплуатации отеля.",
        writing_guidance="Сгруппировать факты по проектным решениям; отдельно сформулировать подтвержденный результат работ, если он есть.",
        patterns=(
            r"\bdusit\b",
            r"оператор.*(техничес|проект|design|standard|мокап|ff&e|f&b)",
            r"brand standards",
            r"technical requirement",
        ),
    ),
    ReportDirection(
        direction_id="DIR_003",
        section_number="4.3",
        name="Работа с консультантами проекта",
        report_heading="Работа с консультантами проекта",
        description="Проверка расчётов, материалов и предложений проектных консультантов, подготовка заданий и сопровождение договорных вопросов с консультантами.",
        writing_guidance="Показать выявленные замечания, их влияние на бюджет/сроки/качество и необходимые действия.",
        patterns=(
            r"консультант",
            r"consultant",
            r"\bиск\b",
            r"инспир",
            r"аполло",
            r"проектиров",
            r"инженер",
            r"\bmep\b",
            r"конструкц",
        ),
    ),
    ReportDirection(
        direction_id="DIR_004",
        section_number="4.4",
        name="Взаимодействие с Dyer",
        report_heading="Взаимодействие с Dyer",
        description="Проектные и архитектурные решения с Dyer Group, включая планировки, детальный дизайн, фасады, патио, мокапы и общественные пространства.",
        writing_guidance="Сначала перечислить критичные блоки работ, затем существенные открытые вопросы и подтвержденные решения.",
        patterns=(
            r"\bdyer\b",
            r"groupdyer",
            r"dyergroup",
            r"даер",
            r"архитектор",
            r"architect",
            r"architectural",
        ),
    ),
    ReportDirection(
        direction_id="DIR_005",
        section_number="4.5",
        name="Архитектурный надзор и пространственная координация",
        report_heading=(
            "В рамках заключенных Дополнительных соглашений № 4, 5 на оказание услуг по "
            "архитектурному надзору и пространственной координации ведется работа с Архитектором проекта"
        ),
        description="Задания и результаты по архитектурному надзору и пространственной координации в рамках Дополнительных соглашений № 4 и № 5.",
        writing_guidance="Указать состояние реестра заданий, официальные письма, выезды, согласования и фактические результаты за период.",
        patterns=(
            r"архитектурн\w+ надзор",
            r"пространственн\w+ координац",
            r"реестр\w* задан",
            r"дополнительн\w+ соглашен\w* №?\s*[45]",
            r"\bан\b.*\bпк\b",
        ),
    ),
]


class MonthlyDirectionCategorizer:
    """Assign reportable email threads to the five fixed rows in the sample."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def categorize_threads(self, threads: List[EmailThread]) -> List[ThreadCategory]:
        categories = self._empty_categories()
        by_id: Dict[str, ThreadCategory] = {category.category_id: category for category in categories}

        for thread in threads:
            direction = self._classify_thread(thread)
            by_id[direction.direction_id].add_thread(thread)
            self.logger.info("Monthly direction: %s -> %s", thread.subject[:60], direction.name)
        return categories

    def categorize_insights(self, insights: List["ThreadInsight"]) -> List[ThreadCategory]:
        categories = self._empty_categories()
        by_id: Dict[str, ThreadCategory] = {category.category_id: category for category in categories}

        for insight in insights:
            category = by_id.get(insight.direction_id) or by_id["DIR_003"]
            category.add_insight(insight)
            self.logger.info("Monthly insight direction: %s -> %s", insight.subject[:60], category.name)
        return categories

    def _empty_categories(self) -> List[ThreadCategory]:
        return [
            ThreadCategory(direction.direction_id, direction.name, direction.description)
            for direction in MONTHLY_DIRECTIONS
        ]

    def _classify_thread(self, thread: EmailThread) -> ReportDirection:
        text = self._thread_text(thread)

        # Specific contractual/supervision rows must win over generic Dusit/Dyer wording.
        for direction_id in ("DIR_005", "DIR_001", "DIR_002", "DIR_004", "DIR_003"):
            direction = next(item for item in MONTHLY_DIRECTIONS if item.direction_id == direction_id)
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in direction.patterns):
                return direction
        return next(item for item in MONTHLY_DIRECTIONS if item.direction_id == "DIR_003")

    def _thread_text(self, thread: EmailThread) -> str:
        chunks = [thread.subject or ""]
        chunks.extend(participant or "" for participant in sorted(thread.participants))
        for message in thread.messages[:8]:
            chunks.append(getattr(message, "analysis_body", None) or getattr(message, "body", "") or "")
            for attachment in getattr(message, "attachments", []) or []:
                chunks.append(attachment.get("filename", ""))
        return "\n".join(chunks).lower()

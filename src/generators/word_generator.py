"""
Word Document Generator
Creates formal monthly reports following the consultant/operator section template
"""

import logging
import re
from pathlib import Path
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from typing import Dict, List

from src.analyzers.monthly_directions import MONTHLY_DIRECTIONS


class WordReportGenerator:
    """Generate Word document reports in formal structure"""

    TEMPLATE_PATH = Path(__file__).parent / "templates" / "monthly_report_template.docx"
    TEMPLATE_ROW_BY_DIRECTION = {
        "DIR_001": 3,
        "DIR_002": 4,
        "DIR_003": 5,
        "DIR_004": 6,
        "DIR_005": 7,
    }
    FORBIDDEN_MONTHLY_BOILERPLATE = (
        "обработана цепочка",
        "проанализирована переписка",
        "статус сформирован по карточкам",
        "требуется проверка финальной редакции",
        "существенные цепочки",
    )
    
    # Russian translations
    TRANSLATIONS_RU = {
        'title': 'Ежемесячный отчет',
        'section_title': 'Основные направления работы',
        'generated': 'Создано',
        'context': 'Контекст:',
        'actions': 'Действия:',
        'result': 'Результат / Статус:',
        'period': 'Период / Даты:',
        'parties': 'Стороны / Контрагенты:',
        'remarks': 'Замечания / Риски:',
        'recommendations': 'Рекомендации / Следующие шаги:',
        'statistics': 'Статистика отчета',
        'total_categories': 'Всего подразделов',
        'total_messages': 'Всего сообщений',
        'total_attachments': 'Всего вложений'
    }
    
    # Month names in Russian (genitive case for report title)
    MONTHS_RU = {
        1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
        5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
        9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
    }
    
    def __init__(self, config: dict):
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        report_config = config.get('report', {})
        self.table_style = report_config.get('table_style', {})
        self.font = self.table_style.get('font', 'Calibri')
        self.font_size = self.table_style.get('font_size', 11)
    
    def generate_report(self, summaries: Dict, output_path: Path, report_month: str = None) -> Path:
        """Generate a paste-ready contract report fragment from the supplied Word template."""
        self.logger.info(f"Generating structured report: {output_path}")

        template_path = self._monthly_template_path()
        doc = Document(str(template_path))
        if not doc.tables or len(doc.tables[0].rows) < 8 or len(doc.tables[0].columns) != 5:
            raise RuntimeError(f"Некорректный шаблон ежемесячного отчета: {template_path}")

        table = doc.tables[0]
        directions_by_id = {direction.direction_id: direction for direction in MONTHLY_DIRECTIONS}
        for direction_id, row_index in self.TEMPLATE_ROW_BY_DIRECTION.items():
            summary_data = dict(summaries.get(direction_id) or {})
            direction = directions_by_id[direction_id]
            summary_data.setdefault("category_name", direction.name)
            summary_data.setdefault("report_heading", direction.report_heading)

            row = table.rows[row_index]
            self._replace_cell_paragraphs(row.cells[1], self._build_monthly_narrative(summary_data))
            self._replace_cell_paragraphs(
                row.cells[2],
                self._format_report_date_range(summary_data.get("date_range")),
            )
        
        # Save document
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path))
        
        self.logger.info(f"✓ Report saved: {output_path}")
        
        return output_path

    def _monthly_template_path(self) -> Path:
        configured = self.config.get("report", {}).get("template")
        candidates = []
        if configured and configured != "default":
            configured_path = Path(configured)
            candidates.append(configured_path)
            if not configured_path.is_absolute():
                candidates.append(Path(__file__).resolve().parents[2] / configured_path)
        candidates.append(self.TEMPLATE_PATH)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError("Не найден шаблон ежемесячного отчета report_sample.docx")

    def _build_monthly_narrative(self, summary_data: Dict) -> str:
        heading = self._as_text(summary_data.get("report_heading")).strip()
        narrative = self._as_text(summary_data.get("narrative")).strip()

        if not narrative:
            overview = self._as_text(summary_data.get("overview") or summary_data.get("context")).strip()
            actions = [str(item).strip() for item in summary_data.get("actions", []) or [] if str(item).strip()]
            result = self._as_text(summary_data.get("result")).strip()
            narrative = "\n\n".join(part for part in (overview, " ".join(actions), result) if part)
        if not narrative:
            narrative = "За отчетный период значимая активность по данному направлению не выявлена."

        normalized = narrative.lower()
        found = [phrase for phrase in self.FORBIDDEN_MONTHLY_BOILERPLATE if phrase in normalized]
        if found:
            raise RuntimeError(
                "AI вернул служебные формулировки вместо готового текста отчета: " + ", ".join(found)
            )

        blocks = []
        if heading and not narrative.lower().startswith(heading.lower()):
            blocks.append(heading)
        blocks.append(narrative)

        unavailable_links = self._unique_strings(summary_data.get("unavailable_links", []) or [])
        missing_from_text = [link for link in unavailable_links if link not in narrative]
        if missing_from_text:
            blocks.append(
                "Документы по следующим ссылкам не удалось скачать; ссылки приведены для ручного доступа:\n"
                + "\n".join(missing_from_text)
            )

        return "\n\n".join(self._clean_report_block(block) for block in blocks if str(block).strip())

    def _replace_cell_paragraphs(self, cell, text: str) -> None:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(text or ""))]
        paragraphs = [part for part in paragraphs if part] or [""]
        cell.text = paragraphs[0]
        for part in paragraphs[1:]:
            cell.add_paragraph(part)

    def _format_report_date_range(self, value) -> str:
        text = self._as_text(value).strip()
        if not text or text == "Н/Д":
            return ""
        match = re.fullmatch(r"(\d{2}\.\d{2}\.\d{4})\s*[-–—]\s*(\d{2}\.\d{2}\.\d{4})", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
        return text

    def _clean_report_block(self, value: str) -> str:
        lines = []
        for raw_line in str(value or "").replace("\r", "").splitlines():
            line = raw_line.strip()
            line = re.sub(r"^#{1,6}\s*", "", line)
            line = re.sub(r"^[-*•]\s+", "", line)
            lines.append(line)
        return "\n".join(lines).strip()

    def _unique_strings(self, values) -> List[str]:
        if isinstance(values, str):
            values = [values]
        seen = set()
        unique = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return unique

    def generate_custom_report(self, analysis: Dict, output_path: Path, report_month: str = None) -> Path:
        """Generate a free-form analysis/report document."""
        self.logger.info(f"Generating custom analysis report: {output_path}")

        doc = Document()
        style = doc.styles['Normal']
        font = style.font
        font.name = self.font
        font.size = Pt(self.font_size)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(analysis.get("title") or "Пользовательский анализ")
        run.bold = True
        run.font.size = Pt(18)
        run.font.color.rgb = RGBColor(68, 114, 196)

        if report_month:
            subtitle = doc.add_paragraph()
            subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
            subtitle.add_run(report_month).font.size = Pt(12)

        doc.add_paragraph()
        self._add_plain_text(doc, analysis.get("analysis", ""))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path))
        self.logger.info(f"✓ Custom report saved: {output_path}")
        return output_path
    
    def _add_header(self, doc, report_month: str = None):
        """Add report header"""
        
        # Title
        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(self.TRANSLATIONS_RU['title'])
        run.bold = True
        run.font.size = Pt(18)
        run.font.color.rgb = RGBColor(68, 114, 196)
        
        # Subtitle (month/year)
        if not report_month:
            now = datetime.now()
            month_ru = self.MONTHS_RU[now.month].capitalize()
            report_month = f"{month_ru} {now.year}"
        
        subtitle = doc.add_paragraph()
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = subtitle.add_run(report_month)
        run.font.size = Pt(14)
        
        # Generation date
        now = datetime.now()
        date_ru = f"{now.day} {self.MONTHS_RU[now.month]} {now.year} г."
        
        date_para = doc.add_paragraph()
        date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = date_para.add_run(f"{self.TRANSLATIONS_RU['generated']}: {date_ru}")
        run.font.size = Pt(10)
        run.italic = True
        
        # Add spacing
        doc.add_paragraph()
    
    def _add_monthly_directions_table(self, doc, summaries: Dict):
        """
        Add monthly report directions in investor-style table:
        col1 = № (1 / 2 / 3 ...)
        col2 = content and result
        col3 = period/date
        """
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        table.columns[0].width = Inches(0.6)
        table.columns[1].width = Inches(7.0)
        table.columns[2].width = Inches(1.8)

        # Header row
        header_cells = table.rows[0].cells
        header_cells[0].text = "№"
        header_cells[1].text = self.TRANSLATIONS_RU['section_title']
        header_cells[2].text = "Период"
        self._format_row(header_cells, is_header=True)

        # Direction rows
        for idx, (_, summary_data) in enumerate(summaries.items(), 1):
            row_cells = table.add_row().cells
            row_cells[0].text = str(idx)
            row_cells[1].text = self._build_investor_cell_text(summary_data)
            row_cells[2].text = summary_data.get("date_range", "")
            self._format_row(row_cells, is_header=False)

    def _build_investor_cell_text(self, summary_data: Dict) -> str:
        """Build detailed monthly narrative for investor-style table."""
        if summary_data.get("message_count", 0) == 0:
            return (
                f"{summary_data.get('category_name', '')}\n\n"
                "Активность по направлению за отчетный период не выявлена."
            ).strip()

        blocks = []
        category_name = (summary_data.get("category_name") or "").strip()
        if category_name:
            blocks.append(category_name)

        overview = self._as_text(summary_data.get("overview") or summary_data.get("context"))
        if overview:
            blocks.append(overview)

        actions = summary_data.get("actions", []) or []
        if actions:
            blocks.append("Ключевые действия:\n" + self._numbered_lines(actions, limit=10))

        result = self._as_text(summary_data.get("result"))
        if result:
            blocks.append(f"Результат / статус: {result}")

        parties = self._as_text(summary_data.get("parties"))
        if parties:
            blocks.append(f"Стороны / контрагенты: {parties}")

        remarks = self._as_text(summary_data.get("remarks"))
        if remarks:
            blocks.append(f"Замечания / риски: {remarks}")

        recommendations = self._as_text(summary_data.get("recommendations"))
        if recommendations:
            blocks.append(f"Рекомендации / следующие шаги: {recommendations}")

        thread_items = summary_data.get("thread_items", []) or []
        if thread_items:
            blocks.append("Существенные цепочки:\n" + self._thread_item_lines(thread_items, limit=12))

        return "\n\n".join(block for block in blocks if block).strip()

    def _as_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "; ".join(str(item).strip() for item in value if str(item).strip())
        if isinstance(value, dict):
            return "; ".join(
                f"{key}: {item}"
                for key, item in value.items()
                if str(item).strip()
            )
        return str(value).strip()

    def _numbered_lines(self, items: List[str], limit: int = 10) -> str:
        lines = []
        for idx, item in enumerate(items[:limit], 1):
            text = str(item).strip()
            if not text:
                continue
            text = re.sub(r"^\d+[\).\s-]+", "", text)
            lines.append(f"{idx}. {text}")
        return "\n".join(lines)

    def _thread_item_lines(self, items: List[Dict], limit: int = 12) -> str:
        lines = []
        for idx, item in enumerate(items[:limit], 1):
            subject = str(item.get("subject") or "Без темы").strip()
            date_range = str(item.get("date_range") or "").strip()
            summary = str(item.get("summary") or "").strip()
            status = str(item.get("status") or "").strip()
            suffix = []
            if date_range:
                suffix.append(date_range)
            if status:
                suffix.append(status)
            meta = f" ({'; '.join(suffix)})" if suffix else ""
            if summary:
                lines.append(f"{idx}. {subject}{meta}: {summary}")
            else:
                lines.append(f"{idx}. {subject}{meta}")
        return "\n".join(lines)

    def _format_row(self, cells, is_header: bool):
        """Apply alignment/font to row cells."""
        for idx, cell in enumerate(cells):
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            for paragraph in cell.paragraphs:
                if idx == 0:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif idx == 2:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                else:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    run.font.name = self.font
                    run.font.size = Pt(self.font_size)
                    if is_header:
                        run.bold = True
    
    def _add_statistics(self, doc, summaries: Dict):
        """Add report statistics"""
        
        doc.add_page_break()
        
        total_messages = sum(s['message_count'] for s in summaries.values())
        total_attachments = sum(s['attachment_count'] for s in summaries.values())
        
        heading = doc.add_paragraph()
        heading.add_run(self.TRANSLATIONS_RU['statistics']).bold = True

        doc.add_paragraph(f"• {self.TRANSLATIONS_RU['total_categories']}: {len(summaries)}")
        doc.add_paragraph(f"• {self.TRANSLATIONS_RU['total_messages']}: {total_messages}")
        doc.add_paragraph(f"• {self.TRANSLATIONS_RU['total_attachments']}: {total_attachments}")

    def _add_plain_text(self, doc, text: str):
        """Add plain/markdown-like text as readable Word paragraphs."""
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                doc.add_paragraph()
                continue
            paragraph = doc.add_paragraph()
            if line.startswith("#"):
                line = line.lstrip("#").strip()
                run = paragraph.add_run(line)
                run.bold = True
                run.font.size = Pt(14)
            else:
                paragraph.add_run(line)


if __name__ == "__main__":
    print("✓ Word generator module loaded successfully")

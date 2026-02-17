"""
Word Document Generator
Creates formal monthly reports following the consultant/operator section template
"""

import logging
from pathlib import Path
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from typing import Dict, List


class WordReportGenerator:
    """Generate Word document reports in formal structure"""
    
    # Russian translations
    TRANSLATIONS_RU = {
        'title': 'Ежемесячный отчет',
        'section_title': '4. Работа с консультантами и операторами',
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
        """Generate structured Word document report"""
        self.logger.info(f"Generating structured report: {output_path}")
        
        doc = Document()
        
        # Set default font
        style = doc.styles['Normal']
        font = style.font
        font.name = self.font
        font.size = Pt(self.font_size)
        
        # Add header
        self._add_header(doc, report_month)
        
        # Add section 4 with subsections in investor-style table
        self._add_section_4_table(doc, summaries)
        
        # Add statistics
        self._add_statistics(doc, summaries)
        
        # Save document
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path))
        
        self.logger.info(f"✓ Report saved: {output_path}")
        
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
    
    def _add_section_4_table(self, doc, summaries: Dict):
        """
        Add section in investor-style table:
        col1 = № (4 / 4.1 / 4.2 ...)
        col2 = content and result
        col3 = period/date
        """
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        table.columns[0].width = Inches(0.6)
        table.columns[1].width = Inches(7.0)
        table.columns[2].width = Inches(1.8)

        # Row "4"
        header_cells = table.rows[0].cells
        header_cells[0].text = "4"
        header_cells[1].text = "Работа с консультантами и операторами в рамках реализации проекта."
        header_cells[2].text = ""
        self._format_row(header_cells, is_header=True)

        # Rows "4.1", "4.2", ...
        for idx, (_, summary_data) in enumerate(summaries.items(), 1):
            row_cells = table.add_row().cells
            row_cells[0].text = f"4.{idx}"
            row_cells[1].text = self._build_investor_cell_text(summary_data)
            row_cells[2].text = summary_data.get("date_range", "")
            self._format_row(row_cells, is_header=False)

    def _build_investor_cell_text(self, summary_data: Dict) -> str:
        """Build concise narrative like in investor sample."""
        actions = summary_data.get("actions", []) or []
        actions_text = " ".join(a.strip() for a in actions if a and a.strip())
        if not actions_text:
            actions_text = "Проведена рабочая переписка по профильному вопросу."

        result = (summary_data.get("result") or "").strip()
        if not result:
            result = "Статус уточняется."

        # Keep text concise for table layout.
        actions_text = actions_text[:900].rstrip()
        result = result[:300].rstrip()

        return f"{actions_text}\n\nРезультат работ: {result}"

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


if __name__ == "__main__":
    print("✓ Word generator module loaded successfully")

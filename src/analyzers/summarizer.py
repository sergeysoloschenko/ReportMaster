"""
Thread Summarizer
Generates structured AI summaries for email threads following formal report template
"""

import logging
from typing import List, Dict
from src.analyzers.categorizer import ThreadCategory
from src.analyzers.monthly_directions import MONTHLY_DIRECTIONS
from src.utils.api_client import ClaudeAPIClient
from src.parsers.content_cleaner import ContentCleaner


class Summarizer:
    """Generate structured summaries for email threads"""
    
    def __init__(self, config: dict, api_client: ClaudeAPIClient):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.api_client = api_client
        self.content_cleaner = ContentCleaner(config)
        
        sum_config = config.get('summarization', {})
        self.max_length = sum_config.get('max_length', 300)
        self.include_participants = sum_config.get('include_participants', True)
        self.include_dates = sum_config.get('include_dates', True)
    
    def summarize_categories(self, categories: List[ThreadCategory]) -> dict:
        """
        Generate structured summaries for all categories
        
        Args:
            categories: List of ThreadCategory objects
        
        Returns:
            Dict mapping category_id to structured summary data
        """
        self.logger.info(f"Generating structured summaries for {len(categories)} categories...")
        
        summaries = {}
        
        for category in categories:
            self.logger.info(f"  Summarizing: {category.name}")
            
            summary_data = self._summarize_category(category)
            summaries[category.category_id] = summary_data
        
        self.logger.info("✓ All summaries generated")
        
        return summaries

    def summarize_monthly_categories_from_insights(self, categories: List[ThreadCategory]) -> dict:
        """Generate monthly direction summaries from early LLM thread insight cards."""
        self.logger.info("Generating monthly summaries from thread insights for %s categories...", len(categories))
        summaries = {}

        for category in categories:
            insights = getattr(category, "insights", []) or []
            direction = next(
                (
                    {
                        "direction_id": item.direction_id,
                        "section_number": item.section_number,
                        "name": item.name,
                        "report_heading": item.report_heading,
                        "description": item.description,
                        "writing_guidance": item.writing_guidance,
                    }
                    for item in MONTHLY_DIRECTIONS
                    if item.direction_id == category.category_id
                ),
                {
                    "direction_id": category.category_id,
                    "section_number": "",
                    "name": category.name,
                    "report_heading": category.name,
                    "description": category.description,
                    "writing_guidance": "",
                },
            )
            date_range = self._category_date_range(category)
            insight_payloads = [self._insight_payload(insight) for insight in insights]
            summary = self.api_client.summarize_direction_insights(direction, insight_payloads, date_range)
            summary.update(
                {
                    "category_name": category.name,
                    "date_range": date_range if insights else "Н/Д",
                    "participants": self._category_participants(category),
                    "message_count": category.total_messages,
                    "attachment_count": category.total_attachments,
                    "insight_count": len(insights),
                    "section_number": direction.get("section_number", ""),
                    "report_heading": direction.get("report_heading", category.name),
                }
            )
            summaries[category.category_id] = summary

        return summaries
    
    def _summarize_category(self, category: ThreadCategory) -> dict:
        """Generate structured summary for a single category"""
        if category.total_messages == 0:
            return {
                'category_name': category.name,
                'date_range': 'Н/Д',
                'participants': [],
                'message_count': 0,
                'attachment_count': 0,
                'context': category.description,
                'actions': [],
                'result': 'Активность за период не выявлена.',
                'parties': '',
                'remarks': '',
                'recommendations': ''
            }
        
        # Collect all messages from threads in this category
        all_messages = []
        all_participants = set()
        dates = []
        
        for thread in category.threads:
            for msg in thread.messages:
                # Clean message content
                source_text = getattr(msg, "analysis_body", None) or msg.body
                cleaned = self.content_cleaner.extract_main_content(source_text)
                if cleaned:
                    all_messages.append(cleaned)
                
                # Collect participants
                all_participants.add(msg.sender)
                all_participants.update(msg.recipients)
                
                # Collect dates
                if msg.date:
                    dates.append(msg.date)
        
        # Format date range
        date_range = "Н/Д"
        if dates:
            dates.sort()
            start = dates[0].strftime('%d.%m.%Y')
            end = dates[-1].strftime('%d.%m.%Y')
            date_range = f"{start}–{end}" if start != end else start
        
        # Generate structured AI summary
        if self.api_client.client and all_messages:
            structured_summary = self.api_client.summarize_thread(
                messages=all_messages,
                participants=list(all_participants),
                date_range=date_range,
                category=category.name,
                context=category.description
            )
        else:
            # Fallback structure
            structured_summary = {
                'context': category.description,
                'actions': ['Переписка по данному вопросу'],
                'result': 'В процессе',
                'parties': ', '.join(list(all_participants)[:5]),
                'remarks': '',
                'recommendations': ''
            }
        
        return {
            'category_name': category.name,
            'date_range': date_range,
            'participants': list(all_participants)[:10],
            'message_count': category.total_messages,
            'attachment_count': category.total_attachments,
            # Structured fields
            'context': structured_summary.get('context', category.description),
            'actions': structured_summary.get('actions', []),
            'result': structured_summary.get('result', ''),
            'parties': structured_summary.get('parties', ', '.join(list(all_participants)[:5])),
            'remarks': structured_summary.get('remarks', ''),
            'recommendations': structured_summary.get('recommendations', '')
        }

    def _insight_payload(self, insight) -> Dict:
        return {
            "thread_id": insight.thread_id,
            "thread_hash": insight.thread_hash,
            "subject": insight.subject,
            "direction_id": insight.direction_id,
            "direction_name": insight.direction_name,
            "summary": insight.summary,
            "actions": insight.actions,
            "decisions": insight.decisions,
            "open_questions": insight.open_questions,
            "risks": insight.risks,
            "next_steps": insight.next_steps,
            "documents": insight.documents,
            "unavailable_links": insight.unavailable_links,
            "parties": insight.parties,
            "date_range": insight.date_range,
            "message_count": insight.message_count,
            "attachment_count": insight.attachment_count,
            "confidence": insight.confidence,
        }

    def _category_date_range(self, category: ThreadCategory) -> str:
        dates = []
        for thread in category.threads:
            for msg in thread.messages:
                if msg.date:
                    dates.append(msg.date)
        if not dates:
            return "Н/Д"
        dates.sort()
        start = dates[0].strftime('%d.%m.%Y')
        end = dates[-1].strftime('%d.%m.%Y')
        return f"{start}-{end}" if start != end else start

    def _category_participants(self, category: ThreadCategory) -> List[str]:
        participants = set()
        for insight in getattr(category, "insights", []) or []:
            participants.update(insight.parties)
        if participants:
            return sorted(participants)[:10]

        for thread in category.threads:
            participants.update(thread.participants)
        return sorted(participants)[:10]


if __name__ == "__main__":
    print("✓ Summarizer module loaded successfully")

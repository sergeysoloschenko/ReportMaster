"""
Thread Summarizer
Generates structured AI summaries for email threads following formal report template
"""

import logging
from typing import List, Dict
from src.analyzers.categorizer import ThreadCategory
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
    
    def _summarize_category(self, category: ThreadCategory) -> dict:
        """Generate structured summary for a single category"""
        
        # Collect all messages from threads in this category
        all_messages = []
        all_participants = set()
        dates = []
        
        for thread in category.threads:
            for msg in thread.messages:
                # Clean message content
                cleaned = self.content_cleaner.extract_main_content(msg.body)
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


if __name__ == "__main__":
    print("✓ Summarizer module loaded successfully")

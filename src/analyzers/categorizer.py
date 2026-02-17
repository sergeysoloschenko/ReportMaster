"""
Email Thread Categorizer
Uses AI and algorithms to categorize email threads
"""

import logging
import re
from typing import List, Dict
from collections import Counter
from src.parsers.thread_builder import EmailThread
from src.utils.api_client import ClaudeAPIClient


class ThreadCategory:
    """Represents a category of email threads"""
    
    def __init__(self, category_id: str, name: str, description: str = ""):
        self.category_id = category_id
        self.name = name
        self.description = description
        self.threads = []
    
    def add_thread(self, thread: EmailThread):
        """Add thread to this category"""
        self.threads.append(thread)
    
    @property
    def thread_count(self):
        return len(self.threads)
    
    @property
    def total_messages(self):
        return sum(t.message_count for t in self.threads)
    
    @property
    def total_attachments(self):
        return sum(t.total_attachments for t in self.threads)
    
    def __repr__(self):
        return f"ThreadCategory(id={self.category_id}, name='{self.name}', threads={self.thread_count})"


class Categorizer:
    """Categorize email threads"""
    
    def __init__(self, config: dict, api_client: ClaudeAPIClient):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.api_client = api_client
        
        cat_config = config.get('categorization', {})
        self.max_categories = cat_config.get('clustering', {}).get('max_categories', 15)
        self.ai_enabled = cat_config.get('ai_labeling', {}).get('enabled', True)
    
    def categorize_threads(self, threads: List[EmailThread]) -> List[ThreadCategory]:
        """
        Categorize email threads
        
        Args:
            threads: List of EmailThread objects
        
        Returns:
            List of ThreadCategory objects
        """
        self.logger.info(f"Categorizing {len(threads)} threads...")
        
        if not threads:
            return []
        
        categories = []
        categories_by_name = {}
        category_counter = 1
        
        for thread in threads:
            # Extract keywords from thread
            keywords = self._extract_keywords(thread)
            
            # Get sample content
            sample_content = self._get_sample_content(thread)
            
            # Use AI to categorize if enabled
            if self.ai_enabled and self.api_client.client:
                result = self.api_client.categorize_thread(
                    subject=thread.subject,
                    keywords=keywords,
                    sample_content=sample_content
                )
                
                category_name = result['category']
                category_desc = result['description']
            else:
                # Fallback: use subject as category
                category_name = thread.subject[:50]
                category_desc = f"Thread with {thread.message_count} messages"
            
            normalized_category_name = self._normalize_category_name(category_name)

            if normalized_category_name in categories_by_name:
                category = categories_by_name[normalized_category_name]
                category.add_thread(thread)
            else:
                category = ThreadCategory(
                    category_id=f"CAT_{category_counter:03d}",
                    name=category_name,
                    description=category_desc
                )
                category.add_thread(thread)
                categories.append(category)
                categories_by_name[normalized_category_name] = category
                category_counter += 1
            
            self.logger.info(f"  Thread '{thread.subject[:40]}...' -> Category: {category_name}")
        
        self.logger.info(f"Created {len(categories)} categories")
        
        return categories
    
    def _extract_keywords(self, thread: EmailThread, top_n: int = 10) -> List[str]:
        """Extract keywords from thread messages"""
        # Combine all message bodies
        all_text = " ".join([msg.body for msg in thread.messages if msg.body])
        
        # Simple keyword extraction - split and count
        words = re.findall(r"[a-zA-Zа-яА-Я0-9]{3,}", all_text.lower())
        
        # Filter out short words and common words
        stop_words = {
            'the', 'is', 'at', 'which', 'on', 'and', 'a', 'an', 'as', 'to', 'for', 'of', 'in',
            'что', 'это', 'как', 'для', 'или', 'при', 'без', 'после', 'письмо'
        }
        filtered_words = [w for w in words if len(w) > 3 and w not in stop_words]
        
        # Count frequencies
        word_counts = Counter(filtered_words)
        
        # Get top keywords
        keywords = [word for word, count in word_counts.most_common(top_n)]
        
        return keywords
    
    def _get_sample_content(self, thread: EmailThread, max_length: int = 500) -> str:
        """Get sample content from thread for AI analysis"""
        if not thread.messages:
            return ""
        
        # Get first message body
        first_msg = thread.messages[0]
        content = first_msg.body if first_msg.body else ""
        
        # Truncate if too long
        if len(content) > max_length:
            content = content[:max_length] + "..."
        
        return content

    def _normalize_category_name(self, category_name: str) -> str:
        """Normalize category name for deduplication."""
        normalized = " ".join((category_name or "Без категории").lower().split())
        return normalized[:120]


if __name__ == "__main__":
    print("✓ Categorizer module loaded successfully")

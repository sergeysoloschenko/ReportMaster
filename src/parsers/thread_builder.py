"""
Thread Builder - Reconstruct email conversation threads
Groups related emails based on subject, participants, and timing
"""

import re
import logging
from typing import List, Dict, Set
from datetime import timedelta
from src.parsers.msg_parser import EmailMessage


class EmailThread:
    """Represents a conversation thread"""
    
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.messages = []
        self.subject = ""
        self.participants = set()
        self.start_date = None
        self.end_date = None
        self.has_attachments = False
        self.total_attachments = 0
    
    def add_message(self, message: EmailMessage):
        """Add a message to this thread"""
        self.messages.append(message)
        self._update_metadata()
    
    def _update_metadata(self):
        """Update thread metadata based on messages"""
        if not self.messages:
            return
        
        # Sort by date
        self.messages.sort(key=lambda m: m.date if m.date else datetime.min)
        
        # Update subject (use first message subject)
        self.subject = self.messages[0].subject
        
        # Collect all participants
        self.participants = set()
        for msg in self.messages:
            self.participants.add(msg.sender)
            self.participants.update(msg.recipients)
            self.participants.update(msg.cc)
        
        # Update dates
        dates = [m.date for m in self.messages if m.date]
        if dates:
            self.start_date = min(dates)
            self.end_date = max(dates)
        
        # Update attachment info
        self.has_attachments = any(m.has_attachments for m in self.messages)
        self.total_attachments = sum(m.attachment_count for m in self.messages)
    
    @property
    def message_count(self):
        """Return number of messages in thread"""
        return len(self.messages)
    
    def __repr__(self):
        return f"EmailThread(id={self.thread_id}, messages={self.message_count}, subject='{self.subject[:50]}...')"


class ThreadBuilder:
    """Build conversation threads from email messages"""
    
    def __init__(self, config: dict = None):
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        
        # Get settings from config
        thread_config = self.config.get('email', {}).get('thread_grouping', {})
        self.similarity_threshold = thread_config.get('similarity_threshold', 0.7)
        self.max_gap_days = thread_config.get('max_gap_days', 7)
    
    def build_threads(self, messages: List[EmailMessage]) -> List[EmailThread]:
        """
        Build conversation threads from messages
        
        Args:
            messages: List of EmailMessage objects
        
        Returns:
            List of EmailThread objects
        """
        self.logger.info(f"Building threads from {len(messages)} messages...")
        
        if not messages:
            return []
        
        # Group messages by normalized subject
        subject_groups = self._group_by_subject(messages)
        
        # Create threads
        threads = []
        thread_counter = 1
        
        for subject_key, msgs in subject_groups.items():
            # Split by participant overlap and time gaps
            participant_groups = self._split_by_participants(msgs)
            sub_threads = []
            for participant_group in participant_groups:
                sub_threads.extend(self._split_by_time_gap(participant_group, max_gap_days=self.max_gap_days))
            
            for sub_msgs in sub_threads:
                thread = EmailThread(f"THREAD_{thread_counter:03d}")
                for msg in sub_msgs:
                    thread.add_message(msg)
                threads.append(thread)
                thread_counter += 1
        
        self.logger.info(f"Created {len(threads)} threads")
        
        return threads
    
    def _group_by_subject(self, messages: List[EmailMessage]) -> Dict[str, List[EmailMessage]]:
        """Group messages by normalized subject"""
        groups = {}
        
        for msg in messages:
            normalized_subject = self._normalize_subject(msg.subject)
            
            if normalized_subject not in groups:
                groups[normalized_subject] = []
            
            groups[normalized_subject].append(msg)
        
        return groups
    
    def _normalize_subject(self, subject: str) -> str:
        """
        Normalize email subject for comparison
        Remove RE:, FW:, etc. and extra whitespace
        """
        if not subject:
            return ""
        
        # Convert to lowercase
        subject = subject.lower()
        
        # Remove common prefixes
        prefixes = [r'^re:', r'^fw:', r'^fwd:', r'^aw:', r'^\[.*?\]']
        for prefix in prefixes:
            subject = re.sub(prefix, '', subject, flags=re.IGNORECASE)
        
        # Remove extra whitespace
        subject = ' '.join(subject.split())
        
        return subject.strip()
    
    def _split_by_time_gap(self, messages: List[EmailMessage], max_gap_days: int = 7) -> List[List[EmailMessage]]:
        """
        Split messages into sub-threads if there are large time gaps
        
        Args:
            messages: List of messages with same subject
            max_gap_days: Maximum days between messages in same thread
        
        Returns:
            List of message lists (sub-threads)
        """
        if len(messages) <= 1:
            return [messages]
        
        # Sort by date
        sorted_messages = sorted(messages, key=lambda m: m.date if m.date else datetime.min)
        
        # Split if time gap is too large
        sub_threads = []
        current_thread = [sorted_messages[0]]
        
        for i in range(1, len(sorted_messages)):
            current_msg = sorted_messages[i]
            previous_msg = sorted_messages[i-1]
            
            # Check time gap
            if current_msg.date and previous_msg.date:
                time_gap = current_msg.date - previous_msg.date
                
                if time_gap > timedelta(days=max_gap_days):
                    # Start new sub-thread
                    sub_threads.append(current_thread)
                    current_thread = [current_msg]
                else:
                    current_thread.append(current_msg)
            else:
                current_thread.append(current_msg)
        
        # Add last sub-thread
        if current_thread:
            sub_threads.append(current_thread)
        
        return sub_threads if sub_threads else [messages]

    def _split_by_participants(self, messages: List[EmailMessage]) -> List[List[EmailMessage]]:
        """
        Split by participant overlap to reduce false merges when subject is generic.
        """
        if len(messages) <= 1:
            return [messages]

        groups: List[List[EmailMessage]] = []
        group_participants: List[Set[str]] = []

        for msg in messages:
            msg_participants = {msg.sender, *msg.recipients, *msg.cc}
            matched = False
            for idx, participants in enumerate(group_participants):
                if not participants:
                    continue
                overlap = len(msg_participants & participants)
                ratio = overlap / max(len(msg_participants), 1)
                if ratio >= self.similarity_threshold:
                    groups[idx].append(msg)
                    group_participants[idx].update(msg_participants)
                    matched = True
                    break

            if not matched:
                groups.append([msg])
                group_participants.append(set(msg_participants))

        return groups


# Import datetime for thread builder
from datetime import datetime


if __name__ == "__main__":
    # Test thread building
    print("Thread builder module loaded successfully!")

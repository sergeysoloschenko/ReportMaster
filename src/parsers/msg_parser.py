"""
Outlook MSG file parser
Extracts email content, metadata, and attachments
"""

import extract_msg
from pathlib import Path
from datetime import datetime
import logging
from typing import Dict, List, Optional
import hashlib
import struct
import re

from src.processors.deduplicator import hash_text
from src.processors.document_extractor import DocumentExtractor


class EmailMessage:
    """Represents a parsed email message"""
    
    def __init__(self, msg_file: Path, document_extractor: Optional[DocumentExtractor] = None):
        self.logger = logging.getLogger(__name__)
        self.file_path = msg_file
        self.msg_id = self._generate_msg_id(msg_file)
        self.document_extractor = document_extractor or DocumentExtractor()
        
        # Metadata
        self.subject = ""
        self.sender = ""
        self.recipients = []
        self.cc = []
        self.date = None
        self.message_id = ""
        self.in_reply_to = ""
        self.references = []
        
        # Content
        self.body = ""
        self.html_body = ""
        self.analysis_body = ""
        self.normalized_body_hash = ""
        
        # Attachments
        self.attachments = []
        self.has_attachments = False
        self.extracted_attachment_count = 0
        
        # Parse the message
        self._parse()
    
    @property
    def attachment_count(self):
        """Return number of attachments"""
        return len(self.attachments)
    
    def _generate_msg_id(self, msg_file: Path) -> str:
        """Generate unique ID for message"""
        return hashlib.md5(str(msg_file).encode()).hexdigest()[:12]
    
    def _parse(self):
        """Parse the MSG file"""
        try:
            msg = extract_msg.Message(str(self.file_path))
            
            # Extract metadata
            self.subject = msg.subject or "(No Subject)"
            self.sender = msg.sender or "Unknown"
            self.recipients = self._parse_recipients(msg.to)
            self.cc = self._parse_recipients(msg.cc)
            
            # Extract date using multiple methods
            self.date = self._extract_date_robust(msg)
            
            self.message_id = getattr(msg, 'messageId', '')
            
            # Extract body content
            self.body = msg.body or ""
            self.html_body = msg.htmlBody or ""
            
            # Extract attachments
            self.attachments = self._extract_attachments(msg)
            self.has_attachments = len(self.attachments) > 0
            self.extracted_attachment_count = sum(1 for att in self.attachments if att.get("extracted_text"))
            self.normalized_body_hash = hash_text(self.body or self.html_body or "")
            self.analysis_body = self._build_analysis_body()
            
            msg.close()
            
            self.logger.debug(f"Parsed: {self.subject[:40]} | Date: {self.date}")
            
        except Exception as e:
            self.logger.error(f"Error parsing {self.file_path}: {e}")
            raise
    
    def _extract_date_robust(self, msg) -> Optional[datetime]:
        """Extract date using multiple methods"""
        
        # Method 1: Try standard properties
        date_properties = ['date', 'parsedDate', 'receivedTime', 'clientSubmitTime', 'creationTime']
        
        for prop in date_properties:
            if hasattr(msg, prop):
                value = getattr(msg, prop)
                if value:
                    try:
                        if isinstance(value, datetime):
                            self.logger.debug(f"Date from {prop}: {value}")
                            return value
                        elif isinstance(value, str):
                            from dateutil import parser as date_parser
                            parsed = date_parser.parse(value)
                            self.logger.debug(f"Date from {prop} (parsed): {parsed}")
                            return parsed
                    except Exception as e:
                        self.logger.debug(f"Failed to parse {prop}: {e}")
                        continue
        
        # Method 2: Try accessing raw properties
        try:
            # PR_CLIENT_SUBMIT_TIME = 0x0039
            # PR_MESSAGE_DELIVERY_TIME = 0x0E06
            # PR_CREATION_TIME = 0x3007
            
            prop_ids = [
                '0x00390040',  # PR_CLIENT_SUBMIT_TIME
                '0x0E060040',  # PR_MESSAGE_DELIVERY_TIME
                '0x30070040',  # PR_CREATION_TIME
            ]
            
            for prop_id in prop_ids:
                try:
                    if hasattr(msg, '_getTypedData'):
                        value = msg._getTypedData(prop_id)
                        if value and isinstance(value, datetime):
                            self.logger.debug(f"Date from property {prop_id}: {value}")
                            return value
                except:
                    continue
        except Exception as e:
            self.logger.debug(f"Raw property access failed: {e}")
        
        # Method 3: Try msg.header for received date
        try:
            if hasattr(msg, 'header') and msg.header:
                header = msg.header
                # Look for Date: header
                for line in header.split('\n'):
                    if line.lower().startswith('date:'):
                        date_str = line.split(':', 1)[1].strip()
                        from dateutil import parser as date_parser
                        parsed = date_parser.parse(date_str)
                        self.logger.debug(f"Date from header: {parsed}")
                        return parsed
        except Exception as e:
            self.logger.debug(f"Header parsing failed: {e}")
        
        # Method 4: File modification time as last resort
        try:
            file_mtime = self.file_path.stat().st_mtime
            file_date = datetime.fromtimestamp(file_mtime)
            self.logger.info(f"Using file modification time for {self.file_path.name}: {file_date}")
            return file_date
        except:
            pass
        
        self.logger.warning(f"Could not extract date from {self.file_path.name}")
        return None
    
    def _parse_recipients(self, recipients_str: Optional[str]) -> List[str]:
        """Parse recipient string into list"""
        if not recipients_str:
            return []
        
        recipients = [r.strip() for r in recipients_str.replace(';', ',').split(',')]
        return [r for r in recipients if r]
    
    def _extract_attachments(self, msg) -> List[Dict]:
        """Extract attachment information"""
        attachments = []
        
        try:
            for attachment in msg.attachments:
                filename = attachment.longFilename or attachment.shortFilename or 'unnamed'
                data = attachment.data if hasattr(attachment, 'data') else None
                extracted = self.document_extractor.extract_bytes(filename, data)
                att_info = {
                    'filename': filename,
                    'size': len(data) if data else 0,
                    'data': data,
                    'content_hash': extracted.content_hash,
                    'extracted_text': extracted.text,
                    'extraction_status': extracted.skipped_reason or 'ok'
                }
                attachments.append(att_info)
        except Exception as e:
            self.logger.warning(f"Error extracting attachments: {e}")
        
        return attachments

    def _build_analysis_body(self) -> str:
        """Build token-conscious text used by downstream categorization/summarization."""
        body = self.get_clean_body()
        attachment_texts = []
        seen_hashes = set()

        for attachment in self.attachments:
            text = attachment.get("extracted_text") or ""
            content_hash = attachment.get("content_hash")
            if not text or content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            attachment_texts.append(
                f"[Вложение: {attachment.get('filename', 'unnamed')}]\n{text[:4000]}"
            )

        if not attachment_texts:
            return body

        if self._should_include_attachment_text(body):
            return "\n\n".join([body, *attachment_texts]).strip()

        attachment_index = "; ".join(
            attachment.get("filename", "unnamed") for attachment in self.attachments
        )
        return "\n\n".join([body, f"[Вложения без полного текста в LLM-контексте: {attachment_index}]"]).strip()

    def _should_include_attachment_text(self, body: str) -> bool:
        if len((body or "").strip()) < 700:
            return True

        attachment_markers = [
            r"во влож",
            r"вложени",
            r"прилага",
            r"см\.\s*файл",
            r"см\.\s*влож",
            r"attached",
            r"attachment",
            r"see attached",
        ]
        text = (body or "").lower()
        return any(re.search(marker, text) for marker in attachment_markers)
    
    def get_clean_body(self) -> str:
        """Get cleaned email body text"""
        text = self.body if self.body else self.html_body
        return text
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'msg_id': self.msg_id,
            'file_path': str(self.file_path),
            'subject': self.subject,
            'sender': self.sender,
            'recipients': self.recipients,
            'cc': self.cc,
            'date': self.date.isoformat() if self.date else None,
            'message_id': self.message_id,
            'body': self.body,
            'analysis_body': self.analysis_body,
            'has_attachments': self.has_attachments,
            'attachment_count': self.attachment_count,
            'extracted_attachment_count': self.extracted_attachment_count,
            'attachment_names': [a['filename'] for a in self.attachments]
        }
    
    def __repr__(self):
        date_str = self.date.strftime('%Y-%m-%d %H:%M') if self.date else 'No date'
        return f"EmailMessage(subject='{self.subject[:50]}...', date={date_str})"


class MSGParser:
    """Parse multiple MSG files"""
    
    def __init__(self, document_extractor: Optional[DocumentExtractor] = None):
        self.logger = logging.getLogger(__name__)
        self.document_extractor = document_extractor or DocumentExtractor()
    
    def parse_files(self, msg_files: List[Path]) -> List[EmailMessage]:
        """Parse multiple MSG files"""
        messages = []
        
        self.logger.info(f"Parsing {len(msg_files)} MSG files...")
        
        for msg_file in msg_files:
            try:
                message = EmailMessage(msg_file, document_extractor=self.document_extractor)
                messages.append(message)
            except Exception as e:
                self.logger.error(f"Failed to parse {msg_file}: {e}")
                continue
        
        self.logger.info(f"Successfully parsed {len(messages)} messages")
        return messages
    
    def parse_directory(self, directory: Path) -> List[EmailMessage]:
        """Parse all MSG files in a directory"""
        msg_files = list(directory.glob("*.msg"))
        
        if not msg_files:
            self.logger.warning(f"No .msg files found in {directory}")
            return []
        
        return self.parse_files(msg_files)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    parser = MSGParser()
    test_dir = Path("data/input")
    
    if test_dir.exists():
        messages = parser.parse_directory(test_dir)
        print(f"\nParsed {len(messages)} messages")
        
        for msg in messages:
            print(f"\n{msg}")
    else:
        print(f"Test directory not found: {test_dir}")

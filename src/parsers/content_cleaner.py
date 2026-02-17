"""
Clean and normalize email content
Remove signatures, disclaimers, quoted text, etc.
"""

import re
import logging
from typing import List


class ContentCleaner:
    """Clean email content"""
    
    # Common signature patterns
    SIGNATURE_PATTERNS = [
        r'--+\s*$',
        r'_{5,}',
        r'Sent from my .*',
        r'Get Outlook for .*',
    ]
    
    # Common disclaimer patterns
    DISCLAIMER_PATTERNS = [
        r'This email.*?confidential',
        r'CONFIDENTIALITY NOTICE',
        r'disclaimer.*?email',
        r'The information contained in this',
    ]
    
    # Quote patterns
    QUOTE_PATTERNS = [
        r'^>+\s.*$',
        r'^On .* wrote:',
        r'^From:.*?Subject:.*?$',
        r'-----Original Message-----',
    ]
    
    def __init__(self, config: dict = None):
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        
        email_config = self.config.get('email', {})
        cleaning_config = email_config.get('content_cleaning', {})
        
        self.remove_signatures = cleaning_config.get('remove_signatures', True)
        self.remove_disclaimers = cleaning_config.get('remove_disclaimers', True)
        self.remove_quoted = cleaning_config.get('remove_quoted_text', True)
    
    def clean(self, text: str) -> str:
        """Clean email text"""
        if not text:
            return ""
        
        text = self._remove_html_tags(text)
        lines = text.split('\n')
        
        if self.remove_signatures:
            lines = self._remove_signatures(lines)
        
        if self.remove_disclaimers:
            lines = self._remove_disclaimers(lines)
        
        if self.remove_quoted:
            lines = self._remove_quoted_text(lines)
        
        cleaned = '\n'.join(lines)
        cleaned = self._normalize_whitespace(cleaned)
        
        return cleaned.strip()
    
    def _remove_html_tags(self, text: str) -> str:
        """Remove HTML tags"""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&amp;', '&')
        return text
    
    def _remove_signatures(self, lines: List[str]) -> List[str]:
        """Remove email signatures"""
        result = []
        signature_found = False
        
        for line in lines:
            if not signature_found:
                for pattern in self.SIGNATURE_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        signature_found = True
                        break
            
            if not signature_found:
                result.append(line)
        
        return result
    
    def _remove_disclaimers(self, lines: List[str]) -> List[str]:
        """Remove legal disclaimers"""
        result = []
        
        for line in lines:
            starts_disclaimer = any(
                re.search(pattern, line, re.IGNORECASE | re.DOTALL)
                for pattern in self.DISCLAIMER_PATTERNS
            )
            
            if starts_disclaimer:
                continue
            
            if len(line) > 500 and 'confidential' in line.lower():
                continue
            
            result.append(line)
        
        return result
    
    def _remove_quoted_text(self, lines: List[str]) -> List[str]:
        """Remove quoted/replied text"""
        result = []
        
        for line in lines:
            if line.strip().startswith('>'):
                continue
            
            if re.match(r'^On .* wrote:', line):
                break
            
            result.append(line)
        
        return result
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace"""
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    
    def extract_main_content(self, text: str) -> str:
        """Extract only the main content"""
        cleaned = self.clean(text)
        parts = re.split(r'\n(?:On .* wrote:|From:.*?Sent:)', cleaned, maxsplit=1)
        return parts[0].strip() if parts else cleaned

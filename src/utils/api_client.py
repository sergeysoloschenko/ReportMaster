"""
Claude API Client for categorization and summarization
"""

import logging
from anthropic import Anthropic
from typing import List, Dict, Optional


class ClaudeAPIClient:
    """Client for interacting with Claude API"""
    
    def __init__(self, config: dict):
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        api_key = config['api']['anthropic_api_key']
        
        if not api_key or api_key == 'not_set':
            self.logger.warning("Claude API key not set!")
            self.client = None
        else:
            self.client = Anthropic(api_key=api_key)
            self.logger.info("Claude API client initialized")
        
        self.model_categorization = config['api']['model_categorization']
        self.model_summarization = config['api']['model_summarization']
        self.max_tokens = config['api']['max_tokens']
        self.temperature = config['api']['temperature']
    
    def categorize_thread(self, subject: str, keywords: List[str], sample_content: str) -> Dict:
        """
        Generate category name and description for a thread IN RUSSIAN
        
        Args:
            subject: Email subject
            keywords: Extracted keywords
            sample_content: Sample email content
        
        Returns:
            Dict with 'category' and 'description'
        """
        if not self.client:
            return {
                'category': subject[:50],
                'description': 'Категория определена по теме переписки'
            }
        
        prompt = f"""Проанализируй эту email переписку и предоставь НА РУССКОМ ЯЗЫКЕ:
1. Краткое название категории (2-4 слова) в формате работы с консультантом или оператором
2. Краткое описание контекста (1 предложение)

Тема: {subject}
Ключевые слова: {', '.join(keywords[:10])}

Пример содержания:
{sample_content[:500]}

Ответь в точном формате:
Категория: [название категории]
Описание: [описание контекста]"""
        
        try:
            response = self.client.messages.create(
                model=self.model_categorization,
                max_tokens=200,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text
            
            # Parse response
            category = "Без категории"
            description = ""
            
            for line in content.split('\n'):
                if line.startswith('Категория:') or line.startswith('Category:'):
                    category = line.split(':', 1)[1].strip()
                elif line.startswith('Описание:') or line.startswith('Description:'):
                    description = line.split(':', 1)[1].strip()
            
            return {
                'category': category,
                'description': description
            }
            
        except Exception as e:
            self.logger.error(f"Error categorizing thread: {e}")
            if self._is_auth_error(e):
                # Stop retrying invalid credentials for every thread.
                self.client = None
            return {
                'category': subject[:50],
                'description': 'Категория определена по теме переписки'
            }
    
    def summarize_thread(self, messages: List[str], participants: List[str], date_range: str, category: str, context: str) -> Dict:
        """
        Generate structured summary for a thread following the formal report template
        
        Args:
            messages: List of message contents
            participants: List of participant names
            date_range: Date range string
            category: Category name
            context: Context description
        
        Returns:
            Dict with structured summary sections
        """
        if not self.client:
            return {
                'context': "API ключ не настроен",
                'actions': [],
                'result': "",
                'parties': "",
                'remarks': "",
                'recommendations': ""
            }
        
        # Combine messages
        combined = "\n\n---\n\n".join(messages[:5])
        
        prompt = f"""Ты — профессиональный AI-аналитик и автор ежемесячных проектных отчётов в девелопменте и гостиничном строительстве.

Создай структурированный отчёт по разделу **4. Работа с консультантами и операторами** на основе переписки.

**ВАЖНО:** Отчёт должен быть в деловом, нейтральном стиле, совершенный вид, 3-е лицо.

**Входные данные:**
- Тема: {category}
- Контекст: {context}
- Период: {date_range}
- Участники: {', '.join(participants[:5])}

Переписка:
{combined[:2500]}

Создай отчёт в следующем формате (каждый раздел должен быть заполнен):

**Контекст:** [Одно предложение — цель или фон работ]

**Действия:**
[Пронумерованный список конкретных действий: кто, что сделал, какие документы направлены]

**Результат / Статус:**
[Краткое резюме текущего статуса: согласовано / не согласовано / с комментариями / требует доработки]

**Стороны / Контрагенты:**
[Перечисли ключевых участников: архитекторы, консультанты, подрядчики, операторы]

**Замечания / Риски:**
[Фактические замечания без эмоций, если есть проблемы или риски]

**Рекомендации / Следующие шаги:**
[Конкретные рекомендации в формате: "СХ рекомендует..." или "Рекомендуется..."]

Верни результат СТРОГО в формате JSON:
{{
  "context": "...",
  "actions": ["1. ...", "2. ...", "3. ..."],
  "result": "...",
  "parties": "...",
  "remarks": "...",
  "recommendations": "..."
}}"""
        
        try:
            response = self.client.messages.create(
                model=self.model_summarization,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text.strip()
            
            # Try to parse JSON
            import json
            import re
            
            # Extract JSON from response (in case there's extra text)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                result = json.loads(json_str)
                return result
            else:
                # Fallback if JSON parsing fails
                return {
                    'context': context,
                    'actions': [content[:500]],
                    'result': "Требует уточнения",
                    'parties': ', '.join(participants[:5]),
                    'remarks': "",
                    'recommendations': ""
                }
            
        except Exception as e:
            self.logger.error(f"Error summarizing thread: {e}")
            if self._is_auth_error(e):
                self.client = None
            return {
                'context': context,
                'actions': ['Переписка обработана в базовом режиме без AI-суммаризации'],
                'result': "В процессе",
                'parties': ', '.join(participants[:5]),
                'remarks': "",
                'recommendations': "Проверить корректность API-ключа и повторить генерацию для расширенного резюме"
            }

    def _is_auth_error(self, error: Exception) -> bool:
        """Return True for authentication-related API failures."""
        text = str(error).lower()
        return (
            "authentication_error" in text
            or "invalid x-api-key" in text
            or "error code: 401" in text
        )


if __name__ == "__main__":
    from src.utils.config_loader import load_config
    
    config = load_config()
    client = ClaudeAPIClient(config)
    
    if client.client:
        print("✓ API client initialized successfully")
        print(f"  Categorization model: {client.model_categorization}")
        print(f"  Summarization model: {client.model_summarization}")
    else:
        print("✗ API client not initialized - check your API key in .env")

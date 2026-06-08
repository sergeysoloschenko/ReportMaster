"""
GigaChat API Client for categorization and summarization.
"""

import json
import logging
import re
import time
import hashlib
from typing import Dict, List, Optional
from pathlib import Path
from uuid import uuid4

import httpx


class GigaChatAPIClient:
    """
    Backward-compatible client name used by existing pipeline code.
    Internally this implementation uses GigaChat REST API.
    """

    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self, config: dict):
        self.logger = logging.getLogger(__name__)
        self.config = config

        api_cfg = config.get("api", {})
        self.auth_key = api_cfg.get("gigachat_auth_key", "not_set")
        self.scope = api_cfg.get("gigachat_scope", "GIGACHAT_API_PERS")
        self.verify_ssl = api_cfg.get("gigachat_verify_ssl", True)
        self.model_categorization = api_cfg.get("model_categorization", "GigaChat-2")
        self.model_summarization = api_cfg.get("model_summarization", "GigaChat-2-Max")
        self.max_tokens = api_cfg.get("max_tokens", 2048)
        self.temperature = api_cfg.get("temperature", 0.3)

        self._access_token: Optional[str] = None
        self._token_expires_at: int = 0
        self._usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
        cache_dir = Path(config.get("paths", {}).get("cache", "data/cache"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = cache_dir / "llm_analysis_cache.json"
        self._cache = self._load_cache()
        self.http = httpx.Client(timeout=45.0, verify=self.verify_ssl)

        if not self.auth_key or self.auth_key == "not_set":
            self.logger.warning("GigaChat authorization key not set!")
            self.client = None
        else:
            self.client = self
            self.logger.info("GigaChat API client initialized")

    def categorize_thread(self, subject: str, keywords: List[str], sample_content: str) -> Dict:
        if not self.client:
            return {
                "category": subject[:50],
                "description": "Категория определена по теме переписки",
            }

        cache_key = self._cache_key("categorize", {
            "subject": subject,
            "keywords": keywords[:10],
            "sample_content": sample_content,
            "model": self.model_categorization,
        })
        cached = self._cache_get(cache_key)
        if cached:
            return cached

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
            content = self._chat_completion(
                prompt=prompt,
                model=self.model_categorization,
                max_tokens=200,
            )

            category = "Без категории"
            description = ""

            for line in content.split("\n"):
                if line.startswith("Категория:") or line.startswith("Category:"):
                    category = line.split(":", 1)[1].strip()
                elif line.startswith("Описание:") or line.startswith("Description:"):
                    description = line.split(":", 1)[1].strip()

            result = {
                "category": category,
                "description": description,
            }
            self._cache_set(cache_key, result)
            return result

        except Exception as e:
            self.logger.error(f"Error categorizing thread: {e}")
            if self._is_auth_error(e):
                self.client = None
            return {
                "category": subject[:50],
                "description": "Категория определена по теме переписки",
            }

    def summarize_thread(self, messages: List[str], participants: List[str], date_range: str, category: str, context: str) -> Dict:
        if not self.client:
            return {
                "context": "GigaChat ключ не настроен",
                "actions": [],
                "result": "",
                "parties": "",
                "remarks": "",
                "recommendations": "",
            }

        combined = "\n\n---\n\n".join(messages[:5])
        organizations = self._extract_organizations(participants)
        organizations_text = ", ".join(organizations) if organizations else "Организации не определены"

        cache_key = self._cache_key("summarize", {
            "messages": messages[:5],
            "participants": sorted(participants)[:20],
            "date_range": date_range,
            "category": category,
            "context": context,
            "model": self.model_summarization,
            "max_tokens": self.max_tokens,
        })
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        prompt = f"""Ты — профессиональный AI-аналитик и автор ежемесячных проектных отчётов в девелопменте и гостиничном строительстве.

Создай структурированный отчёт по направлению **{category}** на основе переписки и документов.

**ВАЖНО:** Отчёт должен быть в деловом, нейтральном стиле, совершенный вид, 3-е лицо.
**КРИТИЧЕСКОЕ ПРАВИЛО:** НЕ указывай ФИО, имена и должности конкретных людей.
Во всех формулировках используй только названия организаций (по доменам email и контексту переписки).
Пример: вместо "Юдина Т.В. инициировала..." пиши "Спектрум Холдинг инициировало...".
Если персоналия встречается в тексте, замени её на соответствующую организацию.

**Входные данные:**
- Тема: {category}
- Контекст: {context}
- Период: {date_range}
- Участники (сырые данные): {', '.join(participants[:8])}
- Определённые организации: {organizations_text}

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
            content = self._chat_completion(
                prompt=prompt,
                model=self.model_summarization,
                max_tokens=self.max_tokens,
            )

            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                self._cache_set(cache_key, result)
                return result

            result = {
                "context": context,
                "actions": [content[:500]],
                "result": "Требует уточнения",
                "parties": organizations_text,
                "remarks": "",
                "recommendations": "",
            }
            self._cache_set(cache_key, result)
            return result

        except Exception as e:
            self.logger.error(f"Error summarizing thread: {e}")
            if self._is_auth_error(e):
                self.client = None
            return {
                "context": context,
                "actions": ["Переписка обработана в базовом режиме без AI-суммаризации"],
                "result": "В процессе",
                "parties": organizations_text,
                "remarks": "",
                "recommendations": "Проверить корректность GigaChat ключа и повторить генерацию",
            }

    def run_custom_analysis(self, user_prompt: str, source_texts: List[str], title: str = "Пользовательский анализ") -> Dict:
        combined = "\n\n--- SOURCE ---\n\n".join(text for text in source_texts if text.strip())
        if not combined:
            return {
                "title": title,
                "analysis": "Не найден читаемый текст для анализа.",
            }

        if not self.client:
            return {
                "title": title,
                "analysis": "GigaChat ключ не настроен. Исходники извлечены, но пользовательский анализ не выполнен.",
            }

        cache_key = self._cache_key("custom_analysis", {
            "user_prompt": user_prompt,
            "source_texts": source_texts,
            "model": self.model_summarization,
            "max_tokens": self.max_tokens,
        })
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        prompt = f"""Ты — профессиональный аналитик. Выполни задачу пользователя по предоставленным исходникам.

Правила:
- Отвечай на русском языке, если пользователь явно не попросил другой язык.
- Не выдумывай факты, которых нет в исходниках.
- Если данных недостаточно, прямо укажи, чего не хватает.
- Структурируй ответ как полноценный аналитический документ с заголовками.

Задача пользователя:
{user_prompt}

Исходники:
{combined[:12000]}"""

        try:
            content = self._chat_completion(
                prompt=prompt,
                model=self.model_summarization,
                max_tokens=self.max_tokens,
            )
            result = {
                "title": title,
                "analysis": content.strip(),
            }
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            self.logger.error("Error running custom analysis: %s", e)
            if self._is_auth_error(e):
                self.client = None
            return {
                "title": title,
                "analysis": "Не удалось выполнить пользовательский анализ через LLM. Проверьте ключ и повторите запуск.",
            }

    def _get_access_token(self) -> str:
        now = int(time.time())
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "RqUID": str(uuid4()),
            "Authorization": f"Basic {self.auth_key}",
        }
        data = {"scope": self.scope}

        response = self.http.post(self.OAUTH_URL, headers=headers, data=data)
        response.raise_for_status()

        payload = response.json()
        token = payload.get("access_token")
        expires_at = int(payload.get("expires_at", 0))
        if not token:
            raise RuntimeError("GigaChat OAuth token was not returned")

        # If expires_at wasn't provided, fall back to ~30 min.
        if expires_at <= now:
            expires_at = now + 29 * 60

        self._access_token = token
        self._token_expires_at = expires_at
        return token

    def _chat_completion(self, prompt: str, model: str, max_tokens: int) -> str:
        token = self._get_access_token()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        response = self.http.post(self.API_URL, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        self._accumulate_usage(body.get("usage") or {})

        choices = body.get("choices", [])
        if not choices:
            raise RuntimeError("GigaChat response has no choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not content:
            raise RuntimeError("GigaChat response message content is empty")
        return content

    def get_usage_stats(self) -> Dict[str, int]:
        return dict(self._usage)

    def _load_cache(self) -> Dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.logger.warning("Could not read LLM cache %s: %s", self.cache_path, exc)
            return {}

    def _cache_key(self, kind: str, payload: Dict) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"{kind}:{digest}"

    def _cache_get(self, key: str) -> Optional[Dict]:
        value = self._cache.get(key)
        if value is not None:
            self._usage["cache_hits"] += 1
            return dict(value)
        self._usage["cache_misses"] += 1
        return None

    def _cache_set(self, key: str, value: Dict) -> None:
        self._cache[key] = value
        try:
            self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.logger.warning("Could not write LLM cache %s: %s", self.cache_path, exc)

    def _accumulate_usage(self, usage: Dict) -> None:
        try:
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", 0) or 0)
        except (TypeError, ValueError):
            self.logger.warning("Could not parse token usage payload: %s", usage)
            return

        self._usage["prompt_tokens"] += max(prompt_tokens, 0)
        self._usage["completion_tokens"] += max(completion_tokens, 0)
        if total_tokens > 0:
            self._usage["total_tokens"] += total_tokens
        else:
            self._usage["total_tokens"] += max(prompt_tokens, 0) + max(completion_tokens, 0)

    def _is_auth_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return (
            "401" in text
            or "403" in text
            or "invalid_token" in text
            or "unauthorized" in text
            or "forbidden" in text
            or "basic" in text and "auth" in text
        )

    def _extract_organizations(self, participants: List[str]) -> List[str]:
        domain_aliases = {
            "spgr.ru": "Спектрум Холдинг",
            "dusit.com": "Dusit International",
            "port-gdz.com": "Порт Геленджик",
            "dyergroup.ru": "Dyer Group",
            "groupdyer.com": "Dyer Group",
            "gmail.com": "Внешний контрагент",
            "yandex.ru": "Внешний контрагент",
            "mail.ru": "Внешний контрагент",
        }

        orgs = []
        seen = set()

        for item in participants:
            emails = re.findall(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", item or "")
            for domain in emails:
                domain = domain.lower()
                org = domain_aliases.get(domain)
                if not org:
                    parts = domain.split(".")
                    org = parts[-2].upper() if len(parts) >= 2 else domain.upper()
                if org not in seen:
                    seen.add(org)
                    orgs.append(org)

        return orgs


ClaudeAPIClient = GigaChatAPIClient


if __name__ == "__main__":
    from src.utils.config_loader import load_config

    cfg = load_config()
    client = GigaChatAPIClient(cfg)
    print("Client ready:", bool(client.client))

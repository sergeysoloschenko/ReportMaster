"""
GigaChat API Client for categorization and summarization.
"""

import json
import logging
import re
import shutil
import subprocess
import threading
import time
import hashlib
from typing import Dict, List, Optional
from pathlib import Path
from uuid import uuid4

import httpx


REPORTMASTER_PROJECT_CONTEXT = """
Контекст ReportMaster:
- Автор отчета: менеджер проекта со стороны технического заказчика.
- Аудитория: заказчик и инвестор проекта.
- Проект: проектирование и строительство многофункционального комплекса "Марина Геленджик",
  включая отель, апартаменты и сопутствующие объекты.
- Результат должен быть готовым фрагментом общего договорного отчета, а не аналитической справкой.
- В итоговом тексте нужны только выполненные мероприятия, полученные результаты, существенные
  решения, замечания и незакрытые вопросы. Служебная информация о письмах и процессе анализа запрещена.
""".strip()


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

    def triage_thread_relevance(self, thread_payload: Dict, directions: List[Dict]) -> Dict:
        """Fast first-pass relevance check before deeper monthly report analysis."""
        fallback = self._fallback_thread_triage(thread_payload, directions)
        if not self.client:
            if self._strict_monthly_analysis():
                raise RuntimeError(self._llm_unavailable_message())
            return fallback

        cache_key = self._cache_key("thread_triage_v2_contract_report", {
            "thread_hash": thread_payload.get("thread_hash"),
            "subject": thread_payload.get("subject"),
            "message_count": thread_payload.get("message_count"),
            "attachment_count": thread_payload.get("attachment_count"),
            "model": getattr(self, "model_triage", self.model_categorization),
            "reasoning": getattr(self, "reasoning_triage", ""),
        })
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        directions_text = "\n".join(
            f"- {item['direction_id']}: {item['name']} — {item['description']}"
            for item in directions
        )
        source_json = json.dumps(thread_payload, ensure_ascii=False, indent=2)[:9000]

        allowed_direction_ids = "|".join(item["direction_id"] for item in directions)
        prompt = f"""{REPORTMASTER_PROJECT_CONTEXT}

Ты выполняешь быстрый первичный отбор одной email-цепочки для ежемесячного отчета.

Задача: определить, нужно ли включать цепочку в отчет, и выбрать наиболее подходящее направление.

Критерии включения:
- Включай цепочки, где есть существенные для проекта действия, документы, согласования, комментарии,
  решения, открытые вопросы, риски или следующие шаги.
- Исключай автоматические уведомления, чистую логистику встреч без содержательных решений,
  дубли, служебные сообщения, рассылки, поздравления, подписи, подтверждения получения без сути.
- Включай материал только тогда, когда его можно содержательно отнести к одной из пяти строк отчета.
- Исключай личные вопросы, корпоративные мероприятия, инструктажи, счета без проектного результата
  и общую переписку Заказчика/Инвестора, не относящуюся к предмету строк 4.1-4.5.

Направления отчета:
{directions_text}

Email-цепочка в JSON:
{source_json}

Верни СТРОГО JSON:
{{
  "include_in_report": true,
  "direction_id": "{allowed_direction_ids}",
  "relevance": "high|medium|low|none",
  "reason": "краткое объяснение решения",
  "confidence": "high|medium|low"
}}"""

        try:
            content = self._chat_completion(
                prompt=prompt,
                model=getattr(self, "model_triage", self.model_categorization),
                max_tokens=min(self.max_tokens, 900),
                task_type="triage",
            )
            result = self._json_from_content(content) or fallback
            result = self._normalize_thread_triage_result(result, fallback)
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            self.logger.error("Error triaging thread relevance: %s", e)
            if self._is_auth_error(e):
                self.client = None
            if self._strict_monthly_analysis():
                raise RuntimeError(f"Обязательная AI-аналитика недоступна: {e}") from e
            return fallback

    def analyze_thread_insight(self, thread_payload: Dict, directions: List[Dict]) -> Dict:
        """Analyze one email thread early and return a reusable structured card."""
        fallback = self._fallback_thread_insight(thread_payload, directions)
        if not self.client:
            if self._strict_monthly_analysis():
                raise RuntimeError(self._llm_unavailable_message())
            return fallback

        cache_key = self._cache_key("thread_insight_v3_contract_report", {
            "thread_hash": thread_payload.get("thread_hash"),
            "subject": thread_payload.get("subject"),
            "message_count": thread_payload.get("message_count"),
            "attachment_count": thread_payload.get("attachment_count"),
            "model": getattr(self, "model_thread_insight", self.model_summarization),
            "reasoning": getattr(self, "reasoning_thread_insight", ""),
        })
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        directions_text = "\n".join(
            f"- {item['direction_id']}: {item['name']} — {item['description']}"
            for item in directions
        )
        source_json = json.dumps(thread_payload, ensure_ascii=False, indent=2)[:12000]

        allowed_direction_ids = "|".join(item["direction_id"] for item in directions)
        prompt = f"""{REPORTMASTER_PROJECT_CONTEXT}

Ты — старший проектный аналитик. Проанализируй ОДНУ email-цепочку до формирования ежемесячного отчёта.

Задача: извлечь факты, документы, решения, открытые вопросы и выбрать направление отчёта.

Правила:
- Пиши по-русски, деловым нейтральным стилем.
- Не выдумывай факты.
- Не используй ФИО конкретных людей; замени на организации по email-доменам и контексту.
- Если письмо пересылает документ или есть вложение, явно укажи документ/вложение в documents.
- Формулируй факты как выполненную проектную работу, а не как описание переписки.
- Не пиши «обработана цепочка», «проанализирована переписка», «по карточке» и подобные служебные фразы.
- Ссылки из unavailable_links обязательно верни без изменений в одноименном поле.
- direction_id должен быть строго одним из списка.
- Если preliminary_triage присутствует, используй его как гипотезу, но исправь направление при явной ошибке.

Направления отчёта:
{directions_text}

Email-цепочка в JSON:
{source_json}

Верни СТРОГО JSON:
{{
  "direction_id": "{allowed_direction_ids}",
  "summary": "3-5 предложений о сути цепочки и ее значении для проекта",
  "actions": ["конкретное действие/направление документа/обсуждение"],
  "decisions": ["принятые или зафиксированные решения, если есть"],
  "open_questions": ["незакрытый вопрос, если есть"],
  "risks": ["риск или замечание, если есть"],
  "next_steps": ["следующий шаг, если вытекает из переписки"],
  "documents": ["название документа или вложения"],
  "unavailable_links": ["ссылка на документ, который не удалось скачать"],
  "parties": ["организация 1", "организация 2"],
  "confidence": "high|medium|low"
}}"""

        try:
            content = self._chat_completion(
                prompt=prompt,
                model=getattr(self, "model_thread_insight", self.model_summarization),
                max_tokens=min(self.max_tokens, 1800),
                task_type="thread_insight",
            )
            result = self._json_from_content(content) or fallback
            result = self._normalize_thread_insight_result(result, fallback)
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            self.logger.error("Error analyzing thread insight: %s", e)
            if self._is_auth_error(e):
                self.client = None
            if self._strict_monthly_analysis():
                raise RuntimeError(f"Обязательная AI-аналитика недоступна: {e}") from e
            return fallback

    def summarize_direction_insights(self, direction: Dict, insights: List[Dict], date_range: str) -> Dict:
        """Generate a monthly direction report from pre-analyzed thread cards."""
        if not insights:
            return {
                "category_name": direction["name"],
                "date_range": "Н/Д",
                "participants": [],
                "message_count": 0,
                "attachment_count": 0,
                "context": direction.get("description", ""),
                "narrative": "За отчетный период значимая активность по данному направлению не выявлена.",
                "overview": "Активность за период не выявлена.",
                "actions": [],
                "result": "Активность за период не выявлена.",
                "parties": "",
                "remarks": "",
                "recommendations": "",
                "thread_items": [],
                "unavailable_links": [],
            }

        fallback = self._fallback_direction_summary(direction, insights, date_range)
        if not self.client:
            if self._strict_monthly_analysis():
                raise RuntimeError(self._llm_unavailable_message())
            return fallback

        cache_key = self._cache_key("direction_summary_v4_contract_report", {
            "direction_id": direction.get("direction_id"),
            "insight_hashes": [item.get("thread_hash") for item in insights],
            "model": self.model_summarization,
            "reasoning": getattr(self, "reasoning_summarization", ""),
            "max_tokens": self.max_tokens,
        })
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        source_json = json.dumps(insights, ensure_ascii=False, indent=2)[:65000]
        prompt = f"""{REPORTMASTER_PROJECT_CONTEXT}

Ты — автор ежемесячного отчёта для заказчика и инвестора по проекту "Марина Геленджик".

На входе карточки email-цепочек, уже проанализированные LLM. Сформируй содержательный раздел отчёта по направлению.

Направление: {direction['name']}
Описание направления: {direction.get('description', '')}
Формулировка строки отчета: {direction.get('report_heading', '')}
Специальное указание: {direction.get('writing_guidance', '')}
Период: {date_range}

Правила:
- Пиши по-русски, деловым нейтральным стилем.
- Не используй ФИО конкретных людей, только организации.
- Напиши 2-6 связных абзацев, которые можно без редактирования вставить в графу
  «Наименование выполненных мероприятий. Результат работ.».
- Описывай выполненную работу и результат в совершенном виде: «направлено», «получено»,
  «согласовано», «зафиксировано», «выявлено», «инициировано».
- Объединяй связанные факты тематически и убирай повторы.
- Укажи конкретные документы, номера исходящих писем, решения, замечания, влияние на проект
  и незакрытые вопросы — только если они подтверждены карточками.
- Не перечисляй темы email и не пиши про цепочки, карточки, переписку, анализ, полноту данных,
  участников, количество сообщений/вложений или необходимость «проверки финальной редакции».
- Не добавляй отдельные служебные блоки «Контекст», «Ключевые действия», «Стороны»,
  «Существенные цепочки», «Риски», «Рекомендации».
- Не придумывай факты. Если сведений мало, изложи только подтвержденные действия без комментария
  о недостаточности исходных данных.
- Ссылки из unavailable_links не перефразируй и верни в одноименном массиве.

Карточки цепочек:
{source_json}

Верни СТРОГО JSON:
{{
  "narrative": "готовый текст строки отчета из 2-6 абзацев без заголовка строки",
  "unavailable_links": ["неизмененная ссылка на документ, который не удалось скачать"]
}}"""

        try:
            content = self._chat_completion(
                prompt=prompt,
                model=self.model_summarization,
                max_tokens=self.max_tokens,
                task_type="summarization",
            )
            result = self._json_from_content(content) or fallback
            result = self._normalize_direction_summary_result(result, fallback)
            if self._strict_monthly_analysis() and not result.get("narrative", "").strip():
                raise RuntimeError("AI не вернул готовый текст строки отчета")
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            self.logger.error("Error summarizing direction insights: %s", e)
            if self._is_auth_error(e):
                self.client = None
            if self._strict_monthly_analysis():
                raise RuntimeError(f"Обязательная AI-аналитика недоступна: {e}") from e
            return fallback

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
            "model": getattr(self, "model_custom_analysis", self.model_summarization),
            "reasoning": getattr(self, "reasoning_custom_analysis", ""),
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
                model=getattr(self, "model_custom_analysis", self.model_summarization),
                max_tokens=self.max_tokens,
                task_type="custom_analysis",
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

    def _json_from_content(self, content: str) -> Optional[Dict]:
        json_match = re.search(r"\{.*\}", content or "", re.DOTALL)
        if not json_match:
            return None
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return None

    def _normalize_thread_insight_result(self, result: Dict, fallback: Dict) -> Dict:
        normalized = dict(fallback)
        normalized.update({key: value for key, value in result.items() if value is not None})
        normalized["direction_id"] = self._normalize_direction_id(normalized.get("direction_id"))
        for key in (
            "actions",
            "decisions",
            "open_questions",
            "risks",
            "next_steps",
            "documents",
            "unavailable_links",
            "parties",
        ):
            normalized[key] = self._ensure_string_list(normalized.get(key))
        normalized["summary"] = str(normalized.get("summary") or fallback.get("summary", "")).strip()
        normalized["confidence"] = str(normalized.get("confidence") or "medium").strip()
        normalized["relevance_reason"] = str(normalized.get("relevance_reason") or fallback.get("relevance_reason", "")).strip()
        normalized["triage_confidence"] = str(normalized.get("triage_confidence") or "medium").strip()
        return normalized

    def _normalize_thread_triage_result(self, result: Dict, fallback: Dict) -> Dict:
        normalized = dict(fallback)
        normalized.update({key: value for key, value in result.items() if value is not None})
        normalized["include_in_report"] = self._ensure_bool(normalized.get("include_in_report"), default=True)
        normalized["direction_id"] = self._normalize_direction_id(normalized.get("direction_id"))
        relevance = str(normalized.get("relevance") or "medium").strip().lower()
        normalized["relevance"] = relevance if relevance in {"high", "medium", "low", "none"} else "medium"
        normalized["reason"] = str(normalized.get("reason") or normalized.get("relevance_reason") or "").strip()
        confidence = str(normalized.get("confidence") or "medium").strip().lower()
        normalized["confidence"] = confidence if confidence in {"high", "medium", "low"} else "medium"
        return normalized

    def _normalize_direction_summary_result(self, result: Dict, fallback: Dict) -> Dict:
        normalized = dict(fallback)
        normalized.update({key: value for key, value in result.items() if value is not None})
        normalized["actions"] = self._ensure_string_list(normalized.get("actions"))
        normalized["narrative"] = str(normalized.get("narrative") or "").strip()
        normalized["unavailable_links"] = self._unique_strings(
            [
                *self._ensure_string_list(fallback.get("unavailable_links")),
                *self._ensure_string_list(normalized.get("unavailable_links")),
            ]
        )
        if not isinstance(normalized.get("thread_items"), list):
            normalized["thread_items"] = fallback.get("thread_items", [])
        return normalized

    def _fallback_thread_triage(self, thread_payload: Dict, directions: List[Dict]) -> Dict:
        text = json.dumps(thread_payload, ensure_ascii=False).lower()
        direction_id = self._heuristic_direction_id(text)
        return {
            "include_in_report": True,
            "direction_id": direction_id,
            "relevance": "medium",
            "reason": "Цепочка включена консервативно: автоматический fallback не исключает потенциально важные письма.",
            "confidence": "low",
        }

    def _fallback_thread_insight(self, thread_payload: Dict, directions: List[Dict]) -> Dict:
        text = json.dumps(thread_payload, ensure_ascii=False).lower()
        direction_id = self._heuristic_direction_id(text)
        attachments = []
        unavailable_links = []
        for message in thread_payload.get("messages", []):
            for attachment in message.get("attachments", []):
                filename = attachment.get("filename")
                if filename:
                    attachments.append(filename)
            unavailable_links.extend(self._ensure_string_list(message.get("unavailable_links")))
        return {
            "direction_id": direction_id,
            "summary": "Обязательная AI-аналитика не выполнена.",
            "actions": [],
            "decisions": [],
            "open_questions": [],
            "risks": [],
            "next_steps": [],
            "documents": attachments[:10],
            "unavailable_links": self._unique_strings(unavailable_links),
            "parties": self._extract_organizations(thread_payload.get("participants", [])),
            "confidence": "low",
            "relevance_reason": "",
            "triage_confidence": "low",
        }

    def _fallback_direction_summary(self, direction: Dict, insights: List[Dict], date_range: str) -> Dict:
        actions = []
        parties = set()
        attachments = 0
        messages = 0
        thread_items = []
        unavailable_links = []
        for item in insights:
            messages += int(item.get("message_count", 0) or 0)
            attachments += int(item.get("attachment_count", 0) or 0)
            actions.extend(self._ensure_string_list(item.get("actions"))[:3])
            parties.update(self._ensure_string_list(item.get("parties")))
            unavailable_links.extend(self._ensure_string_list(item.get("unavailable_links")))
            thread_items.append({
                "subject": item.get("subject", ""),
                "date_range": item.get("date_range", ""),
                "summary": item.get("summary", ""),
                "status": "В работе",
            })
        narrative_parts = [
            str(item.get("summary") or "").strip()
            for item in insights
            if str(item.get("summary") or "").strip()
        ]
        return {
            "category_name": direction["name"],
            "date_range": date_range,
            "participants": sorted(parties)[:10],
            "message_count": messages,
            "attachment_count": attachments,
            "context": direction.get("description", ""),
            "narrative": "\n\n".join(narrative_parts),
            "overview": " ".join(item.get("summary", "") for item in insights[:6] if item.get("summary")),
            "actions": actions[:12],
            "result": "",
            "parties": ", ".join(sorted(parties)[:12]),
            "remarks": "; ".join(
                value
                for item in insights
                for value in self._ensure_string_list(item.get("risks") or item.get("open_questions"))
            )[:1200],
            "recommendations": "; ".join(
                value
                for item in insights
                for value in self._ensure_string_list(item.get("next_steps"))
            )[:1200],
            "thread_items": thread_items[:20],
            "unavailable_links": self._unique_strings(unavailable_links),
        }

    def _heuristic_direction_id(self, text: str) -> str:
        if re.search(r"архитектурн\w+ надзор|пространственн\w+ координац|реестр\w* задан", text):
            return "DIR_005"
        if "dusit" in text and re.search(r"договор|agreement|hma|term sheet|loi|финансов\w+ модел", text):
            return "DIR_001"
        if "dusit" in text:
            return "DIR_002"
        if re.search(r"dyer|groupdyer|dyergroup|даер|архитектор|architect", text):
            return "DIR_004"
        return "DIR_003"

    def _normalize_direction_id(self, value: str) -> str:
        value = str(value or "").strip()
        return value if value in {"DIR_001", "DIR_002", "DIR_003", "DIR_004", "DIR_005"} else "DIR_003"

    def _strict_monthly_analysis(self) -> bool:
        return bool(self.config.get("processing", {}).get("require_llm_for_monthly", True))

    def _llm_unavailable_message(self) -> str:
        return (
            "Обязательная AI-аналитика недоступна. Проверьте авторизацию Codex в контейнере "
            "(docker compose exec backend codex login --device-auth) и повторите формирование отчета."
        )

    def _ensure_string_list(self, value) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _unique_strings(self, values: List[str]) -> List[str]:
        seen = set()
        unique = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return unique

    def _ensure_bool(self, value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1", "да", "включить", "include"}:
                return True
            if normalized in {"false", "no", "0", "нет", "исключить", "exclude"}:
                return False
        return default

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

    def _chat_completion(self, prompt: str, model: str, max_tokens: int, task_type: str = "summarization") -> str:
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


class CodexCLIClient(GigaChatAPIClient):
    """
    Backward-compatible client used by the existing pipeline.
    Runs Codex CLI in non-interactive mode instead of calling a chat API directly.
    """

    def __init__(self, config: dict):
        self.logger = logging.getLogger(__name__)
        self.config = config

        api_cfg = config.get("api", {})
        self.command = api_cfg.get("codex_command", "codex")
        self.model_triage = api_cfg.get("model_triage", "")
        self.model_thread_insight = api_cfg.get("model_thread_insight", "")
        self.model_summarization = api_cfg.get("model_summarization", "")
        self.model_custom_analysis = api_cfg.get("model_custom_analysis", self.model_summarization)
        self.model_categorization = api_cfg.get("model_categorization", self.model_triage)
        self.reasoning_by_task = {
            "triage": self._normalize_reasoning(api_cfg.get("reasoning_triage", "low")),
            "thread_insight": self._normalize_reasoning(api_cfg.get("reasoning_thread_insight", "medium")),
            "summarization": self._normalize_reasoning(api_cfg.get("reasoning_summarization", "high")),
            "custom_analysis": self._normalize_reasoning(api_cfg.get("reasoning_custom_analysis", "high")),
        }
        self.reasoning_triage = self.reasoning_by_task["triage"]
        self.reasoning_thread_insight = self.reasoning_by_task["thread_insight"]
        self.reasoning_summarization = self.reasoning_by_task["summarization"]
        self.reasoning_custom_analysis = self.reasoning_by_task["custom_analysis"]
        self.max_tokens = api_cfg.get("max_tokens", 4096)
        self.temperature = api_cfg.get("temperature", 0.3)
        self.timeout_seconds = api_cfg.get("codex_timeout_seconds", 1200)
        self.sandbox = api_cfg.get("codex_sandbox", "read-only")
        self.max_prompt_chars = api_cfg.get("codex_max_prompt_chars", 90000)
        self.workdir = Path(api_cfg.get("codex_workdir") or Path(__file__).resolve().parents[2])
        self.log_callback = config.get("runtime", {}).get("log_callback")

        self._usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "codex_runs": 0,
            "prompt_chars": 0,
            "output_chars": 0,
        }
        cache_dir = Path(config.get("paths", {}).get("cache", "data/cache"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = cache_dir / "llm_analysis_cache.json"
        self._cache = self._load_cache()
        self.http = None

        if getattr(self, "_sdk_transport", False):
            self.client = self
            self.logger.info("Codex SDK client initialized")
        elif shutil.which(self.command):
            self.client = self
            self.logger.info("Codex CLI client initialized with command '%s'", self.command)
        else:
            self.client = None
            self.logger.warning("Codex CLI command '%s' was not found", self.command)

    def _chat_completion(self, prompt: str, model: str, max_tokens: int, task_type: str = "summarization") -> str:
        if not self.client:
            raise RuntimeError("Codex CLI is not configured")

        worker_prompt = self._worker_prompt(prompt)
        if len(worker_prompt) > self.max_prompt_chars:
            worker_prompt = (
                worker_prompt[: self.max_prompt_chars]
                + "\n\n[Context truncated by ReportMaster before Codex analysis.]"
            )

        output_dir = Path(self.config.get("paths", {}).get("temp", "data/temp")) / "codex"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"codex_result_{uuid4().hex}.txt"

        command = [
            self.command,
            "exec",
        ]
        reasoning = self._reasoning_for_task(task_type)
        if reasoning:
            command.extend(["-c", f'model_reasoning_effort="{reasoning}"'])
        command.extend([
            "--sandbox",
            self.sandbox,
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
        ])
        if model:
            command.extend(["--model", model])
        command.append("-")

        self._emit_log(f"Starting Codex CLI analysis ({task_type}, reasoning={reasoning or 'default'})", "codex")
        try:
            completed = self._run_codex_command(command, worker_prompt)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex CLI timed out after {self.timeout_seconds} seconds") from exc

        self._usage["codex_runs"] += 1
        self._usage["prompt_chars"] += len(worker_prompt)

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise RuntimeError(f"Codex CLI failed: {detail[-1200:]}")

        content = ""
        if output_path.exists():
            content = output_path.read_text(encoding="utf-8", errors="replace").strip()
            try:
                output_path.unlink()
            except OSError:
                pass
        if not content:
            content = (completed.stdout or "").strip()
        if not content:
            raise RuntimeError("Codex CLI returned an empty response")

        self._usage["output_chars"] += len(content)
        self._emit_log("Codex CLI analysis completed", "codex")
        return content

    def _reasoning_for_task(self, task_type: str) -> str:
        return self.reasoning_by_task.get(task_type) or self.reasoning_by_task.get("summarization", "")

    def _normalize_reasoning(self, value: str) -> str:
        value = (str(value or "")).strip().lower()
        aliases = {
            "extra-high": "high",
            "extra_high": "high",
            "xhigh": "high",
            "extra high": "high",
            "default": "",
            "none": "",
        }
        value = aliases.get(value, value)
        return value if value in {"low", "medium", "high"} else ""

    def _run_codex_command(self, command: List[str], prompt: str):
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workdir,
            bufsize=1,
        )
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        def reader(stream, collector: List[str], source: str):
            try:
                for line in iter(stream.readline, ""):
                    collector.append(line)
                    self._emit_log(line, source)
            finally:
                stream.close()

        threads = [
            threading.Thread(target=reader, args=(process.stdout, stdout_lines, "codex"), daemon=True),
            threading.Thread(target=reader, args=(process.stderr, stderr_lines, "codex"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        assert process.stdin is not None
        process.stdin.write(prompt)
        process.stdin.close()

        try:
            returncode = process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            for thread in threads:
                thread.join(timeout=2)
            raise

        for thread in threads:
            thread.join(timeout=2)

        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
        )

    def _emit_log(self, message: str, source: str = "codex") -> None:
        if not self.log_callback:
            return
        clean = re.sub(r"\x1b\[[0-9;]*m", "", str(message or "")).strip()
        if not clean:
            return
        try:
            self.log_callback(clean, source)
        except Exception:
            self.logger.debug("Codex log callback failed", exc_info=True)

    def _worker_prompt(self, prompt: str) -> str:
        return f"""You are the private ReportMaster analysis worker.

Rules:
- Analyze only the source text provided in this prompt.
- Do not modify files.
- Do not run shell commands unless absolutely necessary.
- Do not browse the web.
- Return only the requested final answer.

{prompt}"""


class CodexSDKClient(CodexCLIClient):
    """Legacy uploaded-file workflows use the same official SDK transport."""

    _sdk_transport = True

    def __init__(self, config):
        super().__init__(config)
        self.client = self

    def _cache_key(self, kind: str, payload: Dict) -> str:
        import os
        from src.reporting.sdk import MODELS
        profile = {task: (os.getenv(f"REPORT_MODEL_{task.upper()}", model),
                          os.getenv(f"REPORT_EFFORT_{task.upper()}", effort))
                   for task, (model, effort) in MODELS.items()}
        return super()._cache_key("sdk_v1_" + kind, {"profile": profile, "payload": payload})

    def _chat_completion(self, prompt, model, max_tokens, task_type="summarization"):
        from src.reporting.sdk import SDKWorker
        task = {"triage": "triage", "thread_insight": "extract"}.get(task_type, "compose")
        with SDKWorker(log=lambda message: self._emit_log(message)) as worker:
            value = worker.ask(task, 'Выполни задание из поля prompt. Верни JSON с одним полем answer, '
                'содержащим полный ответ строкой в формате, требуемом заданием.', {"prompt": prompt})
            self._usage["codex_runs"] += worker.usage["runs"]
            self._usage["prompt_tokens"] += worker.usage["input_tokens"]
            self._usage["completion_tokens"] += worker.usage["output_tokens"]
            self._usage["total_tokens"] += worker.usage["input_tokens"] + worker.usage["output_tokens"]
            return value["answer"]


ClaudeAPIClient = CodexSDKClient
ReportMasterLLMClient = CodexSDKClient


if __name__ == "__main__":
    from src.utils.config_loader import load_config

    cfg = load_config()
    client = GigaChatAPIClient(cfg)
    print("Client ready:", bool(client.client))

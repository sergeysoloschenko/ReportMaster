import hashlib
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from src.processors.document_extractor import DocumentExtractor
from src.processors.linked_documents import LinkedDocumentDownloader
from .documents import render_fragment, content_hash
from .ews import EWSClient, password
from .periods import bounds, last_month
from .reference import read_reference
from .schema import Findings, validate_findings
from .sdk import SDKWorker
from .store import ReportStore


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def safe_name(value):
    return (
        re.sub(r"[^\w.() -]", "_", Path(value.replace("\\", "/")).name)[:160]
        or "document"
    )


def report_folder_name(value):
    # Keep report wording and punctuation; replace only unsafe path characters.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip().rstrip(".")
    if name in ("", ".", ".."):
        name = "Пункт"
    if len(name.encode("utf-8")) > 240:
        suffix = "…" + digest(str(value))[:8]
        name = name.encode("utf-8")[:225].decode("utf-8", errors="ignore") + suffix
    return name


def service_image(att):
    image = Path(att["name"]).suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".svg",
        ".webp",
    }
    return image and (
        bool(
            re.search(
                r"logo|signature|facebook|linkedin|twitter|spacer", att["name"], re.I
            )
        )
        or (
            att.get("inline")
            and att.get("size", 0) < 40000
            and re.fullmatch(
                r"image\d+|img\d+|signature.*", Path(att["name"]).stem, re.I
            )
        )
    )


def chunks(messages, limit=42000):
    batch, size = [], 0
    for message in messages:
        metadata = {
            k: v
            for k, v in message.items()
            if k not in ("body", "attachments", "ews_id")
        }
        attachments = [
            {
                k: v
                for k, v in a.items()
                if k not in ("path", "ews_id", "text", "content_id")
            }
            for a in message.get("attachments", [])
        ]
        body = message.get("body", "")
        parts = [
            dict(metadata, body=body[offset : offset + 10000], attachments=attachments)
            for offset in range(0, max(1, len(body)), 10000)
        ]
        for att, summary in zip(message.get("attachments", []), attachments):
            text = att.get("text", "")
            for offset in range(0, len(text), 10000):
                parts.append(
                    dict(
                        metadata,
                        body="Фрагмент текста вложения " + att["name"],
                        attachments=[dict(summary, text=text[offset : offset + 10000])],
                    )
                )
        for part in parts:
            length = len(json.dumps(part, ensure_ascii=False))
            if batch and size + length > limit:
                yield batch
                batch, size = [], 0
            batch.append(part)
            size += length
    if batch:
        yield batch


def bind_attachment_sources(findings, messages):
    """A selected document also cites its actual owning message, never a guessed one."""
    owners = {
        a["id"]: m["id"]
        for m in messages
        for a in m.get("attachments", [])
        if a.get("id")
    }
    for kind in ("tasks", "risks"):
        for item in findings[kind]:
            # A model may cite a document reference where a mail reference is required.
            item["evidence_ids"] = list(
                dict.fromkeys(owners.get(sid, sid) for sid in item["evidence_ids"])
            )
            for aid in item.get("attachment_ids", []):
                if aid not in owners:
                    raise ValueError("Выбрано несуществующее вложение")
                if owners[aid] not in item["evidence_ids"]:
                    item["evidence_ids"].append(owners[aid])
    return findings


class MonthlyService:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv("REPORTMASTER_DATA", "data")).resolve()
        self.store = ReportStore(self.root / "history" / "reports.sqlite3")
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.participants = yaml.safe_load(
            (
                Path(__file__).resolve().parents[2] / "config/project_participants.yaml"
            ).read_text()
        )

    def log(self, rid, text):
        report = self.store.get(rid)
        self.store.update(rid, logs=(report["logs"] + [str(text)])[-300:])

    def start(self, period=None):
        period = period or last_month()
        bounds(period)
        previous = self.store.previous(period)
        if not previous:
            raise ValueError("Сначала импортируйте и утвердите предыдущий отчёт.")
        if not password():
            raise ValueError("Сначала настройте пароль Exchange на сервере.")
        report = self.store.create(
            period,
            previous_report_id=previous["id"],
            source_type="exchange",
            worker_pid=os.getpid(),
        )
        self.pool.submit(self.run, report["id"])
        return report

    def import_reference(self, path, period):
        bounds(period)
        reference = read_reference(path)
        folder = self.root / "reference"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (reference["source_hash"] + ".docx")
        if path.resolve() != target:
            shutil.copyfile(path, target)
        report = self.store.create(
            period,
            source_type="reference",
            template_path=str(target),
            reference=reference,
            worker_pid=os.getpid(),
        )
        self.pool.submit(self.analyze_reference, report["id"])
        return report

    def analyze_reference(self, rid):
        try:
            report = self.store.update(rid, status="processing")
            with SDKWorker(self.store, lambda s: self.log(rid, s)) as worker:
                result = worker.ask(
                    "baseline",
                    """Раздели строки предыдущего отчёта на отдельные конкретные задачи.
Сохрани завершённые и промежуточные задачи. Отбери риски, релевантные отелю и апартаментам,
включая стоимость отделки и меблировки, закупки и неопределённость операторов арендных зон.
Общепроектный риск включай в части влияния на отель/апартаменты, если эта связь подтверждена задачами.
Не трактуй плановую дату следующего месяца как факт выполнения. Период указан пользователем и имеет приоритет над названием файла.
Разрешённые section: 4.1 HMA; 4.2 техническая работа с Dusit; 4.3 консультанты/закупки;
4.4 Dyer; 4.5 архитектурный надзор и пространственная координация.
Для исходной версии evidence_ids и attachment_ids пустые, previous_id=null. Назначь уникальные id.
Не придумывай вероятность или ранг риска, сохрани исходные характеристики.
Длинные перечни мероприятий риска сократи до 2–3 законченных предложений. Не обрывай слова ради ограничения длины.
include_in_report=true. Для отсутствующих сведений используй статус Требует уточнения.""",
                    {
                        "period": report["period"],
                        "reference": report["reference"],
                        "participants": self.participants,
                    },
                    Findings.model_json_schema(),
                )
                for kind in ("tasks", "risks"):
                    for index, item in enumerate(result[kind]):
                        item["id"] = f"{rid[:8]}-{kind[0]}{index + 1}"
                findings = validate_findings(result, [], baseline=True)
                report = self.store.update(
                    rid,
                    status="draft",
                    tasks=findings["tasks"],
                    risks=findings["risks"],
                    warnings=list(
                        dict.fromkeys(
                            findings["warnings"] + report["reference"]["warnings"]
                        )
                    ),
                    usage=worker.usage,
                )
                self.export(report)
        except Exception as exc:
            self.store.update(rid, status="failed", error=str(exc))

    def prepare_attachments(self, messages, ews, rid):
        extractor = DocumentExtractor(max_chars=240000)
        downloader = LinkedDocumentDownloader()
        folder = self.root / "mail" / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        link_results = {}
        for message_index, message in enumerate(messages, 1):
            if message_index == 1 or message_index % 20 == 0:
                self.log(rid, f"Документы: письмо {message_index} из {len(messages)}")
            items = []
            for att in message.get("attachments", []):
                if service_image(att):
                    continue
                item = dict(att, id=digest(message["id"] + att["ews_id"]), text="")
                cached = self.store.cache_get("attachment:" + item["id"])
                if cached and cached.get("path") and Path(cached["path"]).exists():
                    items.append(cached)
                    continue
                try:
                    if att["size"] > 50 * 1024 * 1024:
                        raise ValueError(
                            "Файл больше 50 МБ; доступен через исходное письмо"
                        )
                    data = ews.attachment(att["ews_id"])
                    path = folder / (
                        hashlib.sha256(data).hexdigest() + "_" + safe_name(att["name"])
                    )
                    path.write_bytes(data)
                    extracted = extractor.extract_bytes(att["name"], data)
                    item.update(
                        path=str(path),
                        text=extracted.text,
                        warning=extracted.skipped_reason
                        or (
                            "Текст документа ограничен 240000 символами"
                            if len(extracted.text) >= 240000
                            else ""
                        ),
                    )
                    self.store.cache_set("attachment:" + item["id"], item)
                except Exception as exc:
                    item["warning"] = str(exc)
                items.append(item)
            for url in downloader.extract_document_urls(message["body"]):
                item = dict(
                    id=digest(message["id"] + url),
                    name="Ссылка на документ",
                    url=url,
                    text="",
                )
                cached = self.store.cache_get("attachment:" + item["id"])
                if cached and cached.get("path") and Path(cached["path"]).exists():
                    items.append(cached)
                    continue
                if url in link_results:
                    item = dict(link_results[url], id=item["id"], url=url)
                    items.append(item)
                    continue
                result = downloader.download(url)
                if result.success:
                    path = folder / (
                        hashlib.sha256(result.data).hexdigest()
                        + "_"
                        + safe_name(result.filename)
                    )
                    path.write_bytes(result.data)
                    extracted = extractor.extract_bytes(result.filename, result.data)
                    item.update(
                        path=str(path),
                        name=result.filename,
                        text=extracted.text,
                        warning=extracted.skipped_reason
                        or (
                            "Текст документа ограничен 240000 символами"
                            if len(extracted.text) >= 240000
                            else ""
                        ),
                    )
                    self.store.cache_set("attachment:" + item["id"], item)
                else:
                    item["warning"] = result.error
                link_results[url] = item
                items.append(item)
            message["attachments"] = items
            self.store.save_message(message)

    def merge_continuations(self, findings, previous, worker, period):
        for kind in ("tasks", "risks"):
            old = {x["id"]: x for x in previous[kind]}
            if kind == "risks":
                for item in findings[kind]:
                    if item.get("previous_id") is None:
                        matches = [
                            x for x in previous[kind] if x["number"] == item["number"]
                        ]
                        if len(matches) == 1:
                            item["previous_id"] = matches[0]["id"]
            if kind == "risks":
                for item in findings[kind]:
                    if not re.search(
                        r"ранг\s*(?:риска)?\s*:",
                        item["response"] + " " + item.get("characteristics", ""),
                        re.I,
                    ):
                        source = old.get(item.get("previous_id"), {})
                        rank = re.search(
                            r"Ранг\s*(?:риска)?\s*:\s*([^\n.]+)",
                            source.get("response", ""),
                            re.I,
                        )
                        item["response"] = (
                            "Ранг риска: " + rank.group(1).strip() + ". "
                            if rank
                            else "Ранг риска: требует оценки. "
                        ) + item["response"]
            groups = {}
            for item in findings[kind]:
                if item.get("previous_id"):
                    groups.setdefault(item["previous_id"], []).append(item)
            for pid, items in groups.items():
                if len(items) < 2:
                    continue
                if pid not in old:
                    raise ValueError("Неизвестная исходная задача при объединении")
                value = worker.ask(
                    "compose",
                    f"""Несколько строк описывают продолжение одного пункта прошлого отчёта.
Объедини их в одну краткую строку {kind}, другой список оставь пустым.
Сохрани все существенные результаты и незакрытые вопросы; частичное возобновление
не означает завершение всей задачи. Противоречия явно обозначь, не выбирай удобную версию.
Не добавляй факты. Сохрани подтверждающие evidence_ids и относящиеся attachment_ids.
Используй previous_id исходного пункта и его направление section, если это задача.
Не более трёх ёмких предложений в результате; статус должен относиться ко всему предмету.""",
                    {"period": period, "previous": old[pid], "candidates": items},
                    Findings.model_json_schema(),
                )
                merged = value.get(kind, [])
                if len(merged) != 1:
                    raise ValueError("Не удалось объединить продолжение задачи")
                merged = merged[0]
                merged["previous_id"] = pid
                merged["id"] = pid
                if kind == "tasks":
                    merged["section"] = old[pid]["section"]
                if not set(merged["evidence_ids"]).issubset(
                    {sid for x in items for sid in x["evidence_ids"]}
                ):
                    raise ValueError("Объединение добавило неподтверждённый источник")
                if not set(merged["attachment_ids"]).issubset(
                    {aid for x in items for aid in x["attachment_ids"]}
                ):
                    raise ValueError("Объединение добавило неподтверждённое вложение")
                first = next(
                    i
                    for i, x in enumerate(findings[kind])
                    if x.get("previous_id") == pid
                )
                findings[kind] = [
                    x for x in findings[kind] if x.get("previous_id") != pid
                ]
                findings[kind].insert(first, merged)
                findings["warnings"].extend(value.get("warnings", []))
        return findings

    def compact_facts(self, cards, worker, period):
        """Bound synthesis context while retaining explicit evidence and uncertainty."""
        for _ in range(3):
            if len(json.dumps(cards, ensure_ascii=False)) <= 100000:
                return cards
            groups, group, size = [], [], 0
            for card in cards:
                length = len(json.dumps(card, ensure_ascii=False))
                if group and size + length > 65000:
                    groups.append(group)
                    group, size = [], 0
                group.append(card)
                size += length
            if group:
                groups.append(group)
            compacted = []
            for group in groups:
                value = worker.ask(
                    "compose",
                    """Сверни повторяющиеся факты переписки для подготовки месячного отчёта.
Верни {"facts":[{"section":"4.2","text":"краткое содержание","evidence_ids":[],"attachment_ids":[]}]}.
Объединяй повторы одного предмета. Сохрани отдельные существенные действия, результаты,
последние подтверждённые статусы, даты, сроки, противоречия и нерешённые вопросы.
Не превращай планы в результаты. Старые цитаты не являются новыми событиями.
Сохрани подтверждающие evidence_ids и относящиеся attachment_ids из переданного пакета.
Не добавляй факты и ссылки. Текст сожми примерно втрое за счёт повторов и второстепенных подробностей.""",
                    {"period": period, "facts": group},
                )
                evidence = {sid for c in group for sid in c["evidence_ids"]}
                attachments = {
                    aid for c in group for aid in c.get("attachment_ids", [])
                }
                reduced = value.get("facts", [])
                if not reduced:
                    raise ValueError("Сводка фактов оказалась пустой")
                for card in reduced:
                    if (
                        card.get("section") not in ("4.1", "4.2", "4.3", "4.4", "4.5")
                        or not card.get("text")
                        or not card.get("evidence_ids")
                        or not set(card["evidence_ids"]).issubset(evidence)
                        or not set(card.get("attachment_ids", [])).issubset(attachments)
                    ):
                        raise ValueError(
                            "Сводка фактов содержит неподтверждённые ссылки"
                        )
                compacted.extend(reduced)
            cards = compacted
        if len(json.dumps(cards, ensure_ascii=False)) > 100000:
            raise ValueError(
                "Сводка слишком велика; требуется дополнительная разбивка тем"
            )
        return cards

    def run(self, rid):
        try:
            report = self.store.update(rid, status="processing")
            previous = self.store.get(report["previous_report_id"])
            ews = EWSClient()
            messages = ews.collect(report["period"], lambda s: self.log(rid, s))
            self.store.update(
                rid, coverage=ews.coverage, source_ids=[m["id"] for m in messages]
            )
            for m in messages:
                self.store.save_message(m)
            with SDKWorker(self.store, lambda s: self.log(rid, s)) as worker:
                # Every body chunk is considered, including messages without participant keywords.
                selected = set()
                decisions = []
                history_titles = {
                    kind: [
                        {
                            "id": x["id"],
                            "title": x["title"],
                            "status": x["status"],
                            "section": x.get("section"),
                        }
                        for x in previous[kind]
                    ]
                    for kind in ("tasks", "risks")
                }
                for batch in chunks(
                    [
                        {k: v for k, v in m.items() if k not in ("ews_id",)}
                        for m in messages
                    ]
                ):
                    result = worker.ask(
                        "triage",
                        """Для каждого уникального id письма реши релевантность зоне ответственности.
Ищи также продолжение задач/рисков прошлого периода, включая переоткрытие завершённых.
При сомнении включай. Не исключай короткое письмо с содержательным вложением.
Верни объект decisions с обязательным ключом для каждого уникального id письма:
{"decisions":{"id письма":{"include":true,"reason":"основание"}}}.
Письма могут быть частями длинного сообщения; оцени предоставленную часть.""",
                        {
                            "messages": batch,
                            "history": history_titles,
                            "participants": self.participants,
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["decisions"],
                            "properties": {
                                "decisions": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": list(
                                        dict.fromkeys(x["id"] for x in batch)
                                    ),
                                    "properties": {
                                        x["id"]: {
                                            "type": "object",
                                            "additionalProperties": False,
                                            "required": ["include", "reason"],
                                            "properties": {
                                                "include": {"type": "boolean"},
                                                "reason": {"type": "string"},
                                            },
                                        }
                                        for x in batch
                                    },
                                }
                            },
                        },
                    )
                    found = [
                        dict(value, id=key)
                        for key, value in result["decisions"].items()
                    ]
                    expected = {x["id"] for x in batch}
                    if {x.get("id") for x in found} != expected or any(
                        type(x.get("include")) is not bool for x in found
                    ):
                        raise ValueError("Первичный отбор не охватил все сообщения")
                    decisions.extend(found)
                    selected.update(x["id"] for x in found if x["include"])
                # Include other messages in selected Exchange conversations to preserve context.
                conversations = {
                    m["conversation_id"]
                    for m in messages
                    if m["id"] in selected and m["conversation_id"]
                }
                selected.update(
                    m["id"] for m in messages if m["conversation_id"] in conversations
                )
                relevant = [m for m in messages if m["id"] in selected]
                self.store.update(
                    rid, selection=decisions, selected_count=len(relevant)
                )
                self.prepare_attachments(relevant, ews, rid)
                cards = []
                fact_batches = list(chunks(relevant, 110000))
                for batch_index, batch in enumerate(fact_batches, 1):
                    self.log(
                        rid,
                        f"Извлечение фактов: пакет {batch_index} из {len(fact_batches)}",
                    )
                    result = worker.ask(
                        "extract",
                        """Извлеки конкретные факты, действия, решения, незакрытые вопросы и риски.
Учитывай дату самого события: цитата старого письма внутри августовского не является новым событием.
События вне указанного period используй только как контекст; включай их лишь при подтверждённом развитии в новом периоде.
Для каждого факта укажи evidence_ids (id писем), attachment_ids только содержательных относящихся к факту документов,
section (4.1 HMA, 4.2 Dusit техническое, 4.3 консультанты/закупки, 4.4 Dyer, 4.5 надзор/координация),
text (факт, дата и статус). Сохрани неопределённости и противоречия.
Для продолжения известной задачи сохраняй её прежний section из истории.
Верни {"facts":[{"section":"4.2","text":"...","evidence_ids":[],"attachment_ids":[]}]}.
Изображения без извлечённого текста не считай прочитанными; решение должно опираться на текст письма.""",
                        {
                            "messages": [
                                {k: v for k, v in m.items() if k != "ews_id"}
                                for m in batch
                            ],
                            "participants": self.participants,
                            "previous_tasks": history_titles,
                            "period": report["period"],
                        },
                    )
                    for fact in result.get("facts", []):
                        if fact.get("section") not in [
                            "4.1",
                            "4.2",
                            "4.3",
                            "4.4",
                            "4.5",
                        ] or not fact.get("text"):
                            raise ValueError("Некорректная карточка факта")
                        if not fact.get("evidence_ids") or not set(
                            fact["evidence_ids"]
                        ).issubset({m["id"] for m in batch}):
                            raise ValueError("Карточка факта без корректного источника")
                        cards.append(fact)
                self.store.update(rid, raw_facts=cards)
                cards = self.compact_facts(cards, worker, report["period"])
                self.store.update(rid, facts=cards)
                # Compose by section to bound context; risk review receives all concise cards separately.
                assembled = {"tasks": [], "risks": [], "warnings": []}
                instructions = """Сформируй краткие таблицы нового месяца, сопоставив факты с прошлой версией.
Задача = конкретный предмет работы, не вся строка направления. Один предмет не дублируй.
При продолжении сохрани previous_id. Закрытые задачи включай только при новых существенных событиях.
Без новых данных не меняй подтверждённый статус и не повторяй пункт (include_in_report=false).
Новые задачи включай независимо от прошлого отчёта. Фактические изменения подкрепи evidence_ids.
attachment_ids выбирай из источников; включай только относящиеся к пункту документы или ссылки.
Формулировки: 1–3 коротких предложения с действием, результатом и существенным открытым вопросом.
Не выдумывай сроки, ранги и вероятности. Отличай планы от выполненных действий.
Используй соседние пункты только как образец стиля, не как источник фактов текущего месяца."""
                for section in ("4.1", "4.2", "4.3", "4.4", "4.5"):
                    section_cards = [x for x in cards if x["section"] == section]
                    if not section_cards:
                        continue
                    result = worker.ask(
                        "compose",
                        instructions
                        + f" Сейчас формируй только задачи section={section}, risks=[].",
                        {
                            "period": report["period"],
                            "facts": section_cards,
                            "previous": previous["tasks"],
                            "style_examples": previous["reference"]["style_examples"][
                                :4
                            ],
                        },
                        Findings.model_json_schema(),
                    )
                    if any(x["section"] != section for x in result["tasks"]):
                        raise ValueError("Неверное направление отчёта")
                    assembled["tasks"].extend(result["tasks"])
                    assembled["warnings"].extend(result["warnings"])
                result = worker.ask(
                    "review",
                    instructions
                    + " Сейчас пересмотри только риски, tasks=[]. Новые номера рисков обозначай Н-1, Н-2; существующие номера сохраняй.",
                    {
                        "period": report["period"],
                        "facts": cards,
                        "previous_risks": previous["risks"],
                    },
                    Findings.model_json_schema(),
                )
                assembled["risks"] = result["risks"]
                assembled["warnings"].extend(result["warnings"])
                assembled = self.merge_continuations(
                    assembled, previous, worker, report["period"]
                )
                for kind in ("tasks", "risks"):
                    for index, item in enumerate(assembled[kind]):
                        item["id"] = (
                            item["previous_id"] or f"{rid[:8]}-{kind[0]}{index + 1}"
                        )
                assembled = bind_attachment_sources(assembled, relevant)
                findings = validate_findings(assembled, relevant, previous)
                warnings = findings.pop("warnings")
                warnings += [
                    f"{m['subject']}: {a['name']} — {a['warning']}"
                    for m in relevant
                    for a in m["attachments"]
                    if a.get("warning")
                ]
                if not messages:
                    warnings.append(
                        "За период не найдено писем. Проверьте охват папок перед утверждением."
                    )
                report = self.store.update(
                    rid,
                    status="draft",
                    **findings,
                    warnings=warnings,
                    usage=worker.usage,
                    template_path=previous["template_path"],
                    reference=previous["reference"],
                )
                self.export(report)
        except Exception as exc:
            self.store.update(rid, status="failed", error=str(exc))

    def export(self, report):
        directory = (
            self.root / "output" / "history" / report["id"] / str(report["revision"])
        )
        path = render_fragment(
            report,
            report["template_path"],
            report["reference"],
            directory / f"Report_{report['period']}.docx",
        )
        attachments = self.export_attachments(report, directory)
        return self.store.update(
            report["id"],
            expected_revision=report["revision"],
            report_path=str(path),
            attachments_path=str(attachments),
            document_content_hash=content_hash(report),
        )

    def export_attachments(self, report, directory):
        attachments = directory / "Attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        manifest = []
        for kind in ("tasks", "risks"):
            for item in report[kind]:
                if not item.get("include_in_report"):
                    continue
                target = (
                    attachments
                    / ("Задачи" if kind == "tasks" else "Риски")
                    / report_folder_name(item.get("section", item.get("number")))
                    / report_folder_name(item["title"])
                )
                selected = set(item["attachment_ids"])
                entries = []
                for sid in item["evidence_ids"]:
                    message = self.store.message(sid)
                    if not message:
                        continue
                    for att in message["attachments"]:
                        if att.get("id") not in selected:
                            continue
                        target.mkdir(parents=True, exist_ok=True)
                        entry = {
                            "id": att["id"],
                            "name": att["name"],
                            "url": att.get("url", ""),
                            "source_id": sid,
                            "warning": att.get("warning", ""),
                        }
                        if att.get("path") and Path(att["path"]).exists():
                            filename = att["id"][:10] + "_" + safe_name(att["name"])
                            shutil.copyfile(att["path"], target / filename)
                            entry["file"] = str(
                                (target / filename).relative_to(attachments)
                            )
                        entries.append(entry)
                manifest.append(
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "section": item.get("section", item.get("number")),
                        "folder": str(target.relative_to(attachments)),
                        "documents": entries,
                    }
                )
        (attachments / "index.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        (attachments / "index.txt").write_text(
            "\n\n".join(
                x["section"] + " — " + x["title"]
                + "\nПапка: " + x["folder"]
                + "\n"
                + "\n".join(
                    f"{a['name']}: {a.get('file') or a.get('url') or a.get('warning')}"
                    for a in x["documents"]
                )
                for x in manifest
            )
        )
        return attachments

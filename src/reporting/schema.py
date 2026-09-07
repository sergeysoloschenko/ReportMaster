from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    section: Literal["4.1", "4.2", "4.3", "4.4", "4.5"]
    title: str = Field(min_length=1, max_length=240)
    result: str = Field(min_length=1, max_length=1400)
    status: Literal[
        "Завершено",
        "В работе",
        "На согласовании",
        "Ожидается информация",
        "Приостановлено",
        "Требует уточнения",
    ]
    previous_id: str | None
    evidence_ids: list[str]
    attachment_ids: list[str]
    include_in_report: bool


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    number: str
    title: str = Field(min_length=1, max_length=700)
    characteristics: str = Field(max_length=700)
    dynamics: str = Field(min_length=1, max_length=1000)
    response: str = Field(min_length=1, max_length=1000)
    status: Literal[
        "Открыт", "Снижен", "Повышен", "Реализовался", "Снят", "Требует уточнения"
    ]
    previous_id: str | None
    evidence_ids: list[str]
    attachment_ids: list[str]
    include_in_report: bool


class Findings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[Task]
    risks: list[Risk]
    warnings: list[str]


def validate_findings(data, messages, previous=None, baseline=False, manual=False):
    value = Findings.model_validate(data).model_dump()
    previous = previous or {"tasks": [], "risks": []}
    sources = {m["id"]: m for m in messages}
    all_ids = set()
    for kind in ("tasks", "risks"):
        old = {x["id"]: x for x in previous[kind]}
        matched = set()
        for item in value[kind]:
            if not item["id"] or item["id"] in all_ids:
                raise ValueError("Повторяющийся или пустой идентификатор задачи/риска")
            all_ids.add(item["id"])
            pid = item["previous_id"]
            if pid and (pid not in old or pid in matched):
                raise ValueError("Некорректная связь с предыдущей версией")
            if pid:
                matched.add(pid)
                item["id"] = pid  # stable identity, regardless of model-generated alias
            if not set(item["evidence_ids"]).issubset(sources):
                raise ValueError("Обнаружена ссылка на несуществующее письмо")
            allowed_attachments = {
                a["id"]
                for sid in item["evidence_ids"]
                for a in sources[sid].get("attachments", [])
                if "id" in a
            }
            if not set(item["attachment_ids"]).issubset(allowed_attachments):
                raise ValueError("Вложение не связано с письмами-основаниями пункта")
            if baseline or manual:
                continue
            if not item["evidence_ids"]:
                if not pid:
                    raise ValueError("Новая задача или риск без источника")
                # No news means no factual status change and no automatic repeated report row.
                saved = dict(old[pid])
                saved.update(
                    previous_id=pid,
                    evidence_ids=[],
                    attachment_ids=[],
                    include_in_report=False,
                )
                item.clear()
                item.update(saved)
                if saved["status"] not in ("Завершено", "Снят"):
                    value["warnings"].append(
                        "Нет новых подтверждений: " + saved["title"]
                    )
        # Preserve all old items, including closed ones, for later reopening checks.
        for pid, saved in old.items():
            if pid not in matched:
                value[kind].append(
                    dict(
                        saved,
                        previous_id=pid,
                        evidence_ids=[],
                        attachment_ids=[],
                        include_in_report=False,
                    )
                )
                if saved["status"] not in ("Завершено", "Снят"):
                    value["warnings"].append(
                        "Нет новых подтверждений: " + saved["title"]
                    )
    ids = [x["id"] for kind in ("tasks", "risks") for x in value[kind]]
    if len(ids) != len(set(ids)):
        raise ValueError("Конфликт постоянных идентификаторов")
    return value

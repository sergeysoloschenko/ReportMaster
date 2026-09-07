import io
import sqlite3
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .pipeline import MonthlyService
from .periods import last_month
from .schema import Findings, validate_findings
from .ews import password
from .sdk import MODELS
from .documents import content_hash


class StartRequest(BaseModel):
    period: str | None = None


class EditRequest(Findings):
    revision: int


class ApproveRequest(BaseModel):
    revision: int
    warnings_acknowledged: bool = False


def router(require_auth, service=None):
    service = service or MonthlyService()
    routes = APIRouter(prefix="/api/monthly", dependencies=[Depends(require_auth)])

    def get(rid):
        report = service.store.get(rid)
        if not report:
            raise HTTPException(404, "Отчёт не найден")
        return report

    def public(report):
        return {
            k: v
            for k, v in report.items()
            if k
            not in ("template_path", "report_path", "attachments_path", "reference")
        }

    @routes.get("/settings")
    def settings():
        return {
            "default_period": last_month(),
            "ews_configured": bool(password()),
            "models": MODELS,
        }

    @routes.get("/reports")
    def history():
        return [
            dict(
                id=r["id"],
                period=r["period"],
                status=r["status"],
                created_at=r["created_at"],
                revision=r["revision"],
                source_type=r.get("source_type"),
            )
            for r in service.store.list()
        ]

    @routes.post("/reports")
    def start(payload: StartRequest):
        try:
            return public(service.start(payload.period))
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @routes.post("/reference")
    async def import_reference(period: str = Form(...), file: UploadFile = File(...)):
        if not file.filename.lower().endswith(".docx"):
            raise HTTPException(400, "Нужен файл DOCX")
        directory = service.root / "temp" / "reference"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (uuid4().hex + ".docx")
        try:
            with path.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    stream.write(chunk)
            return public(service.import_reference(path, period))
        except (ValueError, sqlite3.IntegrityError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)

    @routes.get("/reports/{rid}")
    def report(rid: str):
        return public(get(rid))

    @routes.put("/reports/{rid}")
    def edit(rid: str, payload: EditRequest):
        report = get(rid)
        if report["status"] != "draft":
            raise HTTPException(409, "Редактировать можно только черновик")
        try:
            previous = service.store.get(report.get("previous_report_id", ""))
            messages = [
                service.store.message(sid) for sid in report.get("source_ids", [])
            ]
            findings = validate_findings(
                payload.model_dump(exclude={"revision"}),
                [m for m in messages if m],
                previous,
                baseline=report.get("source_type") == "reference",
                manual=True,
            )
            updated = service.store.update(
                rid,
                expected_revision=payload.revision,
                **findings,
                manual_edits=(
                    report.get("manual_edits", [])
                    + [
                        {
                            "revision": report["revision"],
                            "before": {k: report[k] for k in ("tasks", "risks")},
                            "after": findings,
                        }
                    ]
                ),
            )
            return public(service.export(updated))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @routes.post("/reports/{rid}/approve")
    def approve(rid: str, payload: ApproveRequest):
        report = get(rid)
        if report["status"] != "draft" or not report.get("report_path"):
            raise HTTPException(409, "Можно утвердить только сформированный черновик")
        if report.get("document_content_hash") != content_hash(report):
            raise HTTPException(
                409,
                "Таблицы ещё не соответствуют последним правкам. Сохраните их повторно.",
            )
        if report.get("source_type") == "exchange" and not report.get(
            "coverage", {}
        ).get("complete"):
            raise HTTPException(409, "Получение почты не завершено")
        if report["warnings"] and not payload.warnings_acknowledged:
            raise HTTPException(409, "Перед утверждением ознакомьтесь с замечаниями")
        try:
            return public(
                service.store.update(
                    rid, expected_revision=payload.revision, status="approved"
                )
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @routes.post("/reports/{rid}/revision")
    def revision(rid: str):
        report = get(rid)
        if report["status"] != "approved":
            raise HTTPException(409, "Новая редакция создаётся из утверждённой версии")
        values = {
            k: v
            for k, v in report.items()
            if k
            not in (
                "id",
                "revision",
                "created_at",
                "updated_at",
                "status",
                "period",
                "report_path",
                "attachments_path",
            )
        }
        created = service.store.create(report["period"], status="draft", **values)
        return public(service.export(created))

    @routes.get("/reports/{rid}/document")
    def document(rid: str):
        report = get(rid)
        if report.get("document_content_hash") != content_hash(report):
            raise HTTPException(409, "Сначала сохраните правки и обновите документ")
        path = Path(report.get("report_path", ""))
        if not path.is_file():
            raise HTTPException(404, "Документ ещё не готов")
        return FileResponse(path, filename=f"Report_{report['period']}.docx")

    @routes.get("/reports/{rid}/attachments")
    def attachments(rid: str):
        report = get(rid)
        if report.get("document_content_hash") != content_hash(report):
            raise HTTPException(409, "Вложения ещё не соответствуют последним правкам")
        path = Path(report.get("attachments_path", ""))
        if not report.get("attachments_path") or not path.is_dir():
            raise HTTPException(404, "Вложения ещё не готовы")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in path.rglob("*"):
                if item.is_file():
                    archive.write(item, str(item.relative_to(path)))
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="Attachments_{report["period"]}.zip"'
            },
        )

    @routes.get("/reports/{rid}/sources/{sid}")
    def source(rid: str, sid: str):
        report = get(rid)
        if sid not in report.get("source_ids", []):
            raise HTTPException(404, "Источник не относится к отчёту")
        message = service.store.message(sid)
        if not message:
            raise HTTPException(404, "Источник не найден")
        return {
            **{k: v for k, v in message.items() if k not in ("ews_id", "attachments")},
            "attachments": [
                {k: v for k, v in a.items() if k not in ("ews_id", "path")}
                for a in message["attachments"]
            ],
        }

    @routes.get("/reports/{rid}/sources/{sid}/attachments/{aid}")
    def source_attachment(rid: str, sid: str, aid: str):
        source(rid, sid)
        message = service.store.message(sid)
        att = next((a for a in message["attachments"] if a.get("id") == aid), None)
        if not att or not att.get("path") or not Path(att["path"]).is_file():
            raise HTTPException(404, "Файл недоступен; используйте исходную ссылку")
        return FileResponse(att["path"], filename=att["name"])

    return routes

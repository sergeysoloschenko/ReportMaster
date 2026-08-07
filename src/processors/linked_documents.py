"""Download document links found in email bodies as report attachments."""

from __future__ import annotations

import ipaddress
import logging
import mimetypes
import re
import socket
from dataclasses import dataclass
from email.message import Message
from html import unescape
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import httpx


DOCUMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".dwg",
    ".dxf",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rar",
    ".rtf",
    ".txt",
    ".xls",
    ".xlsm",
    ".xlsx",
    ".zip",
}

FILE_SHARE_HOST_MARKERS = (
    "1drv.ms",
    "cloud.mail.ru",
    "disk.yandex.",
    "docs.google.com",
    "drive.google.com",
    "dropbox.com",
    "sharepoint.com",
    "we.tl",
    "wetransfer.com",
    "yadi.sk",
)

CONTENT_TYPE_EXTENSIONS = {
    "application/msword": ".doc",
    "application/pdf": ".pdf",
    "application/rtf": ".rtf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/zip": ".zip",
    "text/csv": ".csv",
    "text/plain": ".txt",
}


@dataclass
class LinkedDocumentResult:
    source_url: str
    success: bool
    filename: str = ""
    data: bytes = b""
    resolved_url: str = ""
    content_type: str = ""
    error: str = ""


class LinkedDocumentDownloader:
    """Find likely file-sharing URLs and download public documents safely."""

    URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
    HREF_PATTERN = re.compile(
        r"href\s*=\s*[\"'](?P<url>https?://[^\"']+)[\"']",
        re.IGNORECASE,
    )

    def __init__(
        self,
        enabled: bool = True,
        timeout_seconds: float = 20.0,
        max_bytes: int = 25 * 1024 * 1024,
        max_links_per_message: int = 10,
        max_redirects: int = 6,
        client: Optional[httpx.Client] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_links_per_message = max_links_per_message
        self.max_redirects = max_redirects
        self._result_cache = {}
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "ReportMaster/1.2 document-link-downloader"},
        )

    def download_from_text(self, plain_text: str, html_text: str = "") -> List[LinkedDocumentResult]:
        if not self.enabled:
            return []

        urls = self.extract_document_urls(plain_text, html_text)
        results = []
        for url in urls[: self.max_links_per_message]:
            result = self._result_cache.get(url)
            if result is None:
                result = self.download(url)
                self._result_cache[url] = result
            results.append(result)
        return results

    def extract_document_urls(self, plain_text: str, html_text: str = "") -> List[str]:
        if isinstance(plain_text, bytes):
            plain_text = plain_text.decode("utf-8", errors="replace")
        if isinstance(html_text, bytes):
            html_text = html_text.decode("utf-8", errors="replace")
        candidates = []
        candidates.extend(self.URL_PATTERN.findall(unescape(plain_text or "")))
        candidates.extend(match.group("url") for match in self.HREF_PATTERN.finditer(unescape(html_text or "")))
        candidates.extend(self.URL_PATTERN.findall(unescape(html_text or "")))

        unique = []
        seen = set()
        for candidate in candidates:
            url = self._clean_url(candidate)
            if not url or url in seen or not self._looks_like_document_link(url):
                continue
            seen.add(url)
            unique.append(url)
        return unique

    def download(self, source_url: str) -> LinkedDocumentResult:
        source_url = self._clean_url(source_url)
        if not source_url:
            return LinkedDocumentResult(source_url=source_url, success=False, error="Некорректная ссылка")

        try:
            prepared_url = self._prepare_provider_url(source_url)
            if self._is_yandex_public_link(prepared_url):
                prepared_url = self._resolve_yandex_download_url(prepared_url)
            response, final_url = self._request_with_safe_redirects(prepared_url)
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if response.status_code < 200 or response.status_code >= 300:
                response.close()
                return LinkedDocumentResult(
                    source_url=source_url,
                    success=False,
                    resolved_url=final_url,
                    content_type=content_type,
                    error=f"HTTP {response.status_code}",
                )

            content_length = response.headers.get("content-length")
            try:
                declared_size = int(content_length) if content_length else 0
            except ValueError:
                declared_size = 0
            if declared_size > self.max_bytes:
                response.close()
                return LinkedDocumentResult(
                    source_url=source_url,
                    success=False,
                    resolved_url=final_url,
                    content_type=content_type,
                    error=f"Файл превышает лимит {self.max_bytes // (1024 * 1024)} МБ",
                )

            data = self._read_limited_content(response, self.max_bytes)
            if not data:
                return LinkedDocumentResult(
                    source_url=source_url,
                    success=False,
                    resolved_url=final_url,
                    content_type=content_type,
                    error="Сервер вернул пустой файл",
                )
            if content_type in {"text/html", "application/xhtml+xml"}:
                return LinkedDocumentResult(
                    source_url=source_url,
                    success=False,
                    resolved_url=final_url,
                    content_type=content_type,
                    error="Ссылка ведёт на веб-страницу или требует авторизации",
                )

            filename = self._response_filename(response.headers, final_url, content_type)
            return LinkedDocumentResult(
                source_url=source_url,
                success=True,
                filename=filename,
                data=data,
                resolved_url=final_url,
                content_type=content_type,
            )
        except Exception as exc:
            self.logger.warning("Could not download linked document %s: %s", source_url, exc)
            return LinkedDocumentResult(source_url=source_url, success=False, error=self._public_error(exc))

    def _request_with_safe_redirects(self, url: str) -> tuple[httpx.Response, str]:
        current_url = url
        for _ in range(self.max_redirects + 1):
            self._validate_public_http_url(current_url)
            request = self.client.build_request("GET", current_url)
            response = self.client.send(request, stream=True)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response, str(response.url)
            location = response.headers.get("location")
            if not location:
                return response, str(response.url)
            response.close()
            current_url = urljoin(str(response.url), location)
        raise RuntimeError("Превышен лимит перенаправлений")

    def _resolve_yandex_download_url(self, public_url: str) -> str:
        api_url = (
            "https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key="
            + quote(public_url, safe="")
        )
        response, _ = self._request_with_safe_redirects(api_url)
        if response.status_code < 200 or response.status_code >= 300:
            response.close()
            raise RuntimeError(f"Яндекс Диск вернул HTTP {response.status_code}")
        payload = self._read_limited_content(response, 1024 * 1024)
        href = httpx.Response(200, content=payload).json().get("href")
        if not href:
            raise RuntimeError("Яндекс Диск не вернул публичную ссылку для скачивания")
        return href

    def _read_limited_content(self, response: httpx.Response, limit: int) -> bytes:
        chunks = []
        size = 0
        try:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise RuntimeError(f"Файл превышает лимит {limit // (1024 * 1024)} МБ")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    def _validate_public_http_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            raise ValueError("Разрешены только HTTPS-ссылки")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Некорректный адрес документа")
        if parsed.port not in {None, 443}:
            raise ValueError("Нестандартный сетевой порт запрещён")

        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError("Не удалось определить адрес сервера")
        for address in {item[4][0] for item in addresses}:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError("Локальный или служебный сетевой адрес запрещён")

    def _prepare_provider_url(self, url: str) -> str:
        url = self._unwrap_safe_link(url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path

        google_match = re.search(r"/(document|spreadsheets|presentation)/d/([^/]+)", path)
        if host == "docs.google.com" and google_match:
            kind, file_id = google_match.groups()
            extension = {"document": "docx", "spreadsheets": "xlsx", "presentation": "pptx"}[kind]
            return f"https://docs.google.com/{kind}/d/{file_id}/export?format={extension}"

        drive_match = re.search(r"/file/d/([^/]+)", path)
        if host in {"drive.google.com", "docs.google.com"} and drive_match:
            return f"https://drive.usercontent.google.com/download?id={drive_match.group(1)}&export=download&confirm=t"

        if host == "drive.google.com":
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if query.get("id"):
                return f"https://drive.usercontent.google.com/download?id={query['id']}&export=download&confirm=t"

        if host.endswith("dropbox.com"):
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query["dl"] = "1"
            return urlunparse(parsed._replace(query=urlencode(query)))

        if host.endswith("sharepoint.com"):
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query["download"] = "1"
            return urlunparse(parsed._replace(query=urlencode(query)))

        return url

    def _looks_like_document_link(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        suffix = Path(parsed.path).suffix.lower()
        query = parsed.query.lower()
        embedded_url = self._unwrap_safe_link(url)
        if embedded_url != url:
            return self._looks_like_document_link(embedded_url)
        return (
            suffix in DOCUMENT_EXTENSIONS
            or any(marker in host for marker in FILE_SHARE_HOST_MARKERS)
            or any(marker in query for marker in ("download=", "attachment=", "file="))
        )

    def _unwrap_safe_link(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if "safelinks.protection.outlook.com" not in host:
            return url
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        target = query.get("url")
        return target if target and target.startswith(("https://", "http://")) else url

    def _is_yandex_public_link(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in {"disk.yandex.ru", "disk.yandex.com", "yadi.sk"}

    def _response_filename(self, headers: httpx.Headers, final_url: str, content_type: str) -> str:
        disposition = headers.get("content-disposition", "")
        filename = self._filename_from_content_disposition(disposition)
        if not filename:
            filename = Path(urlparse(final_url).path).name
        filename = self._sanitize_filename(filename)

        suffix = Path(filename).suffix.lower()
        if not suffix:
            extension = CONTENT_TYPE_EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ""
            filename = f"linked_document{extension}"
        return filename

    def _filename_from_content_disposition(self, disposition: str) -> str:
        if not disposition:
            return ""
        message = Message()
        message["content-disposition"] = disposition
        filename = message.get_filename() or ""
        if isinstance(filename, tuple):
            filename = filename[-1]
        return str(filename)

    def _clean_url(self, value: str) -> str:
        url = unescape(str(value or "")).strip()
        while url and url[-1] in ".,;:!?)]}>»”'\"":
            url = url[:-1]
        return url

    def _sanitize_filename(self, value: str) -> str:
        filename = Path(str(value or "linked_document")).name
        filename = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", filename).strip().strip(".")
        return (filename or "linked_document")[:160]

    def _public_error(self, exc: Exception) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return "Истекло время ожидания скачивания"
        if isinstance(exc, httpx.HTTPStatusError):
            return f"HTTP {exc.response.status_code}"
        text = str(exc).strip()
        return text[:240] or exc.__class__.__name__

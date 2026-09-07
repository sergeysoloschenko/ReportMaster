"""Read-only EWS SOAP client: FindFolder, FindItem, GetItem, GetAttachment."""
import base64
import hashlib
import os
import time
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

import requests
from requests_ntlm import HttpNtlmAuth

from .periods import bounds, utc

NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "m": "http://schemas.microsoft.com/exchange/services/2006/messages",
    "t": "http://schemas.microsoft.com/exchange/services/2006/types",
}


def txt(node, path):
    found = node.find(path, NS)
    return found.text or "" if found is not None else ""


def password():
    path = os.getenv(
        "EWS_PASSWORD_FILE",
        str(Path(os.getenv("REPORTMASTER_DATA", "data")) / "history" / "ews_password"),
    )
    return (
        Path(path).read_text().rstrip("\r\n")
        if path and Path(path).is_file()
        else os.getenv("EWS_PASSWORD", "")
    )


class EWSClient:
    def __init__(self, session=None):
        self.url = os.getenv("EWS_URL", "https://post.spgr.ru/EWS/Exchange.asmx")
        if not self.url.startswith("https://"):
            raise ValueError("Для EWS требуется HTTPS")
        self.session = session or requests.Session()
        if session is None:
            secret = password()
            if not secret:
                raise ValueError(
                    "Не настроен пароль Exchange: задайте EWS_PASSWORD_FILE на сервере."
                )
            self.session.auth = HttpNtlmAuth(
                os.getenv("EWS_USERNAME", r"spectrum\soloshchenko"), secret
            )
        self.coverage = {"folders": [], "complete": False, "warnings": []}

    def call(self, operation):
        envelope = f'<s:Envelope xmlns:s="{NS["s"]}" xmlns:m="{NS["m"]}" xmlns:t="{NS["t"]}"><s:Header><t:RequestServerVersion Version="Exchange2010_SP2"/></s:Header><s:Body>{operation}</s:Body></s:Envelope>'
        for attempt in range(4):
            response = self.session.post(
                self.url,
                data=envelope.encode(),
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=(15, 90),
                allow_redirects=False,
            )
            if response.status_code in (429, 503) and attempt < 3:
                time.sleep(min(2**attempt, 8))
                continue
            if response.status_code in (401, 403):
                raise RuntimeError(
                    "Exchange отклонил NTLM-вход. Проверьте пароль и права почтового ящика."
                )
            if response.status_code != 200:
                raise RuntimeError(f"Exchange: HTTP {response.status_code}")
            if b"<!DOCTYPE" in response.content or b"<!ENTITY" in response.content:
                raise RuntimeError("Недопустимый XML Exchange")
            root = ET.fromstring(response.content)
            codes = [n.text for n in root.findall(".//m:ResponseCode", NS)]
            if "ErrorServerBusy" in codes and attempt < 3:
                time.sleep(min(2**attempt, 8))
                continue
            errors = [code for code in codes if code != "NoError"]
            if errors or root.find(".//s:Fault", NS) is not None:
                raise RuntimeError("Exchange: " + ", ".join(errors or ["SOAP Fault"]))
            if not codes:
                raise RuntimeError("Exchange не подтвердил выполнение запроса")
            return root
        raise RuntimeError("Exchange временно недоступен")

    def folders(self, distinguished):
        """Include mail moved by rules into subfolders, not only the root inbox."""
        folders = [(f'<t:DistinguishedFolderId Id="{distinguished}"/>', distinguished)]
        offset = 0
        while True:
            root = self.call(
                f"""<m:FindFolder Traversal="Deep"><m:FolderShape><t:BaseShape>Default</t:BaseShape></m:FolderShape>
                <m:IndexedPageFolderView MaxEntriesReturned="100" Offset="{offset}" BasePoint="Beginning"/>
                <m:ParentFolderIds>{folders[0][0]}</m:ParentFolderIds></m:FindFolder>"""
            )
            page = root.find(".//m:RootFolder", NS)
            if page is None:
                raise RuntimeError("FindFolder: отсутствует RootFolder")
            for folder in page.findall("./t:Folders/*", NS):
                fid = folder.find("t:FolderId", NS)
                if fid is not None:
                    folders.append(
                        (
                            f'<t:FolderId Id={quoteattr(fid.attrib["Id"])}/>',
                            txt(folder, "t:DisplayName"),
                        )
                    )
            if page.attrib.get("IncludesLastItemInRange") == "true":
                break
            nxt = int(page.attrib.get("IndexedPagingOffset", 0))
            if nxt <= offset:
                raise RuntimeError("FindFolder: неполная пагинация")
            offset = nxt
        return folders

    def find_ids(self, folder_xml, start, end, sent=False):
        field = "item:DateTimeSent" if sent else "item:DateTimeReceived"
        offset, ids = 0, []
        while True:
            root = self.call(
                f"""<m:FindItem Traversal="Shallow"><m:ItemShape><t:BaseShape>IdOnly</t:BaseShape></m:ItemShape>
            <m:IndexedPageItemView MaxEntriesReturned="100" Offset="{offset}" BasePoint="Beginning"/>
            <m:Restriction><t:And><t:IsGreaterThanOrEqualTo><t:FieldURI FieldURI="{field}"/><t:FieldURIOrConstant><t:Constant Value="{utc(start)}"/></t:FieldURIOrConstant></t:IsGreaterThanOrEqualTo>
            <t:IsLessThan><t:FieldURI FieldURI="{field}"/><t:FieldURIOrConstant><t:Constant Value="{utc(end)}"/></t:FieldURIOrConstant></t:IsLessThan></t:And></m:Restriction>
            <m:SortOrder><t:FieldOrder Order="Ascending"><t:FieldURI FieldURI="{field}"/></t:FieldOrder></m:SortOrder>
            <m:ParentFolderIds>{folder_xml}</m:ParentFolderIds></m:FindItem>"""
            )
            page = root.find(".//m:RootFolder", NS)
            if page is None:
                raise RuntimeError("FindItem: отсутствует RootFolder")
            ids.extend(n.attrib["Id"] for n in page.findall("./t:Items/*/t:ItemId", NS))
            if page.attrib.get("IncludesLastItemInRange") == "true":
                break
            nxt = int(page.attrib.get("IndexedPagingOffset", 0))
            if nxt <= offset:
                raise RuntimeError("FindItem: неполная пагинация")
            offset = nxt
        return list(dict.fromkeys(ids))

    def get_items(self, ids, folder, sent):
        fields = [
            "item:Subject",
            "item:Body",
            "item:DateTimeReceived",
            "item:DateTimeSent",
            "item:Attachments",
            "item:WebClientReadFormQueryString",
            "item:ConversationId",
            "message:From",
            "message:ToRecipients",
            "message:CcRecipients",
            "message:InternetMessageId",
            "message:InReplyTo",
        ]
        shape = "".join(f'<t:FieldURI FieldURI="{f}"/>' for f in fields)
        root = self.call(
            "<m:GetItem><m:ItemShape><t:BaseShape>IdOnly</t:BaseShape><t:BodyType>Text</t:BodyType><t:AdditionalProperties>"
            + shape
            + "</t:AdditionalProperties></m:ItemShape><m:ItemIds>"
            + "".join(f"<t:ItemId Id={quoteattr(i)}/>" for i in ids)
            + "</m:ItemIds></m:GetItem>"
        )
        items = root.findall(".//m:Items/*", NS)
        if len(items) != len(ids):
            raise RuntimeError("GetItem вернул не все сообщения; отчёт не сформирован")
        result = []
        for item in items:
            eid = item.find("t:ItemId", NS).attrib["Id"]
            internet_id = txt(item, "t:InternetMessageId")
            attachments = []
            for att in item.findall("t:Attachments/*", NS):
                aid = att.find("t:AttachmentId", NS)
                if aid is None:
                    continue
                attachments.append(
                    {
                        "ews_id": aid.attrib["Id"],
                        "name": txt(att, "t:Name"),
                        "size": int(txt(att, "t:Size") or 0),
                        "inline": txt(att, "t:IsInline") == "true",
                        "content_id": txt(att, "t:ContentId"),
                        "kind": att.tag.rsplit("}", 1)[-1],
                    }
                )
            conv = item.find("t:ConversationId", NS)
            result.append(
                dict(
                    id=hashlib.sha256((internet_id or eid).encode()).hexdigest(),
                    ews_id=eid,
                    internet_id=internet_id,
                    subject=txt(item, "t:Subject"),
                    body=txt(item, "t:Body"),
                    date=txt(item, "t:DateTimeSent" if sent else "t:DateTimeReceived"),
                    sender=" ".join(
                        filter(
                            None,
                            [
                                txt(item, "t:From/t:Mailbox/t:Name"),
                                txt(item, "t:From/t:Mailbox/t:EmailAddress"),
                            ],
                        )
                    ),
                    recipients=[
                        n.text or ""
                        for n in item.findall(
                            "t:ToRecipients/t:Mailbox/t:EmailAddress", NS
                        )
                    ],
                    cc=[
                        n.text or ""
                        for n in item.findall(
                            "t:CcRecipients/t:Mailbox/t:EmailAddress", NS
                        )
                    ],
                    conversation_id=conv.attrib.get("Id", "")
                    if conv is not None
                    else "",
                    in_reply_to=txt(item, "t:InReplyTo"),
                    folder=folder,
                    sent=sent,
                    url=txt(item, "t:WebClientReadFormQueryString"),
                    attachments=attachments,
                )
            )
        return result

    def collect(self, period, progress=lambda s: None):
        start, end = bounds(period)
        messages = {}
        for distinguished in ("inbox", "sentitems"):
            for folder_xml, name in self.folders(distinguished):
                ids = self.find_ids(
                    folder_xml, start, end, distinguished == "sentitems"
                )
                progress(f"Exchange: {name}, писем {len(ids)}")
                count = 0
                for offset in range(0, len(ids), 25):
                    for msg in self.get_items(
                        ids[offset : offset + 25], name, distinguished == "sentitems"
                    ):
                        messages[msg["id"]] = msg
                        count += 1
                self.coverage["folders"].append(
                    {
                        "name": name,
                        "root": distinguished,
                        "found": len(ids),
                        "read": count,
                    }
                )
        self.coverage["complete"] = True
        return sorted(messages.values(), key=lambda m: (m["date"], m["id"]))

    def attachment(self, aid):
        root = self.call(
            f"<m:GetAttachment><m:AttachmentShape/><m:AttachmentIds><t:AttachmentId Id={quoteattr(aid)}/></m:AttachmentIds></m:GetAttachment>"
        )
        node = root.find(".//t:FileAttachment/t:Content", NS)
        if node is None or not node.text:
            raise ValueError("Вложение не является доступным файлом")
        return base64.b64decode(node.text, validate=True)

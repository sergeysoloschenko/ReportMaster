"""Read the provided DOCX as a template and a source, without trusting its filename period."""
import hashlib
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def read_reference(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    tables = []
    for table in root.findall("./w:body/w:tbl", NS):
        rows = []
        for row in table.findall("w:tr", NS):
            rows.append(
                [
                    "\n".join(
                        "".join(t.text or "" for t in p.findall(".//w:t", NS))
                        for p in c.findall("w:p", NS)
                    ).strip()
                    for c in row.findall("w:tc", NS)
                ]
            )
        tables.append(rows)
    task_index = next(
        i
        for i, rows in enumerate(tables)
        if rows and "Наименование выполненных" in " ".join(rows[0])
    )
    own = [
        dict(number=r[0], text=r[1], dates=r[2], owner=r[3], contract=r[4])
        for r in tables[task_index]
        if len(r) == 5 and "солощенко" in r[3].lower()
    ]
    if not own:
        raise ValueError("В отчёте не найдены строки Солощенко")
    risk_indices = [
        i
        for i, rows in enumerate(tables)
        if any("Динамика изменений" in " ".join(r) for r in rows[:3])
    ]
    risks = [
        dict(number=r[0], text=r[1], characteristics=r[2], dynamics=r[3], response=r[4])
        for i in risk_indices
        for r in tables[i][3:]
        if len(r) == 5 and re.match(r"^\d+\.", r[0])
    ]
    examples = [
        r[1]
        for r in tables[task_index]
        if len(r) == 5 and "солощенко" not in r[3].lower() and "Результат" in r[1]
    ][:8]
    return dict(
        tasks=own,
        risks=risks,
        style_examples=examples,
        task_table_index=task_index,
        risk_table_index=risk_indices[0] if risk_indices else None,
        source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        warnings=[
            "Исходный файл содержит смешанные даты. Период исходной версии задан пользователем; плановые сроки не являются фактом выполнения."
        ],
    )

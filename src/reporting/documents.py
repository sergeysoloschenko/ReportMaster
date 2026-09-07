"""Export only the task and risk tables, preserving the reference table geometry."""
from copy import deepcopy
from datetime import timedelta
from .periods import bounds
from pathlib import Path
import hashlib
import json
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def replace(cell, text):
    paragraph = cell.paragraphs[0]
    ppr = deepcopy(paragraph._p.pPr) if paragraph._p.pPr is not None else None
    rpr = (
        deepcopy(paragraph.runs[0]._r.rPr)
        if paragraph.runs and paragraph.runs[0]._r.rPr is not None
        else None
    )
    cell.text = ""
    p = cell.paragraphs[0]
    if ppr is not None:
        p._p.insert(0, ppr)
    run = p.add_run(str(text or ""))
    if rpr is not None:
        run._r.insert(0, rpr)


def content_hash(report):
    return hashlib.sha256(
        json.dumps(
            {k: report[k] for k in ("period", "tasks", "risks")},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def render_fragment(report, template_path, reference, output):
    doc = Document(template_path)
    original = list(doc.tables)
    task = deepcopy(original[reference["task_table_index"]]._tbl)
    risk = (
        deepcopy(original[reference["risk_table_index"]]._tbl)
        if reference.get("risk_table_index") is not None
        else None
    )
    body = doc._element.body
    # Keep the section geometry attached to the source task table when available.
    # A section break belongs to the content preceding it. Find the next
    # section properties after the source task table (landscape in this reference).
    source_table = original[reference["task_table_index"]]._tbl
    sect = None
    for sibling in source_table.itersiblings():
        candidate = (
            sibling
            if sibling.tag == qn("w:sectPr")
            else sibling.find(".//" + qn("w:sectPr"))
        )
        if candidate is not None:
            sect = deepcopy(candidate)
            break
    if sect is None:
        sect = deepcopy(doc.sections[-1]._sectPr)
    for node in list(sect):
        if node.tag in (qn("w:headerReference"), qn("w:footerReference")):
            sect.remove(node)
    for child in list(body):
        body.remove(child)
    body.append(task)
    if risk is not None:
        p = OxmlElement("w:p")
        body.append(p)
        body.append(risk)
    body.append(sect)
    # Do not ship unrelated logos, comments or custom XML from the full source report.
    for rel_id, rel in list(doc.part.rels.items()):
        if rel.reltype.rsplit("/", 1)[-1] in {
            "header",
            "footer",
            "image",
            "customXml",
            "hyperlink",
        }:
            doc.part.drop_rel(rel_id)
    for node in list(doc.settings.element):
        if node.tag in (qn("w:trackRevisions"), qn("w:documentProtection")):
            doc.settings.element.remove(node)
    doc.core_properties.title = ""
    doc.core_properties.subject = ""
    doc.core_properties.comments = ""
    doc.core_properties.author = "Спектрум Холдинг"
    doc.core_properties.last_modified_by = "ReportMaster"
    table = doc.tables[0]
    proto = deepcopy(table.rows[3]._tr)
    # Preserve the actual two header rows. Populate new content only.
    for row in list(table.rows)[2:]:
        table._tbl.remove(row._tr)
    contracts = {r["number"]: r for r in reference["tasks"]}
    grouped = {}
    for item in report["tasks"]:
        if item.get("include_in_report", True):
            grouped.setdefault(item["section"], []).append(item)
    for number, items in sorted(grouped.items()):
        table._tbl.append(deepcopy(proto))
        cells = table.rows[-1].cells
        source = contracts.get(number, {})
        text = "\n\n".join(
            f"{x['title']}. {x['result']} Статус: {x['status']}." for x in items
        )
        start, end = bounds(report["period"])
        dates = (
            start.strftime("%d.%m.%Y")
            + "–"
            + (end - timedelta(days=1)).strftime("%d.%m.%Y")
        )
        values = [
            number,
            text,
            dates,
            source.get("owner", "Солощенко С.С."),
            source.get("contract", ""),
        ]
        for cell, value in zip(cells, values):
            replace(cell, value)
    if risk is not None:
        table = doc.tables[1]
        proto = next(
            deepcopy(row._tr) for row in table.rows[3:] if len(row._tr.tc_lst) == 5
        )
        for row in list(table.rows)[3:]:
            table._tbl.remove(row._tr)
        for item in report["risks"]:
            if not item.get("include_in_report", True):
                continue
            table._tbl.append(deepcopy(proto))
            values = [
                item["number"],
                item["title"],
                item.get("characteristics", ""),
                item["dynamics"],
                f"{item['status']}. {item['response']}",
            ]
            for cell, value in zip(table.rows[-1].cells, values):
                replace(cell, value)
    for table in doc.tables:
        for row in table.rows:
            # Remove fixed heights inherited from a much longer source row.
            for height in row._tr.findall("./w:trPr/w:trHeight", row._tr.nsmap):
                height.getparent().remove(height)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    return output

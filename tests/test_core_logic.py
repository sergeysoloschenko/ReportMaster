from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from src.analyzers.categorizer import Categorizer
from src.analyzers.categorizer import ThreadCategory
from src.analyzers.monthly_directions import MonthlyDirectionCategorizer
from src.analyzers.thread_insights import ThreadInsight, ThreadInsightAnalyzer
from src.generators.attachment_manager import AttachmentManager
from src.generators.word_generator import WordReportGenerator
from src.processors.deduplicator import deduplicate_messages, deduplicate_upload_paths, deduplicate_uploads
from src.processors.document_extractor import DocumentExtractor
from src.processors.source_document import SourceDocumentLoader
from src.parsers.msg_parser import EmailMessage
from src.parsers.thread_builder import ThreadBuilder


class DummyAPIClient:
    def __init__(self):
        self.client = object()

    def categorize_thread(self, subject, keywords, sample_content):
        return {"category": "Общая категория", "description": "test"}

    def triage_thread_relevance(self, thread_payload, directions):
        return {
            "include_in_report": True,
            "direction_id": "DIR_004",
            "relevance": "high",
            "reason": "Dyer comments are relevant architect work.",
            "confidence": "high",
        }

    def analyze_thread_insight(self, thread_payload, directions):
        return {
            "direction_id": "DIR_004",
            "summary": "Dyer направил комментарии по проектным решениям.",
            "actions": ["Dyer направил комментарии"],
            "decisions": [],
            "open_questions": ["Требуется ответ проектной команды"],
            "risks": [],
            "next_steps": ["Подготовить консолидированный ответ"],
            "documents": ["comments.xlsx"],
            "parties": ["Dyer Group"],
            "confidence": "high",
        }


class ExcludingAPIClient(DummyAPIClient):
    def triage_thread_relevance(self, thread_payload, directions):
        return {
            "include_in_report": False,
            "direction_id": "DIR_006",
            "relevance": "none",
            "reason": "Service notification only.",
            "confidence": "high",
        }


def _make_thread(subject: str, body: str = "Body text"):
    msg = SimpleNamespace(
        body=body,
        sender="a@example.com",
        recipients=["b@example.com"],
        cc=[],
    )
    return SimpleNamespace(subject=subject, messages=[msg], message_count=1)


def test_categorizer_merges_same_category_names():
    config = {"categorization": {"ai_labeling": {"enabled": True}}}
    categorizer = Categorizer(config, DummyAPIClient())
    threads = [_make_thread("One"), _make_thread("Two")]

    categories = categorizer.categorize_threads(threads)

    assert len(categories) == 1
    assert categories[0].thread_count == 2


def test_attachment_manager_sanitizes_filename(tmp_path: Path):
    manager = AttachmentManager({})
    category_dir = tmp_path / "Attachments" / "001_test"
    category_dir.mkdir(parents=True)
    stats = {"total_attachments": 0, "categories_with_attachments": 0, "saved_files": []}

    manager._save_attachment(
        {"filename": "../evil.txt", "data": b"secret"},
        category_dir,
        stats,
    )

    saved = list(category_dir.glob("*"))
    assert len(saved) == 1
    assert saved[0].name == "evil.txt"
    assert stats["total_attachments"] == 1


def test_thread_builder_splits_same_subject_with_low_participant_overlap():
    config = {"email": {"thread_grouping": {"similarity_threshold": 0.7, "max_gap_days": 10}}}
    builder = ThreadBuilder(config)

    now = datetime.now()
    messages = [
        SimpleNamespace(subject="RE: Update", sender="a@x.com", recipients=["b@x.com"], cc=[], date=now, has_attachments=False, attachment_count=0),
        SimpleNamespace(subject="RE: Update", sender="c@x.com", recipients=["d@x.com"], cc=[], date=now + timedelta(hours=2), has_attachments=False, attachment_count=0),
    ]

    threads = builder.build_threads(messages)
    assert len(threads) == 2


def test_thread_builder_links_messages_by_rfc_headers_before_subject_matching():
    builder = ThreadBuilder({})
    now = datetime.now()
    messages = [
        SimpleNamespace(
            subject="Initial commercial terms",
            sender="a@x.com",
            recipients=["b@x.com"],
            cc=[],
            date=now,
            has_attachments=False,
            attachment_count=0,
            message_id="root@example",
            in_reply_to="",
            references=[],
        ),
        SimpleNamespace(
            subject="Changed topic line",
            sender="b@x.com",
            recipients=["a@x.com"],
            cc=[],
            date=now + timedelta(hours=1),
            has_attachments=False,
            attachment_count=0,
            message_id="reply@example",
            in_reply_to="root@example",
            references=["root@example"],
        ),
    ]

    threads = builder.build_threads(messages)

    assert len(threads) == 1
    assert threads[0].message_count == 2


def test_msg_parser_accepts_header_message_object():
    headers = Message()
    headers["Message-ID"] = "<root@example>"
    headers["In-Reply-To"] = "<parent@example>"
    headers["References"] = "<grandparent@example> <parent@example>"
    msg = SimpleNamespace(header=headers, messageId="")
    email = EmailMessage.__new__(EmailMessage)

    email._extract_header_metadata(msg)

    assert email.message_id == "root@example"
    assert email.in_reply_to == "parent@example"
    assert email.references == ["grandparent@example", "parent@example"]


def test_msg_parser_can_skip_attachment_text_extraction():
    attachment = SimpleNamespace(longFilename="notes.txt", shortFilename="", data=b"important text")
    msg = SimpleNamespace(attachments=[attachment])
    email = EmailMessage.__new__(EmailMessage)
    email.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    email.document_extractor = DocumentExtractor()

    attachments = email._extract_attachments(msg, extract_text=False)

    assert len(attachments) == 1
    assert attachments[0]["filename"] == "notes.txt"
    assert attachments[0]["data"] == b"important text"
    assert attachments[0]["extracted_text"] == ""
    assert attachments[0]["extraction_status"] == "not_needed"


def test_attachment_folder_name_matches_report_section_format(tmp_path: Path):
    manager = AttachmentManager({})
    category = ThreadCategory("CAT_001", "Согласование ТЗ")

    msg = SimpleNamespace(
        has_attachments=True,
        attachments=[{"filename": "spec.pdf", "data": b"pdf-bytes"}],
    )
    thread = SimpleNamespace(messages=[msg], total_attachments=1)
    category.add_thread(thread)

    stats = manager.save_attachments([category], tmp_path)

    folder = tmp_path / "Attachments" / "1_Согласование ТЗ"
    assert folder.exists()
    assert (folder / "spec.pdf").exists()
    assert stats["total_attachments"] == 1


def test_monthly_direction_categorizer_uses_fixed_directions():
    now = datetime.now()
    message = SimpleNamespace(
        subject="Dyer design comments",
        body="Dyer sent updated comments",
        analysis_body="Dyer sent updated comments",
        sender="lead@dyergroup.ru",
        recipients=["pm@example.com"],
        cc=[],
        date=now,
        has_attachments=False,
        attachment_count=0,
        attachments=[],
    )
    thread = SimpleNamespace(
        subject="Dyer design comments",
        messages=[message],
        participants={"lead@dyergroup.ru", "pm@example.com"},
        message_count=1,
        total_attachments=0,
    )

    categories = MonthlyDirectionCategorizer().categorize_threads([thread])

    assert len(categories) == 6
    dyer_category = next(category for category in categories if category.name == "Работа с архитектором проекта")
    assert dyer_category.thread_count == 1


def test_thread_insight_analyzer_creates_llm_card():
    now = datetime.now()
    message = SimpleNamespace(
        subject="Dyer comments",
        body="Please review Dyer comments attached",
        analysis_body="Please review Dyer comments attached",
        sender="lead@dyergroup.ru",
        recipients=["pm@example.com"],
        cc=[],
        date=now,
        has_attachments=True,
        attachments=[{"filename": "comments.xlsx", "size": 100, "extracted_text": "Facade comments"}],
        message_id="thread-1@example",
    )
    thread = SimpleNamespace(
        thread_id="THREAD_001",
        subject="Dyer comments",
        messages=[message],
        participants={"lead@dyergroup.ru", "pm@example.com"},
        message_count=1,
        total_attachments=1,
    )

    insight = ThreadInsightAnalyzer({}, DummyAPIClient()).analyze_thread(thread)

    assert insight.direction_id == "DIR_004"
    assert insight.direction_name == "Работа с архитектором проекта"
    assert insight.documents == ["comments.xlsx"]
    assert insight.source_thread is thread


def test_thread_insight_analyzer_excludes_irrelevant_threads():
    now = datetime.now()
    message = SimpleNamespace(
        subject="Automatic notification",
        body="This is an automatic service notification.",
        analysis_body="This is an automatic service notification.",
        sender="noreply@example.com",
        recipients=["pm@example.com"],
        cc=[],
        date=now,
        has_attachments=False,
        attachments=[],
        message_id="notification@example",
    )
    thread = SimpleNamespace(
        thread_id="THREAD_001",
        subject="Automatic notification",
        messages=[message],
        participants={"noreply@example.com", "pm@example.com"},
        message_count=1,
        total_attachments=0,
    )

    analyzer = ThreadInsightAnalyzer({}, ExcludingAPIClient())

    insights = analyzer.analyze_threads([thread])

    assert insights == []
    assert analyzer.last_triage_stats["excluded_threads"] == 1


def test_monthly_direction_categorizer_groups_thread_insights():
    thread = SimpleNamespace(message_count=1, total_attachments=0)
    insight = ThreadInsight(
        thread_id="THREAD_001",
        thread_hash="hash",
        subject="Dyer comments",
        direction_id="DIR_004",
        direction_name="Работа с архитектором проекта",
        summary="Dyer comments",
        source_thread=thread,
    )

    categories = MonthlyDirectionCategorizer().categorize_insights([insight])

    dyer_category = next(category for category in categories if category.category_id == "DIR_004")
    assert dyer_category.thread_count == 1
    assert dyer_category.insights == [insight]


def test_word_generator_includes_detailed_thread_items():
    generator = WordReportGenerator({})
    text = generator._build_investor_cell_text({
        "category_name": "Работа с архитектором проекта",
        "message_count": 3,
        "overview": "За период обработаны комментарии Dyer по фасадам.",
        "actions": ["Dyer направил comments.xlsx", "Команда подготовила ответ"],
        "result": "Вопрос находится в работе.",
        "parties": "Dyer Group, Спектрум Холдинг",
        "remarks": "Открыт вопрос по фасадным решениям.",
        "recommendations": "Подготовить консолидированный ответ.",
        "thread_items": [
            {
                "subject": "Dyer comments",
                "date_range": "01.05.2026-03.05.2026",
                "summary": "Обсуждались комментарии по фасадам.",
                "status": "В работе",
            }
        ],
    })

    assert "Ключевые действия" in text
    assert "Существенные цепочки" in text
    assert "Dyer comments" in text


def test_word_generator_accepts_llm_list_fields():
    generator = WordReportGenerator({})
    text = generator._build_investor_cell_text({
        "category_name": "Работа с консультантами проекта",
        "message_count": 2,
        "overview": ["Обработаны комментарии консультантов.", "Подготовлен ответ."],
        "actions": ["Направлены материалы"],
        "result": ["В работе"],
        "parties": ["Спектрум Холдинг", "Dyer Group"],
        "remarks": ["Есть открытый вопрос"],
        "recommendations": ["Подготовить ответ"],
    })

    assert "Спектрум Холдинг; Dyer Group" in text
    assert "Есть открытый вопрос" in text
    assert "Подготовить ответ" in text


def test_deduplicate_uploads_skips_identical_file_bytes():
    unique, stats = deduplicate_uploads([
        ("one.msg", b"same"),
        ("copy.msg", b"same"),
        ("other.msg", b"different"),
    ])

    assert len(unique) == 2
    assert stats.input_count == 3
    assert stats.unique_count == 2
    assert stats.duplicate_count == 1
    assert stats.duplicate_names == ["copy.msg"]


def test_deduplicate_upload_paths_skips_identical_files(tmp_path: Path):
    one = tmp_path / "one.msg"
    copy = tmp_path / "copy.msg"
    other = tmp_path / "other.msg"
    one.write_bytes(b"same")
    copy.write_bytes(b"same")
    other.write_bytes(b"different")

    unique, stats = deduplicate_upload_paths([
        ("one.msg", one),
        ("copy.msg", copy),
        ("other.msg", other),
    ])

    assert [name for name, _, _ in unique] == ["one.msg", "other.msg"]
    assert stats.input_count == 3
    assert stats.unique_count == 2
    assert stats.duplicate_count == 1
    assert stats.duplicate_names == ["copy.msg"]


def test_deduplicate_messages_uses_normalized_content_when_message_id_missing():
    now = datetime.now()
    messages = [
        SimpleNamespace(subject="RE: Status", sender="a@x.com", date=now, message_id="", body="Hello   world"),
        SimpleNamespace(subject="Status", sender="a@x.com", date=now, message_id="", body="hello world"),
    ]

    unique, stats = deduplicate_messages(messages)

    assert len(unique) == 1
    assert stats.duplicate_count == 1


def test_document_extractor_reads_text_file():
    extractor = DocumentExtractor(max_chars=20)
    extracted = extractor.extract_bytes("notes.txt", "Привет\nмир".encode("utf-8"))

    assert extracted.has_text
    assert "Привет" in extracted.text
    assert extracted.skipped_reason is None


def test_source_document_loader_creates_pipeline_message(tmp_path: Path):
    document = tmp_path / "brief.txt"
    document.write_text("Контекст проекта и список решений", encoding="utf-8")

    messages = SourceDocumentLoader().load_files([document])

    assert len(messages) == 1
    assert messages[0].subject == "Документ: brief.txt"
    assert "Контекст проекта" in messages[0].analysis_body

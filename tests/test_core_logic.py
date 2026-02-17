from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.analyzers.categorizer import Categorizer
from src.generators.attachment_manager import AttachmentManager
from src.parsers.thread_builder import ThreadBuilder


class DummyAPIClient:
    def __init__(self):
        self.client = object()

    def categorize_thread(self, subject, keywords, sample_content):
        return {"category": "Общая категория", "description": "test"}


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

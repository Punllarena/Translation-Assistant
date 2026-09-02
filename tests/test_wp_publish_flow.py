"""Tests for translation_assistant/ui/wp_publish_flow.py."""
import sqlite3

import pytest

from translation_assistant.db import Database
from translation_assistant.ui import wp_publish_flow as wpf


@pytest.fixture
def db():
    return Database(":memory:", _conn=sqlite3.connect(":memory:"))


def _doc_with_lines(db, translated=("Bonjour",), series_order=1):
    doc_id = db.create_document(
        "Ch", series_title="Nov", series_order=series_order, chapter_title="Chapter 1"
    )
    db.save_lines(doc_id, [
        {"line_number": i, "prefix": "%", "raw_text": f"src{i}", "translated_text": t}
        for i, t in enumerate(translated)
    ])
    db.set_series_wp_meta("Nov", series_slug="nov", series_title_short="N")
    return doc_id


class TestBuildJob:
    def test_happy_path_populates_lines_and_meta(self, db):
        doc_id = _doc_with_lines(db)
        job = wpf.build_job(db, _Settings(), doc_id)
        assert job.doc_id == doc_id
        assert job.series_order == 1
        assert [ln["translated_text"] for ln in job.lines] == ["Bonjour"]
        assert job.series_meta["series_slug"] == "nov"
        assert job.cover_image is None
        assert job.inline_images == []

    def test_raises_when_nothing_translated(self, db):
        doc_id = _doc_with_lines(db, translated=("", "   "))
        with pytest.raises(wpf.PublishJobError):
            wpf.build_job(db, _Settings(), doc_id)

    def test_password_none_when_disabled(self, db):
        doc_id = _doc_with_lines(db, series_order=5)
        job = wpf.build_job(db, _Settings(wp_password_enabled=False), doc_id)
        assert job.password is None
        assert job.unlock_chapter_index is None

    def test_password_generated_when_enabled_and_past_unlock(self, db):
        doc_id = _doc_with_lines(db, series_order=5)
        job = wpf.build_job(
            db, _Settings(wp_password_enabled=True, wp_unlock_after=2), doc_id
        )
        assert job.password is not None and len(job.password) == 12


class TestJobToPayload:
    def test_forwards_fields_into_build_payload(self, db, monkeypatch):
        doc_id = _doc_with_lines(db)
        job = wpf.build_job(db, _Settings(), doc_id)
        captured = {}
        import translation_assistant.wp_publisher as wp
        real = wp.build_payload
        monkeypatch.setattr(
            wp, "build_payload",
            lambda *a, **k: captured.update(k) or real(*a, **k),
        )
        wpf.job_to_payload(job, "key", scheduled_date="2026-09-03T09:00:00Z", attribution=False)
        assert captured["scheduled_date"] == "2026-09-03T09:00:00Z"
        assert captured["attribution"] is False
        assert captured["images"] == job.inline_images
        assert captured["cover"] is job.cover_image
        assert captured["previous_chapter_index"] == job.prev_wp_chapter_index


class TestPersistPublishResult:
    def test_writes_publish_status_when_created(self, db):
        doc_id = _doc_with_lines(db)
        wrote = wpf.persist_publish_result(
            db, doc_id, {"created": True, "post_url": "https://x/p1/"},
            scheduled_date=None, chapter_index=1,
        )
        assert wrote is True
        info = db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "publish"
        assert info["wp_post_url"] == "https://x/p1/"
        assert info["wp_chapter_index"] == 1

    def test_writes_future_status_when_scheduled(self, db):
        doc_id = _doc_with_lines(db)
        wpf.persist_publish_result(
            db, doc_id, {"updated": True, "post_url": "https://x/p1/"},
            scheduled_date="2026-09-03T09:00:00Z", chapter_index=2,
        )
        info = db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "future"
        assert info["wp_date"] == "2026-09-03T09:00:00Z"

    def test_noop_when_neither_created_nor_updated(self, db):
        doc_id = _doc_with_lines(db)
        db.set_document_wp_status(doc_id, "future", "https://old/", "2026-01-01T00:00:00Z", 1)
        wrote = wpf.persist_publish_result(
            db, doc_id, {"created": False}, scheduled_date=None, chapter_index=1,
        )
        assert wrote is False
        assert db.get_document_wp_status(doc_id)["wp_status"] == "future"


class _Settings:
    """Minimal stand-in for AppSettings — only the wp_* attrs build_job reads."""
    def __init__(self, **over):
        self.wp_password_enabled = over.get("wp_password_enabled", False)
        self.wp_unlock_after = over.get("wp_unlock_after", 0)
        self.wp_attribution_enabled = over.get("wp_attribution_enabled", True)

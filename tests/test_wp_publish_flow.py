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


class TestEnsureWpConfig:
    def test_returns_pair_when_already_configured(self, monkeypatch):
        s = _Settings()
        s.wp_endpoint_url = "https://ex.com"
        s.wp_api_key = "key"
        assert wpf.ensure_wp_config(s, None) == ("https://ex.com", "key")

    def test_pops_dialog_and_returns_none_on_cancel(self, monkeypatch):
        s = _Settings()
        s.wp_endpoint_url = ""
        s.wp_api_key = ""
        monkeypatch.setattr(wpf, "WPSettingsDialog", lambda *a, **k: _RejectDialog())
        assert wpf.ensure_wp_config(s, None) is None


class TestEnsureSeriesWpMeta:
    def test_returns_meta_when_fields_set(self, db):
        db.set_series_wp_meta("Nov", series_slug="nov", series_title_short="N")
        meta = wpf.ensure_series_wp_meta(db, _Settings(), "Nov", None)
        assert meta["series_slug"] == "nov"

    def test_returns_none_when_still_unset_after_dialog(self, db, monkeypatch):
        monkeypatch.setattr(wpf, "SeriesManagerDialog", lambda *a, **k: _RejectDialog())
        monkeypatch.setattr(wpf, "remember_dialog_geometry", lambda *a, **k: None)
        assert wpf.ensure_series_wp_meta(db, _Settings(), "Nov", None) is None


class _RejectDialog:
    def exec(self):
        return 0


class TestPublishConfirmDialog:
    def _job(self, db, **over):
        doc_id = _doc_with_lines(db, series_order=over.get("series_order", 2))
        return wpf.build_job(db, _Settings(), doc_id), doc_id

    def test_scheduled_date_none_when_unchecked(self, qapp, db, monkeypatch):
        monkeypatch.setattr(wpf, "StatusCheckWorker", _NoRunWorker)
        job, _ = self._job(db)
        dlg = wpf.PublishConfirmDialog(job, db, _Settings(), "https://ex.com", "key")
        assert dlg.scheduled_date_utc() is None

    def test_scheduled_date_iso_when_checked(self, qapp, db, monkeypatch):
        monkeypatch.setattr(wpf, "StatusCheckWorker", _NoRunWorker)
        job, _ = self._job(db)
        dlg = wpf.PublishConfirmDialog(job, db, _Settings(), "https://ex.com", "key")
        dlg._schedule_cb.setChecked(True)
        s = dlg.scheduled_date_utc()
        assert s is not None and s.endswith("Z") and "T" in s

    def test_warns_when_already_published(self, qapp, db, monkeypatch):
        monkeypatch.setattr(wpf, "StatusCheckWorker", _NoRunWorker)
        job, doc_id = self._job(db)
        db.set_document_wp_status(doc_id, "publish", "https://ex.com/c/", None, 2)
        job = wpf.build_job(db, _Settings(), doc_id)
        dlg = wpf.PublishConfirmDialog(job, db, _Settings(), "https://ex.com", "key")
        from PySide6.QtWidgets import QLabel
        texts = [w.text() for w in dlg.findChildren(QLabel)]
        assert any("overwrite" in t.lower() for t in texts)


class _NoRunWorker:
    """StatusCheckWorker stand-in that never touches the network."""
    def __init__(self, *a, **k):
        pass
    def start(self):
        pass
    def quit(self):
        pass
    def wait(self, *a, **k):
        pass
    @property
    def succeeded(self):
        return self
    @property
    def error(self):
        return self
    def connect(self, *a, **k):
        pass


class _Settings:
    """Minimal stand-in for AppSettings — only the wp_* attrs build_job reads."""
    def __init__(self, **over):
        self.wp_password_enabled = over.get("wp_password_enabled", False)
        self.wp_unlock_after = over.get("wp_unlock_after", 0)
        self.wp_attribution_enabled = over.get("wp_attribution_enabled", True)
        self.wp_endpoint_url = over.get("wp_endpoint_url", "")
        self.wp_api_key = over.get("wp_api_key", "")
        self.wp_default_schedule_time = over.get("wp_default_schedule_time", "")
        self.wp_chapters_per_day = over.get("wp_chapters_per_day", 1)
        self.wp_schedule_scope_global = over.get("wp_schedule_scope_global", True)

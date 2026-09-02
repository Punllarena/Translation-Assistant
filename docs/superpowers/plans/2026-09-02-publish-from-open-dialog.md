# Publish / Schedule from Open Document Dialog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish or schedule a chapter to WordPress directly from `OpenDocumentDialog` — one selected chapter via a context-menu item, or many selected chapters via a batch dialog — reusing one publish code path.

**Architecture:** Extract the publish machinery currently inlined in `TranslationAssistantWidget._on_publish_wp()` into a new caller-agnostic module `translation_assistant/ui/wp_publish_flow.py` (Qt dialogs + `QThread` workers + pure job-prep helpers). `main_widget` becomes a thin delegator. `dlg_open` gains a single-chapter entry that calls the shared `run_single_publish()` and a batch entry with its own dialog + worker that loops the shared `build_job()` / `job_to_payload()` / `wp_publisher.publish()`.

**Tech Stack:** Python 3, PySide6 (Qt), stdlib `urllib` (via existing `wp_publisher`), pytest. SQLite through `translation_assistant.db.Database`.

**Spec:** `docs/superpowers/specs/2026-09-02-publish-from-open-dialog-design.md`

## Global Constraints

- **No Qt imports in `core.py`** — not touched here; `wp_publish_flow.py` *does* import Qt and lives in `ui/`.
- **No `sqlite3` outside `db.py`** — all DB access via the injected `Database` instance.
- **No changes to `translation_assistant/wp_publisher.py`** — its 68 tests must stay green untouched.
- **`translation_assistant/ui/main_window.py` is legacy** — do not modify it.
- **Settings only via `AppSettings`** — read `settings.wp_endpoint_url`, `settings.wp_api_key`, `settings.wp_default_schedule_time`, `settings.wp_chapters_per_day`, `settings.wp_schedule_scope_global`, `settings.wp_password_enabled`, `settings.wp_unlock_after`, `settings.wp_attribution_enabled`.
- **Test command:** `source .venv/bin/activate` then `pytest`. Single file: `pytest tests/test_wp_publish_flow.py -q`.
- **Full suite must pass** at the end of every task (not just new tests).
- **Commit after every task.** Stage only the files the task names (`git add <path> <path>`), never `git add -A` — the working tree carries unrelated in-flight changes.

---

## File Structure

| File | Responsibility |
|---|---|
| `translation_assistant/ui/wp_publish_flow.py` | **new.** All shared publish machinery: `PublishWorker` / `StatusCheckWorker` (`QThread`), `PublishJobError`, `PublishJob` dataclass, `build_job()`, `job_to_payload()`, `persist_publish_result()`, `ensure_wp_config()`, `ensure_series_wp_meta()`, `PublishConfirmDialog`, `show_publish_result()`, `run_single_publish()`. |
| `translation_assistant/ui/main_widget.py` | `_on_publish_wp()` shrinks to a 3-line delegator. Worker classes deleted, re-imported under old private names. `_on_publish_done` / `_on_publish_error` deleted. |
| `translation_assistant/ui/dlg_open.py` | Two context-menu items + dispatch; `_on_publish_batch()`; `_BatchPublishDialog`; `_BatchPublishWorker`. |
| `tests/test_wp_publish_flow.py` | **new.** Unit tests for every helper + `PublishConfirmDialog` + `run_single_publish`. |
| `tests/test_dlg_open.py` | Context-menu presence/enablement + dispatch + batch tests. |
| `tests/test_main_window.py` | Retarget `TestPublishWpConfirmCopy` (3 tests) and `TestOnPublishDone` (3 tests) to the moved symbols. |

---

## Task 1: Move workers + add job-prep helpers to `wp_publish_flow.py`

**Files:**
- Create: `translation_assistant/ui/wp_publish_flow.py`
- Modify: `translation_assistant/ui/main_widget.py:28-102` (delete `_PublishWorker`, `_StatusCheckWorker` bodies; keep `_IllustrationsPublishWorker`), add a re-import near the other `ui` imports (`main_widget.py:17`)
- Test: `tests/test_wp_publish_flow.py`

**Interfaces:**
- Consumes: `translation_assistant.wp_publisher` (`build_payload`, `compute_password_fields`, `resolve_wp_password_enabled`, `publish`, `check_status`, `WPPublishError`); `translation_assistant.imageopt.shrink_image`; `Database`; `AppSettings`.
- Produces:
  - `class PublishWorker(QThread)` — `__init__(endpoint_url: str, payload: dict, parent=None)`, signals `succeeded = Signal(dict)`, `error = Signal(str)`.
  - `class StatusCheckWorker(QThread)` — `__init__(endpoint_url: str, api_key: str, series_slug: str, chapter: int, parent=None)`, same signals.
  - `class PublishJobError(Exception)`.
  - `@dataclass(frozen=True) class PublishJob` with fields `doc_id: int`, `doc_meta: dict`, `series_meta: dict`, `lines: list[dict]`, `inline_images: list[dict]`, `cover_image: dict | None`, `password: str | None`, `unlock_chapter_index: int | None`, `prev_wp_chapter_index: int | None`, `series_order: int`, `chapter_title: str`.
  - `build_job(db: Database, settings: AppSettings, doc_id: int) -> PublishJob` — raises `PublishJobError` when no translated line exists.
  - `job_to_payload(job: PublishJob, api_key: str, *, scheduled_date: str | None, attribution: bool) -> dict`.
  - `persist_publish_result(db: Database, doc_id: int, result: dict, *, scheduled_date: str | None, chapter_index: int | None) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wp_publish_flow.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wp_publish_flow.py -q`
Expected: FAIL — `ModuleNotFoundError: translation_assistant.ui.wp_publish_flow`.

- [ ] **Step 3: Create `wp_publish_flow.py` with the workers + helpers**

```python
"""
Shared WordPress publish machinery, caller-agnostic.

Everything keys off a Database, an AppSettings, and a doc_id — never a widget's
`self`. Used by TranslationAssistantWidget (single, currently-open doc) and
OpenDocumentDialog (single selected row + batch).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

from translation_assistant.wp_publisher import (
    WPPublishError,
    build_payload,
    check_status,
    compute_password_fields,
    publish,
    resolve_wp_password_enabled,
)


class PublishWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(self, endpoint_url: str, payload: dict, parent=None) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._payload = payload

    def run(self) -> None:
        try:
            self.succeeded.emit(publish(self._endpoint_url, self._payload))
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.error.emit(str(exc))


class StatusCheckWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(
        self, endpoint_url: str, api_key: str, series_slug: str, chapter: int, parent=None
    ) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._series_slug = series_slug
        self._chapter = chapter

    def run(self) -> None:
        try:
            self.succeeded.emit(
                check_status(
                    self._endpoint_url, self._api_key, self._series_slug, self._chapter
                )
            )
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.error.emit(str(exc))


class PublishJobError(Exception):
    """Raised by build_job when a chapter cannot be published (e.g. no translation)."""


@dataclass(frozen=True)
class PublishJob:
    doc_id: int
    doc_meta: dict
    series_meta: dict
    lines: list[dict]
    inline_images: list[dict]
    cover_image: dict | None
    password: str | None
    unlock_chapter_index: int | None
    prev_wp_chapter_index: int | None
    series_order: int
    chapter_title: str


def build_job(db, settings, doc_id: int) -> PublishJob:
    doc_meta = db.get_document(doc_id)
    series_title = doc_meta["series_title"]
    series_meta = db.get_series_wp_meta(series_title)

    pw_settings = db.get_series_wp_password_settings(series_title)
    pw_enabled = resolve_wp_password_enabled(pw_settings, settings.wp_password_enabled)
    unlock_after = (
        pw_settings["wp_unlock_after"]
        if pw_settings["wp_unlock_after"] != -1
        else settings.wp_unlock_after
    )
    password = unlock_chapter_index = None
    if pw_enabled:
        password, unlock_chapter_index = compute_password_fields(
            doc_meta["series_order"], unlock_after
        )

    lines = db.get_lines(doc_id)
    if not any(ln["translated_text"].strip() for ln in lines):
        raise PublishJobError("No translated lines to publish.")

    doc_images = db.get_document_images(doc_id)
    inline_images = [im for im in doc_images if not im["is_cover"] and not im["exclude_export"]]
    cover_image = next((im for im in doc_images if im["is_cover"]), None)

    # EasyWP's proxy resets requests over ~1 MB; full-res EPUB art blows that
    # on its own. Downscale before it goes into the base64 payload.
    from translation_assistant.imageopt import shrink_image
    for im in [*inline_images, *([cover_image] if cover_image else [])]:
        shrunk = shrink_image(im["data"])
        if shrunk is not im["data"]:
            im["data"] = shrunk
            im["src_path"] = im["src_path"].rsplit(".", 1)[0] + ".jpg"

    prev_wp_chapter_index = db.get_document_wp_status(doc_id).get("wp_chapter_index")

    return PublishJob(
        doc_id=doc_id,
        doc_meta=doc_meta,
        series_meta=series_meta,
        lines=lines,
        inline_images=inline_images,
        cover_image=cover_image,
        password=password,
        unlock_chapter_index=unlock_chapter_index,
        prev_wp_chapter_index=prev_wp_chapter_index,
        series_order=doc_meta["series_order"],
        chapter_title=doc_meta["chapter_title"],
    )


def job_to_payload(job: PublishJob, api_key: str, *, scheduled_date, attribution: bool) -> dict:
    return build_payload(
        job.doc_meta,
        job.series_meta,
        job.lines,
        api_key=api_key,
        password=job.password,
        unlock_chapter_index=job.unlock_chapter_index,
        scheduled_date=scheduled_date,
        attribution=attribution,
        images=job.inline_images,
        cover=job.cover_image,
        previous_chapter_index=job.prev_wp_chapter_index,
    )


def persist_publish_result(
    db, doc_id: int, result: dict, *, scheduled_date, chapter_index
) -> bool:
    """Write wp_status back after a publish. Returns True if a write happened."""
    if not (result.get("created") or result.get("updated")):
        return False
    status = "future" if scheduled_date else "publish"
    date = scheduled_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.set_document_wp_status(
        doc_id, status, result.get("post_url") or None, date, chapter_index
    )
    return True
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `pytest tests/test_wp_publish_flow.py -q`
Expected: PASS (all of Task 1's tests).

- [ ] **Step 5: Swap `main_widget.py` to re-import the moved workers**

In `translation_assistant/ui/main_widget.py`, delete the class bodies of `_PublishWorker` (lines ~28-45) and `_StatusCheckWorker` (lines ~74-102). Leave `_IllustrationsPublishWorker` in place. Add, next to the existing `from translation_assistant.ui import remember_dialog_geometry` (line ~17):

```python
from translation_assistant.ui.wp_publish_flow import (
    PublishWorker as _PublishWorker,
    StatusCheckWorker as _StatusCheckWorker,
)
```

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS — all pre-existing tests still green (the `main_widget._PublishWorker` / `_StatusCheckWorker` monkeypatch targets in `test_main_window.py` still resolve, now to the re-imported names).

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/wp_publish_flow.py translation_assistant/ui/main_widget.py tests/test_wp_publish_flow.py
git commit -m "refactor(wp): extract publish workers + build_job into wp_publish_flow"
```

---

## Task 2: Gating helpers — `ensure_wp_config` + `ensure_series_wp_meta`

**Files:**
- Modify: `translation_assistant/ui/wp_publish_flow.py`
- Test: `tests/test_wp_publish_flow.py`

**Interfaces:**
- Consumes: `PublishJob` module (Task 1); `translation_assistant.ui.dlg_wp_settings.WPSettingsDialog`; `translation_assistant.ui.dlg_series.SeriesManagerDialog`; `translation_assistant.ui.remember_dialog_geometry`.
- Produces:
  - `ensure_wp_config(settings, parent) -> tuple[str, str] | None` — `(endpoint_url, api_key)` or `None` if the user cancels the settings dialog / leaves fields blank.
  - `ensure_series_wp_meta(db, settings, series_title: str, parent) -> dict | None` — the `series_wp_meta` dict once `series_slug` and `series_title_short` are set, else `None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wp_publish_flow.py`:

```python
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
```

Add `wp_endpoint_url` / `wp_api_key` / `wp_default_schedule_time` / `wp_chapters_per_day` / `wp_schedule_scope_global` defaults to `_Settings.__init__` so later tasks can reuse it:

```python
        self.wp_endpoint_url = over.get("wp_endpoint_url", "")
        self.wp_api_key = over.get("wp_api_key", "")
        self.wp_default_schedule_time = over.get("wp_default_schedule_time", "")
        self.wp_chapters_per_day = over.get("wp_chapters_per_day", 1)
        self.wp_schedule_scope_global = over.get("wp_schedule_scope_global", True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wp_publish_flow.py -q -k "EnsureWpConfig or EnsureSeriesWpMeta"`
Expected: FAIL — `AttributeError: module ... has no attribute 'ensure_wp_config'`.

- [ ] **Step 3: Add the helpers to `wp_publish_flow.py`**

Add imports at top:

```python
from translation_assistant.ui import remember_dialog_geometry
from translation_assistant.ui.dlg_series import SeriesManagerDialog
from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
```

(If an import cycle appears — `dlg_series` importing back into `ui` — move these two `dlg_*` imports to lazy `import` statements inside the functions, matching the lazy-import style already used in `main_widget._on_publish_wp`.)

Add the functions:

```python
def ensure_wp_config(settings, parent):
    endpoint_url = settings.wp_endpoint_url
    api_key = settings.wp_api_key
    if endpoint_url and api_key:
        return endpoint_url, api_key
    dlg = WPSettingsDialog(settings, parent=parent)
    if not dlg.exec():
        return None
    endpoint_url = settings.wp_endpoint_url
    api_key = settings.wp_api_key
    if not endpoint_url or not api_key:
        return None
    return endpoint_url, api_key


def ensure_series_wp_meta(db, settings, series_title: str, parent):
    meta = db.get_series_wp_meta(series_title)
    if meta["series_slug"] and meta["series_title_short"]:
        return meta
    dlg = SeriesManagerDialog(db, settings=settings, parent=parent)
    remember_dialog_geometry(dlg, settings, "dlg_series")
    dlg.exec()
    meta = db.get_series_wp_meta(series_title)
    if not meta["series_slug"] or not meta["series_title_short"]:
        return None
    return meta
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wp_publish_flow.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/wp_publish_flow.py tests/test_wp_publish_flow.py
git commit -m "refactor(wp): extract ensure_wp_config / ensure_series_wp_meta gating"
```

---

## Task 3: `PublishConfirmDialog`

**Files:**
- Modify: `translation_assistant/ui/wp_publish_flow.py`
- Test: `tests/test_wp_publish_flow.py`

**Interfaces:**
- Consumes: `PublishJob`, `StatusCheckWorker` (Task 1); `wp_publisher.compute_auto_schedule`.
- Produces:
  - `class PublishConfirmDialog(QDialog)` — `__init__(job: PublishJob, db, settings, endpoint_url: str, api_key: str, parent=None)`. Public method `scheduled_date_utc() -> str | None` (the `"%Y-%m-%dT%H:%M:%SZ"` string when "Schedule for later" is checked, else `None`). Overrides `done(r)` to stop its `StatusCheckWorker`.

This is a straight move of the confirm-dialog block from `main_widget._on_publish_wp` (`main_widget.py:1629-1743`) into a class. Behaviour is unchanged: cached-status line, async status refresh (writing back through `db.set_document_wp_status`), previous-chapter-scheduled warning + "Publish Anyway" button, "Schedule for later" checkbox with default-time and auto-schedule pre-fill.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wp_publish_flow.py`:

```python
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
```

Add `from PySide6.QtWidgets import ...` for `qapp` — it is the session `QApplication` fixture from `conftest.py`; add `qapp` to every `PublishConfirmDialog` test's signature.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wp_publish_flow.py -q -k PublishConfirmDialog`
Expected: FAIL — `AttributeError: ... 'PublishConfirmDialog'`.

- [ ] **Step 3: Add `PublishConfirmDialog` to `wp_publish_flow.py`**

Add imports:

```python
from PySide6.QtCore import QDateTime, Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)

from translation_assistant.wp_publisher import compute_auto_schedule
```

Add the class — port `main_widget.py:1629-1749`, replacing `self._settings`→`settings`, `self._db`→`db`, `self._doc_id`→`job.doc_id`, `doc_meta`→`job.doc_meta`, `series_meta`→`job.series_meta`, `self` (parent)→`self` (the dialog):

```python
class PublishConfirmDialog(QDialog):
    def __init__(self, job, db, settings, endpoint_url, api_key, parent=None):
        super().__init__(parent)
        self._job = job
        self._db = db
        self._settings = settings
        self._dte = None
        self._schedule_cb = None
        self._status_worker = None
        self.setWindowTitle("Publish to WordPress")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        doc_meta, series_meta = job.doc_meta, job.series_meta
        layout = QVBoxLayout(self)

        prev_status = None
        prev_scheduled = False
        if job.series_order > 0:
            prev_status = db.get_wp_status_by_series_position(
                doc_meta["series_title"], job.series_order - 1
            )
            prev_scheduled = prev_status is not None and prev_status.get("wp_status") == "future"

        cached = db.get_document_wp_status(job.doc_id)
        status_text_map = {"publish": "Published", "future": "Scheduled", "draft": "Draft"}
        cached_text = status_text_map.get(cached["wp_status"] or "", "Not published")
        self._status_lbl = QLabel(f"WP status: {cached_text}")
        layout.addWidget(self._status_lbl)

        chapter_label = "Synopsis" if job.series_order == 0 else f"Chapter {job.series_order}"
        prompt = f'Publish <b>{doc_meta["chapter_title"]}</b> ({chapter_label}) to WordPress?'
        if cached["wp_status"] == "publish":
            prompt += " — republishing will overwrite the live chapter."
        layout.addWidget(QLabel(prompt))

        if prev_scheduled:
            warn = QLabel(
                f"Warning: Chapter {job.series_order - 1} is still scheduled "
                "and hasn't gone live yet."
            )
            warn.setWordWrap(True)
            layout.addWidget(warn)

        self._schedule_cb = QCheckBox("Schedule for later")
        layout.addWidget(self._schedule_cb)

        default_time = settings.wp_default_schedule_time
        h = m = None
        if default_time:
            try:
                h, m = map(int, default_time.split(":"))
            except (ValueError, IndexError):
                default_time = ""
        if default_time:
            candidate = QDateTime.currentDateTime()
            candidate.setTime(QTime(h, m))
            if candidate <= QDateTime.currentDateTime():
                candidate = candidate.addDays(1)
            self._dte = QDateTimeEdit(candidate)
        else:
            self._dte = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self._dte.setCalendarPopup(True)
        self._dte.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._dte.setEnabled(False)
        self._schedule_cb.toggled.connect(self._dte.setEnabled)
        layout.addWidget(self._dte)

        if prev_scheduled:
            self._schedule_cb.setChecked(True)
            prev_date = prev_status.get("wp_date") if prev_status else None
            if prev_date:
                scope_series = (
                    None if settings.wp_schedule_scope_global else doc_meta["series_title"]
                )
                try:
                    auto = compute_auto_schedule(
                        prev_date,
                        db.get_wp_dates(scope_series),
                        settings.wp_chapters_per_day,
                        settings.wp_default_schedule_time,
                    )
                    self._dte.setDateTime(QDateTime(auto))
                except ValueError:
                    pass

        if prev_scheduled:
            btns = QDialogButtonBox()
            btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
            btns.addButton("Publish Anyway", QDialogButtonBox.ButtonRole.AcceptRole)
        else:
            btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._status_worker = StatusCheckWorker(
            endpoint_url, api_key, series_meta["series_slug"], job.series_order, parent=self
        )
        self._cached = cached
        self._cached_text = cached_text
        self._status_worker.succeeded.connect(self._on_status_ok)
        self._status_worker.error.connect(self._on_status_err)
        self._status_worker.start()

    def _on_status_ok(self, result: dict) -> None:
        m = {"publish": "Published", "future": "Scheduled", "draft": "Draft",
             "not_found": "Not published"}
        self._status_lbl.setText(f"WP status: {m.get(result.get('status', ''), 'Unknown')}")
        self._db.set_document_wp_status(
            self._job.doc_id, result.get("status") or None, result.get("post_url"),
            result.get("date"), self._cached.get("wp_chapter_index"),
        )

    def _on_status_err(self, msg: str) -> None:
        self._status_lbl.setText(f"WP status: {self._cached_text} (cached — {msg})")

    def scheduled_date_utc(self):
        if not self._schedule_cb.isChecked():
            return None
        from datetime import timezone
        local = self._dte.dateTime().toPython()
        return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def done(self, r: int) -> None:
        if self._status_worker is not None:
            self._status_worker.quit()
            self._status_worker.wait(500)
        super().done(r)
```

> Note vs. the old code: `_on_status_ok` no longer calls `self._update_wp_status_label()` — that was a `main_widget`-only side effect. The DB write-back is preserved; callers refresh their own UI.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wp_publish_flow.py -q -k PublishConfirmDialog`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS (the `_on_publish_wp` path in `main_widget` still has its own inline dialog for now — untouched this task).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/wp_publish_flow.py tests/test_wp_publish_flow.py
git commit -m "refactor(wp): extract PublishConfirmDialog into wp_publish_flow"
```

---

## Task 4: `show_publish_result` + `run_single_publish`; migrate `main_widget`

**Files:**
- Modify: `translation_assistant/ui/wp_publish_flow.py`
- Modify: `translation_assistant/ui/main_widget.py` — `_on_publish_wp` (lines ~1550-1771) → delegator; delete `_on_publish_done` (~1773-1835) and `_on_publish_error` (~1837-1839); delete now-unused `self._last_pw` / `self._last_unlock_idx` / `self._last_scheduled_date` / `self._last_wp_chapter_index` init lines (~183-186) and the `_PublishWorker` start block
- Modify: `tests/test_main_window.py` — `TestPublishWpConfirmCopy` (3 tests, ~1323-1471), `TestOnPublishDone` (3 tests, ~1474-1515)
- Test: `tests/test_wp_publish_flow.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces:
  - `show_publish_result(result: dict, job: PublishJob, scheduled_date: str | None, parent) -> None` — the post-publish result dialog (page/post links, generated password field, unlock notice).
  - `run_single_publish(db, settings, doc_id: int, parent, *, on_status_changed=None) -> None` — full end-to-end flow for one doc: gating → `build_job` → `PublishConfirmDialog` → `job_to_payload` → `PublishWorker` → `persist_publish_result` + `show_publish_result` + `on_status_changed()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wp_publish_flow.py`:

```python
class TestRunSinglePublish:
    def test_end_to_end_persists_and_calls_callback(self, qapp, db, monkeypatch):
        doc_id = _doc_with_lines(db)
        s = _Settings(); s.wp_endpoint_url = "https://ex.com"; s.wp_api_key = "key"

        monkeypatch.setattr(wpf, "PublishConfirmDialog", _AcceptConfirm)
        monkeypatch.setattr(wpf, "PublishWorker", _ImmediateWorker(
            {"created": True, "page_url": "https://ex.com/c/", "post_url": "https://ex.com/p/"}
        ))
        monkeypatch.setattr(wpf, "show_publish_result", lambda *a, **k: None)

        called = []
        wpf.run_single_publish(db, s, doc_id, None, on_status_changed=lambda: called.append(1))

        assert called == [1]
        info = db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "publish"
        assert info["wp_post_url"] == "https://ex.com/p/"

    def test_aborts_when_config_cancelled(self, qapp, db, monkeypatch):
        doc_id = _doc_with_lines(db)
        monkeypatch.setattr(wpf, "ensure_wp_config", lambda *a, **k: None)
        # must not raise, must not write
        wpf.run_single_publish(db, _Settings(), doc_id, None)
        assert db.get_document_wp_status(doc_id)["wp_status"] is None

    def test_warns_and_returns_on_empty_translation(self, qapp, db, monkeypatch):
        doc_id = _doc_with_lines(db, translated=("",))
        s = _Settings(); s.wp_endpoint_url = "https://ex.com"; s.wp_api_key = "key"
        monkeypatch.setattr(wpf, "ensure_series_wp_meta", lambda *a, **k: {"series_slug": "n", "series_title_short": "N"})
        warned = []
        monkeypatch.setattr(
            "translation_assistant.ui.wp_publish_flow.QMessageBox.warning",
            lambda *a, **k: warned.append(a),
        )
        wpf.run_single_publish(db, s, doc_id, None)
        assert warned


class _AcceptConfirm:
    def __init__(self, *a, **k):
        pass
    def exec(self):
        return 1
    def scheduled_date_utc(self):
        return None


def _ImmediateWorker(result):
    class _W:
        def __init__(self, *a, **k):
            self._subs = {"succeeded": [], "error": []}
        class _Sig:
            def __init__(self, name, outer):
                self.name, self.outer = name, outer
            def connect(self, fn):
                self.outer._subs[self.name].append(fn)
        @property
        def succeeded(self):
            return _W._Sig("succeeded", self)
        @property
        def error(self):
            return _W._Sig("error", self)
        def start(self):
            for fn in self._subs["succeeded"]:
                fn(result)
    return _W
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wp_publish_flow.py -q -k RunSinglePublish`
Expected: FAIL — `AttributeError: ... 'run_single_publish'`.

- [ ] **Step 3: Add `show_publish_result` + `run_single_publish` to `wp_publish_flow.py`**

Add imports:

```python
from PySide6.QtWidgets import (
    QFormLayout, QLineEdit, QMessageBox,
)
```

```python
def show_publish_result(result, job, scheduled_date, parent):
    created = result.get("created", False)
    updated = result.get("updated", False)
    page_url = result.get("page_url", "")
    post_url = result.get("post_url", "")

    dlg = QDialog(parent)
    dlg.setWindowTitle("WordPress Publish")
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
    dlg.setMinimumWidth(420)
    layout = QVBoxLayout(dlg)

    if created:
        status_text = "Scheduled!" if scheduled_date else "Published!"
    elif updated:
        status_text = "Scheduled!" if scheduled_date else "Updated!"
    else:
        status_text = "Already published."
    layout.addWidget(QLabel(status_text))

    form = QFormLayout()
    if page_url:
        lbl = QLabel(f'<a href="{page_url}">{page_url}</a>')
        lbl.setOpenExternalLinks(True)
        form.addRow("Page:", lbl)
    if post_url and (created or updated):
        lbl = QLabel(f'<a href="{post_url}">{post_url}</a>')
        lbl.setOpenExternalLinks(True)
        form.addRow("Post:", lbl)
    layout.addLayout(form)

    if (created or updated) and job.password:
        pw_edit = QLineEdit(job.password)
        pw_edit.setReadOnly(True)
        pw_edit.selectAll()
        layout.addWidget(QLabel("Password (copy this):"))
        layout.addWidget(pw_edit)

    if (created or updated) and job.unlock_chapter_index is not None:
        layout.addWidget(QLabel(f"Chapter {job.unlock_chapter_index} is now unlocked."))

    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    btns.accepted.connect(dlg.accept)
    layout.addWidget(btns)
    dlg.exec()


def run_single_publish(db, settings, doc_id, parent, *, on_status_changed=None):
    cfg = ensure_wp_config(settings, parent)
    if cfg is None:
        return
    endpoint_url, api_key = cfg

    series_title = db.get_document(doc_id)["series_title"]
    if ensure_series_wp_meta(db, settings, series_title, parent) is None:
        return

    try:
        job = build_job(db, settings, doc_id)
    except PublishJobError as exc:
        QMessageBox.warning(parent, "Nothing to Publish", str(exc))
        return

    dlg = PublishConfirmDialog(job, db, settings, endpoint_url, api_key, parent=parent)
    if not dlg.exec():
        return
    scheduled_date = dlg.scheduled_date_utc()

    try:
        payload = job_to_payload(
            job, api_key, scheduled_date=scheduled_date,
            attribution=settings.wp_attribution_enabled,
        )
    except ValueError as exc:
        QMessageBox.warning(parent, "Payload Error", str(exc))
        return

    worker = PublishWorker(endpoint_url, payload, parent=parent)
    keep = getattr(parent, "_wp_flow_keepalive", None)
    if keep is None and parent is not None:
        keep = []
        parent._wp_flow_keepalive = keep

    def _done(result):
        if persist_publish_result(
            db, doc_id, result, scheduled_date=scheduled_date,
            chapter_index=job.series_order,
        ) and on_status_changed:
            on_status_changed()
        show_publish_result(result, job, scheduled_date, parent)
        if keep is not None and worker in keep:
            keep.remove(worker)

    def _err(msg):
        QMessageBox.warning(parent, "Publish Failed", msg)
        if keep is not None and worker in keep:
            keep.remove(worker)

    worker.succeeded.connect(_done)
    worker.error.connect(_err)
    if keep is not None:
        keep.append(worker)
    worker.start()
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `pytest tests/test_wp_publish_flow.py -q`
Expected: PASS.

- [ ] **Step 5: Replace `main_widget._on_publish_wp` with a delegator**

In `translation_assistant/ui/main_widget.py`, replace the whole body of `_on_publish_wp` (through the `self._publish_worker.start()` line) with:

```python
    def _on_publish_wp(self) -> None:
        from translation_assistant.ui.wp_publish_flow import run_single_publish
        run_single_publish(
            self._db, self._settings, self._doc_id, self,
            on_status_changed=self._update_wp_status_label,
        )
```

Delete `_on_publish_done` and `_on_publish_error` entirely. Remove the now-dead instance attrs and their comment at `main_widget.py:183-186` (`_last_pw`, `_last_unlock_idx`, `_last_scheduled_date`, `_last_wp_chapter_index`) — grep the file for each name first and confirm no remaining reference.

- [ ] **Step 6: Migrate the `test_main_window.py` publish tests**

Replace `TestPublishWpConfirmCopy` with tests that drive the new path:

```python
class TestPublishWpConfirmCopy:
    def test_confirm_dialog_warns_when_already_published(self, win, qapp):
        import sqlite3
        from translation_assistant.db import Database
        from translation_assistant.ui import wp_publish_flow as wpf
        db = Database(":memory:", _conn=sqlite3.connect(":memory:"))
        doc_id = db.create_document("Ch", series_title="Nov", series_order=2, chapter_title="Chapter 2")
        db.save_lines(doc_id, [{"line_number": 0, "prefix": "%", "raw_text": "a", "translated_text": "b"}])
        db.set_series_wp_meta("Nov", series_slug="nov", series_title_short="N")
        db.set_document_wp_status(doc_id, "publish", "https://ex.com/c/", None, 2)

        class _NoRun(wpf.StatusCheckWorker):
            def start(self): pass

        import unittest.mock as m
        with m.patch.object(wpf, "StatusCheckWorker", _NoRun):
            job = wpf.build_job(db, win._settings, doc_id)
            dlg = wpf.PublishConfirmDialog(job, db, win._settings, "https://ex.com", "key")
        from PySide6.QtWidgets import QLabel
        assert any("overwrite" in w.text().lower() for w in dlg.findChildren(QLabel))

    def test_accept_path_forwards_cached_chapter_index(self, qapp):
        """previous_chapter_index flows from the cached wp_chapter_index into build_payload."""
        import sqlite3
        from translation_assistant.db import Database
        from translation_assistant.ui import wp_publish_flow as wpf
        db = Database(":memory:", _conn=sqlite3.connect(":memory:"))
        doc_id = db.create_document("Ch", series_title="Nov", series_order=3, chapter_title="Chapter 3")
        db.save_lines(doc_id, [{"line_number": 0, "prefix": "%", "raw_text": "a", "translated_text": "b"}])
        db.set_series_wp_meta("Nov", series_slug="nov", series_title_short="N")
        db.set_document_wp_status(doc_id, "publish", "https://ex.com/c/", None, 1)

        job = wpf.build_job(db, _MWSettings(), doc_id)
        assert job.prev_wp_chapter_index == 1
        captured = {}
        import translation_assistant.wp_publisher as wp
        real = wp.build_payload
        import unittest.mock as m
        with m.patch.object(wp, "build_payload", lambda *a, **k: captured.update(k) or real(*a, **k)):
            wpf.job_to_payload(job, "key", scheduled_date=None, attribution=True)
        assert captured["previous_chapter_index"] == 1


class _MWSettings:
    wp_password_enabled = False
    wp_unlock_after = 0
    wp_attribution_enabled = True
```

Drop `test_status_ok_preserves_cached_chapter_index` here and re-add it as a `wp_publish_flow` test that instantiates `PublishConfirmDialog` with a `_NoRunWorker`, calls `dlg._on_status_ok({"status": "future", "post_url": "...", "date": "..."})`, and asserts `db.get_document_wp_status(doc_id)["wp_chapter_index"]` is still `1`. Put it in `tests/test_wp_publish_flow.py::TestPublishConfirmDialog`.

Replace `TestOnPublishDone` — its three cases are now `persist_publish_result` behaviour, already covered by `TestPersistPublishResult` in `tests/test_wp_publish_flow.py` (Task 1). Delete `TestOnPublishDone` from `test_main_window.py`. If `_load` / `_sep_file` become unused after this deletion, leave them — other tests in the file use them.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: PASS. If `test_combined_window.py::TestPublishWPAction` fails, it means the File-menu action wiring was disturbed — it must not be; `action_publish_wp` and its `_setup_menubar` reference stay exactly as they were.

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/ui/wp_publish_flow.py translation_assistant/ui/main_widget.py tests/test_wp_publish_flow.py tests/test_main_window.py
git commit -m "refactor(wp): route _on_publish_wp through run_single_publish"
```

---

## Task 5: Single-chapter publish from `OpenDocumentDialog` context menu

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` — `_on_chapter_context_menu` (lines ~315-353)
- Test: `tests/test_dlg_open.py`

**Interfaces:**
- Consumes: `wp_publish_flow.run_single_publish` (Task 4); existing `OpenDocumentDialog._selected_doc_ids()`, `._current_series_raw()`, `._load_chapters()`, `._settings`.
- Produces: no new public symbol — a new context-menu action `"Publish to WordPress…"`, enabled only when exactly one row is selected and `self._settings is not None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dlg_open.py`:

```python
class TestPublishFromContextMenu:
    def _dlg(self, qapp, mem_db, tmp_settings, n=1):
        for i in range(1, n + 1):
            doc_id = mem_db.create_document(
                f"C{i}", series_title="Nov", series_order=i, chapter_title=f"Ch {i}"
            )
            mem_db.save_lines(doc_id, [
                {"line_number": 0, "prefix": "%", "raw_text": "a", "translated_text": "b"},
            ])
        dlg = OpenDocumentDialog(mem_db, settings=tmp_settings)
        _select_series(dlg, "Nov")
        return dlg

    def test_menu_item_enabled_for_single_selection(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(qapp, mem_db, tmp_settings, n=2)
        dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
        seen = {}
        import translation_assistant.ui.dlg_open as mod
        monkeypatch.setattr(mod, "QMenu", _capture_menu(seen))
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(dlg._tree.topLevelItem(0)).center())
        assert seen["Publish to WordPress…"] is True

    def test_menu_item_disabled_for_multi_selection(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(qapp, mem_db, tmp_settings, n=2)
        dlg._tree.selectAll()
        seen = {}
        import translation_assistant.ui.dlg_open as mod
        monkeypatch.setattr(mod, "QMenu", _capture_menu(seen))
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(dlg._tree.topLevelItem(0)).center())
        assert seen["Publish to WordPress…"] is False

    def test_dispatch_calls_run_single_publish_with_selected_doc(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(qapp, mem_db, tmp_settings, n=1)
        item = dlg._tree.topLevelItem(0)
        dlg._tree.setCurrentItem(item)
        target_doc_id = dlg._doc_ids[id(item)]

        captured = {}
        import translation_assistant.ui.wp_publish_flow as wpf
        monkeypatch.setattr(
            wpf, "run_single_publish",
            lambda db, settings, doc_id, parent, **kw: captured.update(
                doc_id=doc_id, has_cb="on_status_changed" in kw
            ),
        )

        class _PickPublishMenu(QMenu):
            def exec(self, *a, **k):
                for act in self.actions():
                    if act.text() == "Publish to WordPress…":
                        return act
                return None

        monkeypatch.setattr("translation_assistant.ui.dlg_open.QMenu", _PickPublishMenu)
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(item).center())
        assert captured["doc_id"] == target_doc_id
        assert captured["has_cb"] is True


def _capture_menu(seen):
    class _M(QMenu):
        def addAction(self, text, *a, **k):
            act = super().addAction(text, *a, **k)
            seen[text] = act.isEnabled()
            _orig = act.setEnabled
            def _rec(v, _o=_orig, _t=text):
                seen[_t] = v
                _o(v)
            act.setEnabled = _rec
            return act
        def exec(self, *a, **k):
            return None
    return _M
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dlg_open.py -q -k PublishFromContextMenu`
Expected: FAIL — `KeyError: 'Publish to WordPress…'` (action not added yet).

- [ ] **Step 3: Add the menu item + dispatch**

In `translation_assistant/ui/dlg_open.py`, in `_on_chapter_context_menu`, after `act_delete = menu.addAction("Delete")`:

```python
        menu.addSeparator()
        act_publish = menu.addAction("Publish to WordPress…")
        act_publish.setEnabled(len(merge_ids) == 1 and self._settings is not None)
```

Add to the `if/elif` dispatch chain (before the final `act_delete` branch is fine; order irrelevant):

```python
        elif chosen == act_publish:
            from translation_assistant.ui.wp_publish_flow import run_single_publish
            series_raw = self._current_series_raw()
            run_single_publish(
                self._db, self._settings, merge_ids[0], self,
                on_status_changed=lambda: self._load_chapters(series_raw),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dlg_open.py -q -k PublishFromContextMenu`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg-open): publish a chapter to WordPress from the context menu"
```

---

## Task 6: Batch publish / schedule from `OpenDocumentDialog`

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py` — `_on_chapter_context_menu` (add batch item), new `_on_publish_batch`, new `_BatchPublishDialog`, new `_BatchPublishWorker`
- Test: `tests/test_dlg_open.py`

**Interfaces:**
- Consumes: `wp_publish_flow` (`ensure_wp_config`, `ensure_series_wp_meta`, `build_job`, `job_to_payload`, `persist_publish_result`, `PublishJobError`); `wp_publisher` (`publish`, `compute_auto_schedule`, `WPPublishError`).
- Produces (all private to `dlg_open.py`):
  - `class _BatchPublishDialog(QDialog)` — `__init__(chapters: list[tuple[int, str, str]], settings, parent=None)` where each tuple is `(series_order, title, wp_cell)`. Reads: `schedule_enabled() -> bool`, `start_qdatetime() -> QDateTime`, `chapters_per_day() -> int`.
  - `class _BatchPublishWorker(QThread)` — `__init__(db, settings, endpoint_url, api_key, jobs: list[tuple[int, str | None]], parent=None)` where each entry is `(doc_id, scheduled_date_or_None)`. Signals: `progress = Signal(int, int, int, dict)` (index, total, doc_id, `{"ok": True, "result": {...}}` or `{"ok": False, "error": "..."}`), `finished_all = Signal(list)` (list of the per-chapter dicts, each with `doc_id` / `series_order` merged in).
  - `OpenDocumentDialog._on_publish_batch(doc_ids: list[int]) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dlg_open.py`:

```python
class TestBatchPublish:
    def _dlg(self, mem_db, tmp_settings, n=3):
        for i in range(1, n + 1):
            doc_id = mem_db.create_document(
                f"C{i}", series_title="Nov", series_order=i, chapter_title=f"Ch {i}"
            )
            mem_db.save_lines(doc_id, [
                {"line_number": 0, "prefix": "%", "raw_text": "a", "translated_text": "b"},
            ])
        mem_db.set_series_wp_meta("Nov", series_slug="nov", series_title_short="N")
        tmp_settings.wp_endpoint_url = "https://ex.com"
        tmp_settings.wp_api_key = "key"
        dlg = OpenDocumentDialog(mem_db, settings=tmp_settings)
        _select_series(dlg, "Nov")
        return dlg

    def test_batch_menu_item_enabled_only_for_multi(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(mem_db, tmp_settings, n=2)
        dlg._tree.selectAll()
        seen = {}
        import translation_assistant.ui.dlg_open as mod
        monkeypatch.setattr(mod, "QMenu", _capture_menu(seen))
        dlg._on_chapter_context_menu(dlg._tree.visualItemRect(dlg._tree.topLevelItem(0)).center())
        assert seen["Publish / Schedule Chapters…"] is True

    def test_batch_publish_now_writes_status_for_all(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(mem_db, tmp_settings, n=3)
        doc_ids = [dlg._doc_ids[id(dlg._tree.topLevelItem(i))] for i in range(3)]

        import translation_assistant.wp_publisher as wp
        monkeypatch.setattr(
            wp, "publish",
            lambda endpoint, payload: {"created": True, "post_url": f"https://ex.com/p{payload['chapter_index']}/"},
        )

        class _NowDialog:
            def __init__(self, *a, **k): pass
            def exec(self): return 1
            def schedule_enabled(self): return False
            def start_qdatetime(self): return None
            def chapters_per_day(self): return 1

        monkeypatch.setattr("translation_assistant.ui.dlg_open._BatchPublishDialog", _NowDialog)
        # run the worker synchronously
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_open._BatchPublishWorker.start",
            lambda self: self.run(),
        )
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_open.QProgressDialog", _DummyProgress
        )
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_open.QDialog.exec", lambda self: 1
        )

        dlg._on_publish_batch(doc_ids)

        for did in doc_ids:
            assert mem_db.get_document_wp_status(did)["wp_status"] == "publish"

    def test_batch_schedule_steps_dates(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(mem_db, tmp_settings, n=3)
        doc_ids = [dlg._doc_ids[id(dlg._tree.topLevelItem(i))] for i in range(3)]
        tmp_settings.wp_default_schedule_time = "09:00"

        seen_dates = []
        import translation_assistant.wp_publisher as wp
        def _fake_publish(endpoint, payload):
            seen_dates.append(payload.get("publish_date"))
            return {"created": True, "post_url": "https://ex.com/p/"}
        monkeypatch.setattr(wp, "publish", _fake_publish)

        from PySide6.QtCore import QDateTime, QDate, QTime
        start = QDateTime(QDate(2026, 9, 3), QTime(9, 0))

        class _SchedDialog:
            def __init__(self, *a, **k): pass
            def exec(self): return 1
            def schedule_enabled(self): return True
            def start_qdatetime(self): return start
            def chapters_per_day(self): return 2

        monkeypatch.setattr("translation_assistant.ui.dlg_open._BatchPublishDialog", _SchedDialog)
        monkeypatch.setattr("translation_assistant.ui.dlg_open._BatchPublishWorker.start", lambda self: self.run())
        monkeypatch.setattr("translation_assistant.ui.dlg_open.QProgressDialog", _DummyProgress)
        monkeypatch.setattr("translation_assistant.ui.dlg_open.QDialog.exec", lambda self: 1)

        dlg._on_publish_batch(doc_ids)

        assert all(d is not None for d in seen_dates)
        assert seen_dates[0].startswith("2026-09-03")
        assert seen_dates[1].startswith("2026-09-03")   # chapters_per_day == 2
        assert seen_dates[2].startswith("2026-09-04")   # rolls to next day

    def test_batch_continues_past_one_failure(self, qapp, mem_db, tmp_settings, monkeypatch):
        dlg = self._dlg(mem_db, tmp_settings, n=3)
        doc_ids = [dlg._doc_ids[id(dlg._tree.topLevelItem(i))] for i in range(3)]

        import translation_assistant.wp_publisher as wp
        from translation_assistant.wp_publisher import WPPublishError
        calls = {"n": 0}
        def _flaky(endpoint, payload):
            calls["n"] += 1
            if calls["n"] == 2:
                raise WPPublishError("boom", status_code=500)
            return {"created": True, "post_url": "https://ex.com/p/"}
        monkeypatch.setattr(wp, "publish", _flaky)

        class _NowDialog:
            def __init__(self, *a, **k): pass
            def exec(self): return 1
            def schedule_enabled(self): return False
            def start_qdatetime(self): return None
            def chapters_per_day(self): return 1

        monkeypatch.setattr("translation_assistant.ui.dlg_open._BatchPublishDialog", _NowDialog)
        monkeypatch.setattr("translation_assistant.ui.dlg_open._BatchPublishWorker.start", lambda self: self.run())
        monkeypatch.setattr("translation_assistant.ui.dlg_open.QProgressDialog", _DummyProgress)
        monkeypatch.setattr("translation_assistant.ui.dlg_open.QDialog.exec", lambda self: 1)

        dlg._on_publish_batch(doc_ids)

        assert calls["n"] == 3  # did not stop at the failure
        statuses = [mem_db.get_document_wp_status(d)["wp_status"] for d in doc_ids]
        assert statuses == ["publish", None, "publish"]


class _DummyProgress:
    def __init__(self, *a, **k): pass
    def setValue(self, *a): pass
    def setLabelText(self, *a): pass
    def wasCanceled(self): return False
    def close(self): pass
    def setWindowModality(self, *a): pass
    def setMinimumDuration(self, *a): pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dlg_open.py -q -k "TestBatchPublish"`
Expected: FAIL — `AttributeError: ... '_BatchPublishDialog'` / `_on_publish_batch`.

- [ ] **Step 3: Add the batch menu item**

In `_on_chapter_context_menu`, right after the `act_publish` line from Task 5:

```python
        act_publish_batch = menu.addAction("Publish / Schedule Chapters…")
        act_publish_batch.setEnabled(len(merge_ids) >= 2 and self._settings is not None)
```

Dispatch branch:

```python
        elif chosen == act_publish_batch:
            self._on_publish_batch(merge_ids)
```

- [ ] **Step 4: Add `_BatchPublishWorker`**

Add near the top of `dlg_open.py` (after imports), alongside `_ChapterTree`:

```python
class _BatchPublishWorker(QThread):
    progress = Signal(int, int, int, dict)      # index, total, doc_id, {"ok": bool, ...}
    finished_all = Signal(list)                 # [{doc_id, series_order, ok, result|error}]

    def __init__(self, db, settings, endpoint_url, api_key, jobs, parent=None):
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._jobs = jobs                       # [(doc_id, scheduled_date | None)]
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from translation_assistant.ui.wp_publish_flow import (
            PublishJobError, build_job, job_to_payload,
        )
        from translation_assistant.wp_publisher import WPPublishError, publish
        summary = []
        total = len(self._jobs)
        for i, (doc_id, sched) in enumerate(self._jobs):
            if self._cancel:
                break
            row = {"doc_id": doc_id, "series_order": None, "scheduled_date": sched}
            try:
                job = build_job(self._db, self._settings, doc_id)
                row["series_order"] = job.series_order
                payload = job_to_payload(
                    job, self._api_key, scheduled_date=sched,
                    attribution=self._settings.wp_attribution_enabled,
                )
                result = publish(self._endpoint_url, payload)
                row.update(ok=True, result=result, password=job.password)
            except (PublishJobError, ValueError, WPPublishError) as exc:
                row.update(ok=False, error=str(exc))
            except Exception as exc:  # noqa: BLE001 — worker boundary
                row.update(ok=False, error=str(exc))
            summary.append(row)
            self.progress.emit(i + 1, total, doc_id, row)
        self.finished_all.emit(summary)
```

Add `QThread`, `Signal` to the `PySide6.QtCore` import line in `dlg_open.py`, and `QProgressDialog` to the `PySide6.QtWidgets` import.

- [ ] **Step 5: Add `_BatchPublishDialog`**

Add near the other private dialogs at the bottom of `dlg_open.py`:

```python
class _BatchPublishDialog(QDialog):
    def __init__(self, chapters, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Publish / Schedule Chapters")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        from PySide6.QtWidgets import (
            QCheckBox, QDateTimeEdit, QDialogButtonBox, QFormLayout, QLabel,
            QSpinBox, QVBoxLayout,
        )
        from PySide6.QtCore import QDateTime, QTime
        layout = QVBoxLayout(self)

        listing = "\n".join(f"  {o}. {t}  {c}".rstrip() for o, t, c in chapters)
        lbl = QLabel(f"{len(chapters)} chapters selected:\n{listing}")
        layout.addWidget(lbl)

        form = QFormLayout()
        self._schedule_cb = QCheckBox("Schedule (unchecked = publish all now)")
        self._schedule_cb.setChecked(True)
        form.addRow(self._schedule_cb)

        default_time = settings.wp_default_schedule_time
        h = m = None
        if default_time:
            try:
                h, m = map(int, default_time.split(":"))
            except (ValueError, IndexError):
                default_time = ""
        candidate = QDateTime.currentDateTime().addSecs(3600)
        if default_time:
            candidate = QDateTime.currentDateTime()
            candidate.setTime(QTime(h, m))
            if candidate <= QDateTime.currentDateTime():
                candidate = candidate.addDays(1)
        self._start = QDateTimeEdit(candidate)
        self._start.setCalendarPopup(True)
        self._start.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("Start:", self._start)

        self._per_day = QSpinBox()
        self._per_day.setMinimum(1)
        self._per_day.setValue(max(1, settings.wp_chapters_per_day))
        form.addRow("Chapters per day:", self._per_day)
        layout.addLayout(form)

        self._schedule_cb.toggled.connect(self._start.setEnabled)
        self._schedule_cb.toggled.connect(self._per_day.setEnabled)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def schedule_enabled(self):
        return self._schedule_cb.isChecked()

    def start_qdatetime(self):
        return self._start.dateTime()

    def chapters_per_day(self):
        return self._per_day.value()
```

- [ ] **Step 6: Add `_on_publish_batch`**

Add as a method on `OpenDocumentDialog`:

```python
    def _on_publish_batch(self, doc_ids: list[int]) -> None:
        from datetime import timezone
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QProgressDialog, QVBoxLayout
        from translation_assistant.ui.wp_publish_flow import ensure_series_wp_meta, ensure_wp_config
        from translation_assistant.wp_publisher import compute_auto_schedule

        cfg = ensure_wp_config(self._settings, self)
        if cfg is None:
            return
        endpoint_url, api_key = cfg

        docs = {d["id"]: d for d in self._db.list_documents()}
        ordered = sorted(
            doc_ids, key=lambda i: (docs[i]["series_title"] or "", docs[i]["series_order"])
        )
        for series_title in {docs[i]["series_title"] for i in ordered}:
            if ensure_series_wp_meta(self._db, self._settings, series_title, self) is None:
                QMessageBox.warning(
                    self, "WP Fields Missing",
                    f'Set slug + short title for "{series_title}" in Series Manager.',
                )
                return

        chapters = [
            (docs[i]["series_order"], docs[i]["chapter_title"] or docs[i]["title"],
             (self._db.get_document_wp_status(i)["wp_status"] or ""))
            for i in ordered
        ]
        dlg = _BatchPublishDialog(chapters, self._settings, parent=self)
        if not dlg.exec():
            return

        schedule = dlg.schedule_enabled()
        slots: list[str | None] = []
        if schedule:
            assigned: list[str] = []
            start_utc = dlg.start_qdatetime().dateTime().toPython().astimezone(
                timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(dlg.start_qdatetime(), "dateTime") \
                else dlg.start_qdatetime().toPython().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for n in range(len(ordered)):
                if n == 0:
                    slot = start_utc
                else:
                    slot = compute_auto_schedule(
                        assigned[-1], assigned, dlg.chapters_per_day(),
                        self._settings.wp_default_schedule_time,
                    ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                assigned.append(slot)
                slots.append(slot)
        else:
            slots = [None] * len(ordered)

        jobs = list(zip(ordered, slots))
        prog = QProgressDialog("Publishing…", "Cancel", 0, len(jobs), self)
        prog.setWindowModality(_Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)

        worker = _BatchPublishWorker(
            self._db, self._settings, endpoint_url, api_key, jobs, parent=self
        )
        self._batch_worker = worker  # keepalive

        def _on_progress(idx, total, doc_id, row):
            prog.setValue(idx)
            prog.setLabelText(f"Publishing chapter {idx} of {total}…")
            if prog.wasCanceled():
                worker.cancel()

        def _on_done(summary):
            prog.close()
            from translation_assistant.ui.wp_publish_flow import persist_publish_result
            for row in summary:
                if row.get("ok"):
                    persist_publish_result(
                        self._db, row["doc_id"], row["result"],
                        scheduled_date=row["scheduled_date"],
                        chapter_index=row["series_order"],
                    )
            self._load_chapters(self._current_series_raw())
            self._show_batch_summary(summary)

        worker.progress.connect(_on_progress)
        worker.finished_all.connect(_on_done)
        worker.start()

    def _show_batch_summary(self, summary: list[dict]) -> None:
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Batch Publish — Results")
        dlg.setWindowFlags(dlg.windowFlags() & ~_Qt.WindowType.WindowContextHelpButtonHint)
        dlg.setMinimumWidth(460)
        layout = QVBoxLayout(dlg)
        ok = sum(1 for r in summary if r.get("ok"))
        layout.addWidget(QLabel(f"{ok} / {len(summary)} published."))
        lines = []
        for r in summary:
            tag = "✓" if r.get("ok") else "✗"
            detail = (
                (r.get("scheduled_date") or "now") if r.get("ok") else r.get("error", "")
            )
            lines.append(f"{tag} ch {r.get('series_order')}: {detail}")
        pws = [
            f"ch {r['series_order']}: {r['password']}"
            for r in summary if r.get("ok") and r.get("password")
        ]
        if pws:
            lines.append("")
            lines.append("Passwords:")
            lines.extend(pws)
        box = QPlainTextEdit("\n".join(lines))
        box.setReadOnly(True)
        layout.addWidget(box)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()
```

> Simplify the `start_utc` computation if `_BatchPublishDialog.start_qdatetime()` reliably returns a `QDateTime` (it does — the test stubs return either a `QDateTime` or `None` only when `schedule_enabled()` is `False`, in which case this branch is skipped). Reduce to:
> ```python
> start_utc = dlg.start_qdatetime().toPython().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
> ```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_dlg_open.py -q -k "TestBatchPublish or TestPublishFromContextMenu"`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(dlg-open): batch publish / schedule selected chapters to WordPress"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| `wp_publish_flow.py` — workers moved as public names, re-import shim | Task 1 |
| `ensure_wp_config` / `ensure_series_wp_meta` | Task 2 |
| `PublishJob` + `build_job` (steps 1-6, image shrink, `PublishJobError`) | Task 1 |
| `job_to_payload` | Task 1 |
| `PublishConfirmDialog` (status worker, prev-scheduled warning, schedule pre-fill) | Task 3 |
| `show_publish_result` | Task 4 |
| `run_single_publish` | Task 4 |
| `main_widget._on_publish_wp` → delegator; delete `_on_publish_done/_error` | Task 4 |
| `test_main_window.py` retarget (`TestPublishWpConfirmCopy`, `TestOnPublishDone`) | Task 4 |
| dlg_open single-chapter context menu + dispatch + tree refresh | Task 5 |
| dlg_open batch dialog (start / chapters-per-day / publish-now) | Task 6 |
| batch sequential worker, `compute_auto_schedule` slot stepping, continue-past-failure | Task 6 |
| batch summary dialog with per-chapter result + passwords | Task 6 |
| `_settings is not None` guard on menu items | Tasks 5, 6 |
| Cancel finishes in-flight chapter then shows summary | Task 6 (`worker.cancel()` checked between chapters) |
| Out of scope: `wp_publisher.py`, volume illustrations, File-menu removal, batch retry | not touched — confirmed in Task 4 Step 7 note |

**2. Placeholder scan** — no "TBD"/"handle edge cases"/"similar to Task N"; every code step carries full code. The two `>` notes (import-cycle fallback in Task 2, `start_utc` simplification in Task 6) are concrete alternatives, not deferrals.

**3. Type consistency** — `PublishJob` field names (`inline_images`, `cover_image`, `prev_wp_chapter_index`, `series_order`, `unlock_chapter_index`, `password`) are identical in Tasks 1, 3, 4, 6. `job_to_payload(job, api_key, *, scheduled_date, attribution)` signature identical in Tasks 1, 4, 6. `run_single_publish(db, settings, doc_id, parent, *, on_status_changed=None)` identical in Tasks 4, 5. `persist_publish_result(db, doc_id, result, *, scheduled_date, chapter_index)` identical in Tasks 1, 4, 6. `_BatchPublishWorker` signals `progress(int,int,int,dict)` / `finished_all(list)` consistent between Task 6 Step 4 and Step 6. `_BatchPublishDialog` readers `schedule_enabled()` / `start_qdatetime()` / `chapters_per_day()` consistent between Step 5 and Step 6 and the tests.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-02-publish-from-open-dialog.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

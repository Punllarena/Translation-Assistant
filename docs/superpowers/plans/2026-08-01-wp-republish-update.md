# WP Republish Always-Update (Client-Side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make this repo's client side track the WP chapter index it last published at, forward it to the server as `previous_chapter_index` so renumbered chapters can be relocated instead of duplicated, and stop dropping local status updates when the server reports `updated: true` instead of `created: true`.

**Architecture:** Add a `wp_chapter_index` column to `documents` alongside the existing `wp_status`/`wp_post_url`/`wp_date` trio, thread it through the existing `get_document_wp_status`/`set_document_wp_status` seam, read it before building the publish payload, and update `_on_publish_done` to persist status on `updated` as well as `created`.

**Tech Stack:** Python, SQLite (stdlib `sqlite3`), PySide6, pytest.

## Global Constraints

- Server-side plugin (`translation-assistant-publisher`, `includes/class-publisher.php`) is a separate repo, not checked out here — **out of scope for this plan**. The spec (`docs/superpowers/specs/2026-08-01-wp-republish-update-design.md`) describes the server contract this plan's payload/response handling assumes (`previous_chapter_index` request field; `updated` response field); implementing the plugin side is a separate plan in that repo.
- `documents` schema migrations use the existing idempotent `PRAGMA table_info` / `ALTER TABLE` pattern in `Database._apply_schema` (`translation_assistant/db.py`) — never a destructive migration.
- Never import `sqlite3` outside `db.py`.
- `AppSettings`/`QSettings` are untouched by this plan — no new settings needed.

---

## File Structure

- Modify `translation_assistant/db.py` — add `wp_chapter_index` column + thread through `set_document_wp_status`/`get_document_wp_status`.
- Modify `translation_assistant/wp_publisher.py` — `build_payload` gains `previous_chapter_index` param.
- Modify `translation_assistant/ui/main_widget.py` — `_on_publish_wp` reads and forwards the previous index and stashes the current one; `_on_publish_done` persists status on `updated` as well as `created`, and its dialog text distinguishes "Updated!" from "Published!"; confirm dialog gets an overwrite-warning clause.
- Modify `tests/test_db.py`, `tests/test_wp_publisher.py`, `tests/test_main_window.py`.

## Task 1: `db.py` — `wp_chapter_index` column and accessor methods

**Files:**
- Modify: `translation_assistant/db.py:157-166` (migration block), `translation_assistant/db.py:527-542` (`set_document_wp_status`/`get_document_wp_status`)
- Test: `tests/test_db.py:1165-1174`

**Interfaces:**
- Produces: `Database.set_document_wp_status(doc_id: int, status: str, post_url: str | None, date: str | None = None, chapter_index: int | None = None) -> None`
- Produces: `Database.get_document_wp_status(doc_id: int) -> dict` with keys `wp_status`, `wp_post_url`, `wp_date`, `wp_chapter_index`

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_db.py`. Update the existing dict-equality test (line 1171-1174) to include the new key, and add two new tests right after `test_wp_status_columns_exist`:

```python
def test_wp_status_columns_exist(db):
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(documents)").fetchall()}
    assert "wp_status" in cols
    assert "wp_post_url" in cols
    assert "wp_chapter_index" in cols


def test_get_document_wp_status_defaults_none(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    info = db.get_document_wp_status(doc_id)
    assert info == {
        "wp_status": None, "wp_post_url": None, "wp_date": None,
        "wp_chapter_index": None,
    }


def test_set_and_get_document_wp_status_includes_chapter_index(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    db.set_document_wp_status(doc_id, "publish", "https://ex.com/ch1/", None, 1)
    info = db.get_document_wp_status(doc_id)
    assert info["wp_chapter_index"] == 1


def test_set_document_wp_status_chapter_index_defaults_none(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    db.set_document_wp_status(doc_id, "publish", "https://ex.com/ch1/")
    assert db.get_document_wp_status(doc_id)["wp_chapter_index"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k wp_status_columns_exist or wp_chapter_index or defaults_none -v`
Expected: FAIL — `wp_chapter_index` missing from PRAGMA columns / KeyError or AssertionError on dict comparison.

- [ ] **Step 3: Add the migration**

In `translation_assistant/db.py`, extend the existing WP-status migration block (currently lines 157-166):

```python
        # Idempotent column migrations for WP publish status on documents
        wp_doc_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()}
        for col, defn in [
            ("wp_status",       "TEXT DEFAULT NULL"),
            ("wp_post_url",     "TEXT DEFAULT NULL"),
            ("wp_date",         "TEXT DEFAULT NULL"),
            ("wp_chapter_index", "INTEGER DEFAULT NULL"),
        ]:
            if col not in wp_doc_existing:
                self._conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {defn}")
        self._conn.commit()
```

- [ ] **Step 4: Update the accessor methods**

Replace `set_document_wp_status`/`get_document_wp_status` (currently lines 527-542):

```python
    def set_document_wp_status(
        self,
        doc_id: int,
        status: str,
        post_url: str | None,
        date: str | None = None,
        chapter_index: int | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE documents SET wp_status = ?, wp_post_url = ?, wp_date = ?, "
            "wp_chapter_index = ? WHERE id = ?",
            (status, post_url, date, chapter_index, doc_id),
        )
        self._conn.commit()

    def get_document_wp_status(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT wp_status, wp_post_url, wp_date, wp_chapter_index FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            return {
                "wp_status": None, "wp_post_url": None, "wp_date": None,
                "wp_chapter_index": None,
            }
        return dict(row)
```

Note: every other existing call site of `set_document_wp_status` (in `main_widget.py`) passes 3-4 positional args and relies on `chapter_index` defaulting to `None` — that default is intentional for those call sites too (Task 3 explicitly threads the real value through where it matters; Task 1 must not change calling convention for the others, since the new parameter is appended last with a default).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS, full file, 918+ tests still green (no regressions from the signature change since `chapter_index` is a trailing optional param).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add wp_chapter_index column for republish index tracking"
```

## Task 2: `wp_publisher.py` — `previous_chapter_index` in `build_payload`

**Files:**
- Modify: `translation_assistant/wp_publisher.py:181-228` (`build_payload`)
- Test: `tests/test_wp_publisher.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (pure function, no DB access)
- Produces: `build_payload(..., previous_chapter_index: int | None = None) -> dict`, adding `payload["previous_chapter_index"]` only when it's not `None` and differs from `doc_meta["series_order"]`

- [ ] **Step 1: Write the failing tests**

Add after `test_build_payload_omits_password_fields_when_none` (around line 195-200) in `tests/test_wp_publisher.py`:

```python
def test_build_payload_includes_previous_chapter_index_when_differs():
    doc_meta, series_meta, lines = _sample_meta()
    doc_meta["series_order"] = 3
    payload = build_payload(
        doc_meta, series_meta, lines, api_key="key123", previous_chapter_index=2,
    )
    assert payload["previous_chapter_index"] == 2

def test_build_payload_omits_previous_chapter_index_when_same():
    doc_meta, series_meta, lines = _sample_meta()
    doc_meta["series_order"] = 1
    payload = build_payload(
        doc_meta, series_meta, lines, api_key="key123", previous_chapter_index=1,
    )
    assert "previous_chapter_index" not in payload

def test_build_payload_omits_previous_chapter_index_when_none():
    doc_meta, series_meta, lines = _sample_meta()
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert "previous_chapter_index" not in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wp_publisher.py -k previous_chapter_index -v`
Expected: FAIL — `build_payload() got an unexpected keyword argument 'previous_chapter_index'`.

- [ ] **Step 3: Implement**

In `translation_assistant/wp_publisher.py`, add the parameter to `build_payload`'s signature and set it near the other optional fields (after the `scheduled_date` block, currently the last lines before `return payload`):

```python
def build_payload(
    doc_meta: dict,
    series_meta: dict,
    lines: list[dict],
    api_key: str,
    password: str | None = None,
    unlock_chapter_index: int | None = None,
    scheduled_date: str | None = None,
    attribution: bool = True,
    images: list[dict] | None = None,
    cover: dict | None = None,
    previous_chapter_index: int | None = None,
) -> dict:
```

```python
    if scheduled_date is not None:
        payload["publish_date"] = scheduled_date
    if previous_chapter_index is not None and previous_chapter_index != doc_meta["series_order"]:
        payload["previous_chapter_index"] = previous_chapter_index
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wp_publisher.py -v`
Expected: PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): build_payload forwards previous_chapter_index for renumber detection"
```

## Task 3: `main_widget.py` — `_on_publish_wp` forwards previous index, warns on overwrite

**Files:**
- Modify: `translation_assistant/ui/main_widget.py:1389-1596` (`_on_publish_wp`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `Database.get_document_wp_status(doc_id) -> dict` (Task 1, key `wp_chapter_index`); `build_payload(..., previous_chapter_index=...)` (Task 2)
- Produces: `self._last_wp_chapter_index: int` set before the publish worker starts, consumed by Task 4's `_on_publish_done`

- [ ] **Step 1: Write the failing test**

`_on_publish_wp` is a large interactive method (opens a modal confirm dialog) that's not currently unit-tested directly — existing coverage only checks the action exists (`tests/test_combined_window.py:131-138`). Rather than drive the modal dialog in a test, verify the two testable seams: the confirm-dialog label text includes the overwrite warning when cached status is "Published", and that `self._last_wp_chapter_index` is set correctly. Add to `tests/test_main_window.py` (near other `win` fixture tests, e.g. after the publish-related section — search `action_publish_wp` for placement, or append a new `class TestPublishWp` section):

```python
class TestPublishWpConfirmCopy:
    def test_confirm_dialog_warns_when_already_published(self, win, monkeypatch):
        _load(win, "Hello\n")
        win._db.set_document_wp_status(win._doc_id, "publish", "https://ex.com/c1/", None, 1)
        win._settings.wp_endpoint_url = "https://example.com"
        win._settings.wp_api_key = "key123"
        doc = win._db.get_document(win._doc_id)
        win._db.set_series_wp_meta(
            doc["series_title"], series_slug="s", series_title_short="S", syosetu_url="",
        )

        captured = {}

        class _FakeDialog:
            def __init__(self, *a, **k): pass
            def exec(self): return 0  # Cancel — stop before any network/worker activity

        def _fake_label_capture(text, *a, **k):
            captured.setdefault("labels", []).append(text)
            from PySide6.QtWidgets import QLabel
            return QLabel(text)

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog", _FakeDialog,
        )
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QLabel", _fake_label_capture,
        )
        win._on_publish_wp()

        assert any("overwrite" in t.lower() for t in captured["labels"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_window.py -k warns_when_already_published -v`
Expected: FAIL — no label contains "overwrite" yet.

- [ ] **Step 3: Implement**

In `translation_assistant/ui/main_widget.py`, inside `_on_publish_wp`, locate the cached-status block (currently around line 1467-1471):

```python
        # Cached WP status line
        _cached = self._db.get_document_wp_status(self._doc_id)
        _status_text_map = {"publish": "Published", "future": "Scheduled", "draft": "Draft"}
        _cached_text = _status_text_map.get(_cached["wp_status"] or "", "Not published")
        _status_lbl = QLabel(f"WP status: {_cached_text}")
        _cl.addWidget(_status_lbl)

        _publish_prompt = f'Publish <b>{doc_meta["chapter_title"]}</b> ({chapter_label}) to WordPress?'
        if _cached["wp_status"] == "publish":
            _publish_prompt += " — republishing will overwrite the live chapter."
        _cl.addWidget(QLabel(_publish_prompt))
```

(replacing the old single-line `_cl.addWidget(QLabel(f'Publish <b>{doc_meta["chapter_title"]}</b> ({chapter_label}) to WordPress?'))`.)

Then, where the payload is built (currently lines ~1550-1559), forward the previous index and stash the current one:

```python
        try:
            payload = build_payload(
                doc_meta, series_meta, lines, api_key=api_key,
                password=self._last_pw,
                unlock_chapter_index=self._last_unlock_idx,
                scheduled_date=self._last_scheduled_date,
                attribution=self._settings.wp_attribution_enabled,
                images=inline_images,
                cover=cover_image,
                previous_chapter_index=_cached.get("wp_chapter_index"),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Payload Error", str(exc))
            return

        self._last_wp_chapter_index = doc_meta["series_order"]
        self.action_publish_wp.setEnabled(False)
```

Also update the `_on_status_ok` callback (currently lines ~1550-1559 region, the async status-refresh handler) so its `set_document_wp_status` call doesn't clobber the stored `wp_chapter_index` with `None` on every background refresh — pass through the value already read into `_cached`:

```python
        def _on_status_ok(result: dict) -> None:
            _map = {
                "publish":   "Published",
                "future":    "Scheduled",
                "draft":     "Draft",
                "not_found": "Not published",
            }
            _status_lbl.setText(f"WP status: {_map.get(result.get('status', ''), 'Unknown')}")
            self._db.set_document_wp_status(
                self._doc_id, result.get("status") or None, result.get("post_url"),
                result.get("date"), _cached.get("wp_chapter_index"),
            )
            self._update_wp_status_label()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_window.py -k warns_when_already_published -v`
Expected: PASS.

- [ ] **Step 5: Run the full test file to check for regressions**

Run: `pytest tests/test_main_window.py tests/test_combined_window.py -v`
Expected: PASS, no regressions (the `_on_status_ok` and payload-building changes are additive/pass-through only).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(wp): forward previous_chapter_index and warn before overwrite republish"
```

## Task 4: `main_widget.py` — `_on_publish_done` persists status on `updated` too

**Files:**
- Modify: `translation_assistant/ui/main_widget.py:1598-1650` (`_on_publish_done`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `self._last_wp_chapter_index` (Task 3); `Database.set_document_wp_status(doc_id, status, post_url, date, chapter_index)` (Task 1)
- Produces: local `wp_status`/`wp_post_url`/`wp_date`/`wp_chapter_index` are refreshed whenever the server reports `created: true` **or** `updated: true`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_window.py`:

```python
class TestOnPublishDone:
    def _prep(self, win):
        _load(win, "Hello\n")
        win._last_scheduled_date = None
        win._last_pw = None
        win._last_unlock_idx = None
        win._last_wp_chapter_index = 1
        return win._doc_id

    def test_persists_status_on_created(self, win, monkeypatch):
        doc_id = self._prep(win)
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )
        win._on_publish_done({"created": True, "page_url": "https://ex.com/c1/", "post_url": "https://ex.com/p1/"})
        info = win._db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "publish"
        assert info["wp_chapter_index"] == 1

    def test_persists_status_on_updated_without_created(self, win, monkeypatch):
        doc_id = self._prep(win)
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )
        win._on_publish_done({
            "created": False, "updated": True,
            "page_url": "https://ex.com/c1/", "post_url": "https://ex.com/p1/",
        })
        info = win._db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "publish"
        assert info["wp_post_url"] == "https://ex.com/p1/"
        assert info["wp_chapter_index"] == 1

    def test_skips_status_write_when_neither_created_nor_updated(self, win, monkeypatch):
        doc_id = self._prep(win)
        win._db.set_document_wp_status(doc_id, "future", "https://old.example/", "2026-01-01T00:00:00Z", 1)
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog.exec", lambda self: 1,
        )
        win._on_publish_done({"created": False, "page_url": "https://ex.com/c1/", "post_url": ""})
        info = win._db.get_document_wp_status(doc_id)
        assert info["wp_status"] == "future"  # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main_window.py -k OnPublishDone -v`
Expected: FAIL on `test_persists_status_on_updated_without_created` (current code only checks `created is False` → skips the write) and `test_persists_status_on_created` fails on the `wp_chapter_index` assertion (column/param don't exist until Task 1, or `self._last_wp_chapter_index` isn't read yet).

- [ ] **Step 3: Implement**

Replace the top of `_on_publish_done` (currently lines 1598-1613):

```python
    def _on_publish_done(self, result: dict) -> None:
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
        )
        from PySide6.QtCore import Qt

        created = result.get("created", False)
        updated = result.get("updated", False)
        page_url = result.get("page_url", "")
        post_url = result.get("post_url", "")

        if created or updated:
            from datetime import datetime as _dt, timezone as _tz
            wp_status_val = "future" if self._last_scheduled_date else "publish"
            wp_date_val = self._last_scheduled_date or _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._db.set_document_wp_status(
                self._doc_id, wp_status_val, post_url or None, wp_date_val,
                self._last_wp_chapter_index,
            )
            self._update_wp_status_label()
```

Then update the dialog body (currently lines 1615-1650) to use `created`/`updated` instead of the old `already` boolean — replace every remaining `already` reference:

```python
        dlg = QDialog(self)
        dlg.setWindowTitle("WordPress Publish")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)

        if created:
            status_text = "Scheduled!" if self._last_scheduled_date else "Published!"
        elif updated:
            status_text = "Scheduled!" if self._last_scheduled_date else "Updated!"
        else:
            status_text = "Already published."
        status_label = QLabel(status_text)
        layout.addWidget(status_label)

        form = QFormLayout()
        if page_url:
            page_label = QLabel(f'<a href="{page_url}">{page_url}</a>')
            page_label.setOpenExternalLinks(True)
            form.addRow("Page:", page_label)
        if post_url and (created or updated):
            post_label = QLabel(f'<a href="{post_url}">{post_url}</a>')
            post_label.setOpenExternalLinks(True)
            form.addRow("Post:", post_label)
        layout.addLayout(form)

        if (created or updated) and self._last_pw:
            pw_edit = QLineEdit(self._last_pw)
            pw_edit.setReadOnly(True)
            pw_edit.selectAll()
            layout.addWidget(QLabel("Password (copy this):"))
            layout.addWidget(pw_edit)

        if (created or updated) and self._last_unlock_idx is not None:
            layout.addWidget(QLabel(f"Chapter {self._last_unlock_idx} is now unlocked."))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)

        dlg.exec()
        self.action_publish_wp.setEnabled(True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main_window.py -k OnPublishDone -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: PASS, all tests (918 baseline + new ones added across Tasks 1-4).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "fix(wp): persist local wp_status on updated republish, not just created"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-08-01-wp-republish-update-design.md`):
- "Data model changes → Client (db.py)" — `wp_chapter_index` column + accessor changes → Task 1. ✅
- "Why the client needs wp_chapter_index" / `previous_chapter_index` sent only when it differs → Task 2. ✅
- "Client-side changes → wp_publisher.py build_payload" → Task 2. ✅
- "Client-side changes → main_widget.py _on_publish_wp reads wp_chapter_index, passes as previous_chapter_index" → Task 3. ✅
- "Client-side changes → main_widget.py _on_publish_done ... call set_document_wp_status whenever created or updated" → Task 4. ✅
- "Confirm-dialog copy" overwrite warning → Task 3. ✅
- "Testing → tests/test_db.py round-trip for wp_chapter_index" → Task 1. ✅
- "Testing → build_payload includes previous_chapter_index only when differs" → Task 2. ✅
- "Testing → _on_publish_done updates local wp_status when updated: true" → Task 4. ✅
- Server-side plugin logic (`update_chapter_page`, `update_toc_entry`, `update_post`, partial-failure recovery, manual smoke-test checklist) — explicitly out of scope (separate repo, not checked out here); flagged in Global Constraints rather than silently dropped.

**Placeholder scan:** no TBD/TODO, every step has runnable code and exact pytest invocations.

**Type consistency:** `get_document_wp_status` return dict key `wp_chapter_index` used consistently in Tasks 1, 3, 4. `build_payload(previous_chapter_index=...)` name matches Task 2 and its Task 3 call site. `self._last_wp_chapter_index` name matches between where Task 3 sets it and Task 4 reads it.

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-01-wp-republish-update.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?

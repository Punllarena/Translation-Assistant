# WordPress Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Publish to WordPress" to Translation Assistant via the companion ta-publisher WP plugin REST endpoint.

**Architecture:** Pure-Python `wp_publisher.py` module handles payload building and HTTP; a `QThread` worker keeps publish non-blocking; new `AppSettings` keys store the endpoint URL and API key globally; two new `series_profiles` columns store slug and short title per series.

**Tech Stack:** PySide6, stdlib `urllib.request` + `json` (no new dependencies), pytest.

## Global Constraints

- No new third-party dependencies — stdlib only for HTTP (`urllib.request`) and JSON (`json`).
- `QSettings("joeglens", "TranslationAssistant")` — never write `QSettings` directly, always through `AppSettings`.
- DB migrations must be idempotent — check column existence with `PRAGMA table_info` before `ALTER TABLE`.
- `wp_publisher.py` must have zero Qt imports — pure Python only.
- `api_key` travels in the payload body (not a header).
- Tests run with `pytest tests/<file>.py -q`.
- `source .venv/bin/activate` before all commands.

---

### Task 1: DB migration — add `series_slug` and `series_title_short` to `series_profiles`

**Files:**
- Modify: `translation_assistant/db.py:109-115` (idempotent migration block for `series_profiles`)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `db.get_series_wp_meta(series_title: str) -> dict` — returns `{"series_slug": str, "series_title_short": str, "syosetu_url": str}`
  - `db.set_series_wp_meta(series_title: str, series_slug: str, series_title_short: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# In tests/test_db.py — add after existing series tests

def test_series_wp_meta_defaults(db):
    db.set_series_profile("MySeries", "p1")
    meta = db.get_series_wp_meta("MySeries")
    assert meta["series_slug"] == ""
    assert meta["series_title_short"] == ""
    assert meta["syosetu_url"] == ""

def test_set_series_wp_meta(db):
    db.set_series_profile("MySeries", "p1")
    db.set_series_wp_meta("MySeries", "my-series", "MS")
    meta = db.get_series_wp_meta("MySeries")
    assert meta["series_slug"] == "my-series"
    assert meta["series_title_short"] == "MS"

def test_series_wp_meta_unknown_series(db):
    meta = db.get_series_wp_meta("NonExistent")
    assert meta["series_slug"] == ""
    assert meta["series_title_short"] == ""
    assert meta["syosetu_url"] == ""
```

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate && pytest tests/test_db.py -k "wp_meta" -q
```
Expected: `AttributeError: 'Database' object has no attribute 'get_series_wp_meta'`

- [ ] **Step 3: Add migration and methods to `db.py`**

In `_apply_schema`, after the existing `syosetu_url` migration block (around line 115), add:

```python
        for col in ("series_slug", "series_title_short"):
            if col not in sp_existing:
                self._conn.execute(
                    f"ALTER TABLE series_profiles ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                )
        self._conn.commit()
```

Then add these two methods to the `Database` class (after `set_series_url`):

```python
    def get_series_wp_meta(self, series_title: str) -> dict:
        row = self._conn.execute(
            "SELECT series_slug, series_title_short, syosetu_url "
            "FROM series_profiles WHERE series_title = ?",
            (series_title,),
        ).fetchone()
        if row is None:
            return {"series_slug": "", "series_title_short": "", "syosetu_url": ""}
        return dict(row)

    def set_series_wp_meta(self, series_title: str, series_slug: str, series_title_short: str) -> None:
        self._conn.execute(
            "INSERT INTO series_profiles (series_title, series_slug, series_title_short) "
            "VALUES (?, ?, ?) ON CONFLICT(series_title) DO UPDATE SET "
            "series_slug = excluded.series_slug, "
            "series_title_short = excluded.series_title_short",
            (series_title, series_slug, series_title_short),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_db.py -k "wp_meta" -q
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add series_slug and series_title_short to series_profiles"
```

---

### Task 2: `AppSettings` — add `wp_endpoint_url` and `wp_api_key`

**Files:**
- Modify: `translation_assistant/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `settings.wp_endpoint_url: str` (property, getter + setter)
  - `settings.wp_api_key: str` (property, getter + setter)

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_settings.py — add after existing property tests

def test_wp_endpoint_url_default(tmp_settings):
    assert tmp_settings.wp_endpoint_url == ""

def test_wp_endpoint_url_roundtrip(tmp_settings):
    tmp_settings.wp_endpoint_url = "https://mysite.com/wp-json/ta-publisher/v1/publish"
    assert tmp_settings.wp_endpoint_url == "https://mysite.com/wp-json/ta-publisher/v1/publish"

def test_wp_api_key_default(tmp_settings):
    assert tmp_settings.wp_api_key == ""

def test_wp_api_key_roundtrip(tmp_settings):
    tmp_settings.wp_api_key = "secret123"
    assert tmp_settings.wp_api_key == "secret123"
```

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate && pytest tests/test_settings.py -k "wp_" -q
```
Expected: `AttributeError: 'AppSettings' object has no attribute 'wp_endpoint_url'`

- [ ] **Step 3: Add properties to `AppSettings`**

In `translation_assistant/settings.py`, after the `last_doc_id` property block, add:

```python
    @property
    def wp_endpoint_url(self) -> str:
        return self._qs.value("WPEndpointUrl", "")

    @wp_endpoint_url.setter
    def wp_endpoint_url(self, value: str) -> None:
        self._qs.setValue("WPEndpointUrl", value)

    @property
    def wp_api_key(self) -> str:
        return self._qs.value("WPApiKey", "")

    @wp_api_key.setter
    def wp_api_key(self, value: str) -> None:
        self._qs.setValue("WPApiKey", value)
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_settings.py -k "wp_" -q
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add wp_endpoint_url and wp_api_key"
```

---

### Task 3: `wp_publisher.py` — pure Python payload builder and HTTP client

**Files:**
- Create: `translation_assistant/wp_publisher.py`
- Create: `tests/test_wp_publisher.py`

**Interfaces:**
- Consumes: `lines: list[dict]` where each dict has `"translated_text": str` (from `db.get_lines`)
- Produces:
  - `slugify(text: str) -> str`
  - `build_chapter_body(lines: list[dict]) -> str` — HTML string of `<p>` tags
  - `get_first_line(lines: list[dict]) -> str` — first non-empty translated_text, plain text
  - `build_payload(doc_meta: dict, series_meta: dict, lines: list[dict], api_key: str) -> dict`
  - `publish(endpoint_url: str, payload: dict, timeout: int = 15) -> dict`
  - `class WPPublishError(Exception)` with `.status_code: int | None` and `.message: str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wp_publisher.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import URLError, HTTPError
from translation_assistant.wp_publisher import (
    slugify, build_chapter_body, get_first_line, build_payload,
    publish, WPPublishError,
)


def test_slugify_basic():
    assert slugify("Sword of the Wanderer") == "sword-of-the-wanderer"

def test_slugify_special_chars():
    assert slugify("Héros & Villain!") == "hros-villain"

def test_slugify_extra_dashes():
    assert slugify("  hello   world  ") == "hello-world"

def test_build_chapter_body_basic():
    lines = [
        {"translated_text": "Hello world"},
        {"translated_text": ""},
        {"translated_text": "Second line"},
    ]
    result = build_chapter_body(lines)
    assert result == "<p>Hello world</p>\n<p>Second line</p>"

def test_build_chapter_body_all_empty():
    lines = [{"translated_text": ""}, {"translated_text": "   "}]
    assert build_chapter_body(lines) == ""

def test_get_first_line_returns_first_nonempty():
    lines = [
        {"translated_text": ""},
        {"translated_text": "First real line"},
        {"translated_text": "Second line"},
    ]
    assert get_first_line(lines) == "First real line"

def test_get_first_line_all_empty():
    lines = [{"translated_text": ""}, {"translated_text": "   "}]
    assert get_first_line(lines) == ""

def _sample_meta():
    doc_meta = {
        "series_title": "Sword of the Wanderer",
        "series_order": 1,
        "chapter_title": "The Beginning",
    }
    series_meta = {
        "series_slug": "sword-of-the-wanderer",
        "series_title_short": "SotW",
        "syosetu_url": "https://ncode.syosetu.com/n1234ab/",
    }
    lines = [{"translated_text": "Hello"}, {"translated_text": "World"}]
    return doc_meta, series_meta, lines

def test_build_payload_chapter():
    doc_meta, series_meta, lines = _sample_meta()
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert payload["api_key"] == "key123"
    assert payload["series_title"] == "Sword of the Wanderer"
    assert payload["series_slug"] == "sword-of-the-wanderer"
    assert payload["series_title_short"] == "SotW"
    assert payload["series_link"] == "https://ncode.syosetu.com/n1234ab/"
    assert payload["chapter_index"] == 1
    assert payload["chapter_title"] == "The Beginning"
    assert payload["chapter_body"] == "<p>Hello</p>\n<p>World</p>"
    assert payload["first_line"] == "Hello"

def test_build_payload_synopsis_omits_first_line():
    doc_meta, series_meta, lines = _sample_meta()
    doc_meta["series_order"] = 0
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert "first_line" not in payload

def test_build_payload_missing_series_slug_raises():
    doc_meta, series_meta, lines = _sample_meta()
    series_meta["series_slug"] = ""
    with pytest.raises(ValueError, match="series_slug"):
        build_payload(doc_meta, series_meta, lines, api_key="key123")

def test_build_payload_missing_series_title_short_raises():
    doc_meta, series_meta, lines = _sample_meta()
    series_meta["series_title_short"] = ""
    with pytest.raises(ValueError, match="series_title_short"):
        build_payload(doc_meta, series_meta, lines, api_key="key123")

def test_publish_success():
    response_data = {"created": True, "page_url": "https://site.com/series/", "post_url": "https://site.com/ch1/"}
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = json.dumps(response_data).encode()
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = publish("https://example.com/endpoint", {"api_key": "k"})
    assert result["created"] is True

def test_publish_http_error_raises_wp_publish_error():
    err = HTTPError("url", 401, "Unauthorized", {}, None)
    err.read = lambda: b'{"message": "bad key"}'
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(WPPublishError) as exc_info:
            publish("https://example.com/endpoint", {"api_key": "k"})
    assert exc_info.value.status_code == 401

def test_publish_connection_error_raises_wp_publish_error():
    with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
        with pytest.raises(WPPublishError) as exc_info:
            publish("https://example.com/endpoint", {"api_key": "k"})
    assert exc_info.value.status_code is None
```

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate && pytest tests/test_wp_publisher.py -q
```
Expected: `ModuleNotFoundError: No module named 'translation_assistant.wp_publisher'`

- [ ] **Step 3: Create `translation_assistant/wp_publisher.py`**

```python
"""
WordPress publish — payload builder and HTTP client. No Qt imports.
"""
import json
import re
import unicodedata
import urllib.request
from urllib.error import HTTPError, URLError


class WPPublishError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def build_chapter_body(lines: list[dict]) -> str:
    parts = [f"<p>{ln['translated_text']}</p>" for ln in lines if ln["translated_text"].strip()]
    return "\n".join(parts)


def get_first_line(lines: list[dict]) -> str:
    for ln in lines:
        if ln["translated_text"].strip():
            return ln["translated_text"]
    return ""


def build_payload(doc_meta: dict, series_meta: dict, lines: list[dict], api_key: str) -> dict:
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")

    payload: dict = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta["syosetu_url"],
        "chapter_index":      doc_meta["series_order"],
        "chapter_title":      doc_meta["chapter_title"],
        "chapter_body":       build_chapter_body(lines),
    }
    if doc_meta["series_order"] != 0:
        payload["first_line"] = get_first_line(lines)
    return payload


def publish(endpoint_url: str, payload: dict, timeout: int = 15) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
            msg = body.get("message", str(exc))
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(f"Could not reach {endpoint_url}: {exc.reason}", status_code=None) from exc
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_wp_publisher.py -q
```
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat: add wp_publisher module — payload builder, slugify, HTTP publish"
```

---

### Task 4: WP Settings dialog (`dlg_wp_settings.py`)

**Files:**
- Create: `translation_assistant/ui/dlg_wp_settings.py`
- Test: `tests/test_dialogs.py` (add to existing file)

**Interfaces:**
- Consumes: `AppSettings` (with `wp_endpoint_url`, `wp_api_key` from Task 2), `wp_publisher.publish` (for Test Connection)
- Produces: `WPSettingsDialog(settings: AppSettings, parent=None)` — modal `QDialog`; on accept, saves endpoint URL and API key to `settings`.

- [ ] **Step 1: Write failing test**

In `tests/test_dialogs.py`, add:

```python
def test_wp_settings_dialog_loads(qapp, tmp_settings):
    from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
    dlg = WPSettingsDialog(tmp_settings)
    assert dlg.windowTitle() == "WordPress Settings"
    dlg.reject()

def test_wp_settings_dialog_saves_on_accept(qapp, tmp_settings):
    from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
    from unittest.mock import patch
    dlg = WPSettingsDialog(tmp_settings)
    dlg._url_edit.setText("https://example.com/wp-json/ta-publisher/v1/publish")
    dlg._key_edit.setText("my-api-key")
    with patch.object(dlg, "accept"):
        dlg._on_save()
    assert tmp_settings.wp_endpoint_url == "https://example.com/wp-json/ta-publisher/v1/publish"
    assert tmp_settings.wp_api_key == "my-api-key"
```

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -k "wp_settings" -q
```
Expected: `ModuleNotFoundError: No module named 'translation_assistant.ui.dlg_wp_settings'`

- [ ] **Step 3: Create `translation_assistant/ui/dlg_wp_settings.py`**

```python
"""
WordPress Settings dialog — endpoint URL and API key.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from translation_assistant.settings import AppSettings


class WPSettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("WordPress Settings")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)

        self._url_edit = QLineEdit(self._settings.wp_endpoint_url)
        self._url_edit.setPlaceholderText("https://yoursite.com/wp-json/ta-publisher/v1/publish")
        form.addRow("Endpoint URL:", self._url_edit)

        self._key_edit = QLineEdit(self._settings.wp_api_key)
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("API key from WP Admin → Settings → TA Publisher")
        form.addRow("API Key:", self._key_edit)

        layout.addLayout(form)

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._on_test)
        layout.addWidget(self._test_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        self._settings.wp_endpoint_url = self._url_edit.text().strip()
        self._settings.wp_api_key = self._key_edit.text().strip()
        self.accept()

    def _on_test(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter an endpoint URL first.")
            return
        import json
        import urllib.request
        from urllib.error import URLError, HTTPError
        try:
            data = json.dumps({}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            QMessageBox.information(self, "Connection OK", "Endpoint reached.")
        except HTTPError as exc:
            if exc.code == 400:
                QMessageBox.information(self, "Connection OK", "Endpoint reached (400 = missing fields, as expected).")
            elif exc.code == 401:
                QMessageBox.warning(self, "Auth Error", "Endpoint reachable but API key rejected (401).")
            else:
                QMessageBox.warning(self, "HTTP Error", f"HTTP {exc.code}: {exc.reason}")
        except URLError as exc:
            QMessageBox.critical(self, "Connection Failed", f"Could not reach endpoint:\n{exc.reason}")
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -k "wp_settings" -q
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_wp_settings.py tests/test_dialogs.py
git commit -m "feat(ui): add WordPress Settings dialog"
```

---

### Task 5: Series Manager — add slug and short title fields

**Files:**
- Modify: `translation_assistant/ui/dlg_series.py`
- Test: `tests/test_dialogs.py` (add)

**Interfaces:**
- Consumes: `db.get_series_wp_meta(series_title)` and `db.set_series_wp_meta(series_title, series_slug, series_title_short)` from Task 1; `slugify(text)` from Task 3.
- Produces: Updated `SeriesManagerDialog` with **Set WP Fields…** button that opens an inline editor for slug and short title.

- [ ] **Step 1: Write failing tests**

In `tests/test_dialogs.py`, add:

```python
def test_series_manager_has_wp_fields_button(qapp, tmp_db):
    from translation_assistant.ui.dlg_series import SeriesManagerDialog
    dlg = SeriesManagerDialog(tmp_db)
    assert hasattr(dlg, "_set_wp_btn")
    dlg.reject()

def test_series_manager_wp_btn_disabled_with_no_selection(qapp, tmp_db):
    from translation_assistant.ui.dlg_series import SeriesManagerDialog
    dlg = SeriesManagerDialog(tmp_db)
    assert not dlg._set_wp_btn.isEnabled()
    dlg.reject()
```

(Note: `tmp_db` fixture already exists in `conftest.py` as the in-memory database fixture. Check `conftest.py` — if the fixture is named differently, use the correct name.)

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -k "series_manager_wp" -q
```
Expected: `AttributeError: 'SeriesManagerDialog' object has no attribute '_set_wp_btn'`

- [ ] **Step 3: Update `dlg_series.py`**

Add `_set_wp_btn` to `_setup_ui`, after `_set_url_btn`:

```python
        self._set_wp_btn = QPushButton("Set WP Fields…")
        self._set_wp_btn.setEnabled(False)
        self._set_wp_btn.clicked.connect(self._on_set_wp_fields)
```

Add it to `btn_row` (before `close_btn`):

```python
        btn_row.addWidget(self._set_wp_btn)
```

Update `_on_row_changed` to enable the button when a row is selected:

```python
    def _on_row_changed(self, row: int) -> None:
        s = self._current_series()
        self._set_url_btn.setEnabled(s is not None)
        self._set_wp_btn.setEnabled(s is not None)
        self._fetch_btn.setEnabled(s is not None and bool(s["url"]))
```

Add `_on_set_wp_fields` method:

```python
    def _on_set_wp_fields(self) -> None:
        s = self._current_series()
        if s is None:
            return
        from translation_assistant.wp_publisher import slugify
        meta = self._db.get_series_wp_meta(s["title"])
        current_slug = meta["series_slug"] or slugify(s["title"])
        current_short = meta["series_title_short"]

        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout
        from PySide6.QtCore import Qt
        dlg = QDialog(self)
        dlg.setWindowTitle(f"WP Fields — {s['title']}")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        slug_edit = QLineEdit(current_slug)
        slug_edit.setPlaceholderText("url-safe-slug")
        short_edit = QLineEdit(current_short)
        short_edit.setPlaceholderText("Abbreviation")
        form.addRow("Series Slug:", slug_edit)
        form.addRow("Short Title:", short_edit)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec():
            self._db.set_series_wp_meta(s["title"], slug_edit.text().strip(), short_edit.text().strip())
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -k "series_manager_wp" -q
```
Expected: 2 passed.

- [ ] **Step 5: Run full dialog suite**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -q
```
Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_series.py tests/test_dialogs.py
git commit -m "feat(ui): add WP Fields button to Series Manager"
```

---

### Task 6: Wire menu action and publish flow in `main_widget.py` and `combined_window.py`

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`
- Test: `tests/test_main_window.py` or `tests/test_combined_window.py` (add)

**Interfaces:**
- Consumes: `wp_publisher.build_payload`, `wp_publisher.publish`, `WPPublishError`, `WPSettingsDialog`, `db.get_series_wp_meta`, `db.get_lines`, `db.get_document`, `settings.wp_endpoint_url`, `settings.wp_api_key` — all from prior tasks.
- Produces:
  - `TranslationAssistantWidget.action_publish_wp: QAction`
  - `TranslationAssistantWidget._on_publish_wp() -> None`
  - `_PublishWorker(QThread)` in `main_widget.py`
  - Menu entry "Publish to WordPress" in File menu (after Export actions)
  - Menu entry "WordPress Settings…" in Settings/Preferences menu

- [ ] **Step 1: Write failing tests**

In `tests/test_combined_window.py`, add:

```python
def test_action_publish_wp_exists(combined_window):
    from translation_assistant.ui.main_widget import TranslationAssistantWidget
    ta = combined_window.findChild(TranslationAssistantWidget)
    assert hasattr(ta, "action_publish_wp")

def test_action_publish_wp_disabled_with_no_doc(combined_window):
    from translation_assistant.ui.main_widget import TranslationAssistantWidget
    ta = combined_window.findChild(TranslationAssistantWidget)
    assert not ta.action_publish_wp.isEnabled()
```

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate && pytest tests/test_combined_window.py -k "publish_wp" -q
```
Expected: `AttributeError: 'TranslationAssistantWidget' object has no attribute 'action_publish_wp'`

- [ ] **Step 3: Add action and worker to `main_widget.py`**

In `_build_actions`, add after `action_export`:

```python
        self.action_publish_wp = QAction("Publish to WordPress…", self)
        self.action_publish_wp.triggered.connect(self._on_publish_wp)
        self.action_publish_wp.setEnabled(False)
```

Enable/disable it alongside `action_export` — search for `self.action_export.setEnabled(` calls and mirror them for `action_publish_wp`.

Add the `_PublishWorker` class near the top of `main_widget.py` (after imports):

```python
from PySide6.QtCore import QThread, Signal as _Signal

class _PublishWorker(QThread):
    finished = _Signal(dict)
    error = _Signal(str)

    def __init__(self, endpoint_url: str, payload: dict, parent=None) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._payload = payload

    def run(self) -> None:
        from translation_assistant.wp_publisher import publish, WPPublishError
        try:
            result = publish(self._endpoint_url, self._payload)
            self.finished.emit(result)
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:
            self.error.emit(str(exc))
```

Add `_on_publish_wp` method to `TranslationAssistantWidget`:

```python
    def _on_publish_wp(self) -> None:
        from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
        from translation_assistant.wp_publisher import build_payload, WPPublishError

        endpoint_url = self._settings.wp_endpoint_url
        api_key = self._settings.wp_api_key
        if not endpoint_url or not api_key:
            dlg = WPSettingsDialog(self._settings, parent=self)
            if not dlg.exec():
                return
            endpoint_url = self._settings.wp_endpoint_url
            api_key = self._settings.wp_api_key
            if not endpoint_url or not api_key:
                return

        doc_meta = self._db.get_document(self._doc_id)
        series_title = doc_meta["series_title"]
        series_meta = self._db.get_series_wp_meta(series_title)

        if not series_meta["series_slug"] or not series_meta["series_title_short"]:
            from translation_assistant.ui.dlg_series import SeriesManagerDialog
            QMessageBox.information(
                self,
                "WP Fields Missing",
                f'Set "Series Slug" and "Short Title" for "{series_title}" in Series Manager.',
            )
            dlg = SeriesManagerDialog(self._db, parent=self)
            dlg.exec()
            series_meta = self._db.get_series_wp_meta(series_title)
            if not series_meta["series_slug"] or not series_meta["series_title_short"]:
                return

        lines = self._db.get_lines(self._doc_id)
        if not any(ln["translated_text"].strip() for ln in lines):
            QMessageBox.warning(self, "Nothing to Publish", "No translated lines to publish.")
            return

        try:
            payload = build_payload(doc_meta, series_meta, lines, api_key=api_key)
        except ValueError as exc:
            QMessageBox.warning(self, "Payload Error", str(exc))
            return

        chapter_label = "Synopsis" if doc_meta["series_order"] == 0 else f"Chapter {doc_meta['series_order']}"
        confirm = QMessageBox.question(
            self,
            "Publish to WordPress",
            f"Publish <b>{doc_meta['chapter_title']}</b> ({chapter_label}) to WordPress?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._publish_worker = _PublishWorker(endpoint_url, payload, parent=self)
        self._publish_worker.finished.connect(self._on_publish_done)
        self._publish_worker.error.connect(self._on_publish_error)
        self._publish_worker.start()

    def _on_publish_done(self, result: dict) -> None:
        page_url = result.get("page_url", "")
        post_url = result.get("post_url", "")
        if result.get("created") is False:
            msg = f"Already published.\nPage: {page_url}"
        else:
            msg = f"Published!\nPage: {page_url}\nPost: {post_url}"
        QMessageBox.information(self, "WordPress Publish", msg)

    def _on_publish_error(self, message: str) -> None:
        QMessageBox.warning(self, "Publish Failed", message)
```

Note: ensure `QMessageBox` is in the imports at the top of `main_widget.py`. Check the existing imports and add if missing.

- [ ] **Step 4: Wire menu in `combined_window.py`**

In `_setup_menubar`, after the Markdown export submenu block (after `file_menu.addAction(ta.action_export_md_ruby_series)` area), add:

```python
        file_menu.addSeparator()
        file_menu.addAction(ta.action_publish_wp)
```

In the Settings menu section, add:

```python
        settings_menu.addSeparator()
        wp_settings_action = QAction("WordPress Settings…", self)
        wp_settings_action.triggered.connect(self._on_wp_settings)
        settings_menu.addAction(wp_settings_action)
```

Add `_on_wp_settings` to `CombinedMainWindow`:

```python
    def _on_wp_settings(self) -> None:
        from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
        dlg = WPSettingsDialog(self._ta_widget._settings, parent=self)
        dlg.exec()
```

- [ ] **Step 5: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_combined_window.py -k "publish_wp" -q
```
Expected: 2 passed.

- [ ] **Step 6: Run full suite**

```bash
source .venv/bin/activate && pytest -q
```
Expected: all tests pass (535+).

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py
git commit -m "feat(ui): wire Publish to WordPress action and QThread publish flow"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|---|---|
| `series_slug`, `series_title_short` columns on `series_profiles` | Task 1 |
| `AppSettings.wp_endpoint_url`, `wp_api_key` | Task 2 |
| `wp_publisher.py` with all functions + `WPPublishError` | Task 3 |
| `slugify` in `wp_publisher.py` | Task 3 |
| `dlg_wp_settings.py` — endpoint, API key, Test Connection | Task 4 |
| Series Manager — slug and short title fields | Task 5 |
| `action_publish_wp` enabled only when doc open | Task 6 |
| `_on_publish_wp` — 10-step flow per spec | Task 6 |
| `_PublishWorker` QThread — non-blocking | Task 6 |
| Success result with page_url and post_url | Task 6 |
| `build_payload` — `first_line` omitted for chapter_index==0 | Task 3 |
| No new dependencies (stdlib only for HTTP) | Task 3 |
| All error conditions (401, 400, 409, timeout, etc.) | Task 3 (WPPublishError), Task 6 (_on_publish_error) |

**409 / `created: false`:** The spec says treat as non-error and show page URL. `_on_publish_done` handles this via `result.get("created") is False`.

### Placeholder scan

No TBDs. All code shown. All types defined before use.

### Type consistency

- `db.get_series_wp_meta` returns `dict` with keys `series_slug`, `series_title_short`, `syosetu_url` — used consistently in Task 3 `build_payload` and Task 6 `_on_publish_wp`.
- `_PublishWorker` defined in Task 6 and only used in Task 6.
- `WPPublishError` defined in Task 3, imported in Task 6.

# WP Status, Safeguard & Default Schedule Time — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WP publish status checking (plugin GET endpoint + app DB cache), a publish safeguard that blocks posting chapter N if chapter N−1 is still scheduled, and a default schedule time preference.

**Architecture:** New REST endpoint in the WP plugin returns chapter status; app caches it in two new `documents` columns; status surfaces in the status bar, publish dialog, and doc list; safeguard reads cached status before every publish.

**Tech Stack:** PHP (WordPress REST API), Python 3.11+, PySide6 6.x, SQLite via `db.py`, pytest

## Global Constraints

- Python 3.11+, PySide6 6.x, SQLite — never import `sqlite3` outside `db.py`
- All schema migrations idempotent via `PRAGMA table_info` check in `_apply_schema()`
- `wp_publisher.py` must stay Qt-free — pure Python only
- Tests use `qapp` and `tmp_settings` fixtures from `conftest.py`; DB tests use in-memory SQLite via `Database(":memory:", _conn=conn)`
- Run tests: `source .venv/bin/activate && pytest <file> -q`
- Commit prefix: `feat:`

---

## File Map

| File | Change |
|------|--------|
| `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/translation-assistant-publisher.php` | Add `GET /status` route + handler |
| `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/includes/class-publisher.php` | Add `get_chapter_status()` method |
| `translation_assistant/wp_publisher.py` | Add `check_status()`, `import urllib.parse` |
| `translation_assistant/db.py` | Add `wp_status`/`wp_post_url` columns, 3 new methods, update `list_documents()` |
| `translation_assistant/settings.py` | Add `wp_default_schedule_time` property |
| `translation_assistant/ui/dlg_wp_settings.py` | Add schedule time checkbox + `QTimeEdit` |
| `translation_assistant/ui/main_widget.py` | Add `_StatusCheckWorker`, `_wp_status_label`, status recording, dialog changes |
| `translation_assistant/ui/dlg_open.py` | Add WP column to tree |
| `tests/test_wp_publisher.py` | Add `check_status` tests |
| `tests/test_db.py` | Add wp_status column and method tests |
| `tests/test_settings.py` | Add `wp_default_schedule_time` tests |
| `tests/test_dialogs.py` | Add WP settings dialog schedule time tests |
| `tests/test_combined_window.py` | Add status bar label test |
| `tests/test_dlg_open.py` | Add WP column tests |

---

### Task 1: WP Plugin — Status Endpoint

**Files:**
- Modify: `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/translation-assistant-publisher.php`
- Modify: `/home/pun/workspace/wp-dev/plugins/translation-assistant-publisher/includes/class-publisher.php`

**Interfaces:**
- Produces: `GET /wp-json/ta-publisher/v1/status?api_key=&series_slug=&chapter=N`
  → `{"status": "publish"|"future"|"draft"|"not_found", "post_url": "<url>"|null}`

- [ ] **Step 1: Add `get_chapter_status()` to `class-publisher.php`**

In `TAP_Publisher`, after the `chapter_exists()` method (around line 112):

```php
public function get_chapter_status( string $series_slug, int $chapter_idx ): array {
    if ( $chapter_idx === 0 ) {
        $page = get_page_by_path( $series_slug, OBJECT, 'page' );
    } else {
        $page = $this->chapter_exists( $series_slug, $chapter_idx );
    }

    if ( ! $page ) {
        return [ 'status' => 'not_found', 'post_url' => null ];
    }

    return [
        'status'   => $page->post_status,
        'post_url' => get_permalink( $page->ID ),
    ];
}
```

- [ ] **Step 2: Register `/status` route in `translation-assistant-publisher.php`**

Inside the `rest_api_init` action, after the existing `/publish` route registration (around line 24):

```php
    register_rest_route( 'ta-publisher/v1', '/status', [
        'methods'             => 'GET',
        'callback'            => 'tap_handle_status',
        'permission_callback' => '__return_true',
    ] );
```

After the `tap_handle_publish()` function, add:

```php
function tap_handle_status( WP_REST_Request $request ): WP_REST_Response {
    $api_key     = $request->get_param( 'api_key' ) ?? '';
    $series_slug = sanitize_title( $request->get_param( 'series_slug' ) ?? '' );
    $chapter     = (int) ( $request->get_param( 'chapter' ) ?? -1 );

    if ( ! TAP_Auth::validate( $api_key ) ) {
        return new WP_REST_Response( [ 'error' => 'Invalid API key' ], 401 );
    }
    if ( $series_slug === '' || $chapter < 0 ) {
        return new WP_REST_Response( [ 'error' => 'Missing series_slug or chapter' ], 400 );
    }

    $publisher = new TAP_Publisher();
    $result    = $publisher->get_chapter_status( $series_slug, $chapter );
    return new WP_REST_Response( $result, 200 );
}
```

- [ ] **Step 3: Manual smoke test**

```bash
curl -s "http://localhost:8888/wp-json/ta-publisher/v1/status?api_key=YOUR_KEY&series_slug=test-series&chapter=1"
```

Expected: `{"status":"not_found","post_url":null}`

- [ ] **Step 4: Commit**

```bash
cd /home/pun/workspace/wp-dev
git add plugins/translation-assistant-publisher/translation-assistant-publisher.php \
        plugins/translation-assistant-publisher/includes/class-publisher.php
git commit -m "feat: add GET /status endpoint to WP publisher plugin"
```

---

### Task 2: `check_status()` in `wp_publisher.py`

**Files:**
- Modify: `translation_assistant/wp_publisher.py`
- Test: `tests/test_wp_publisher.py`

**Interfaces:**
- Produces: `check_status(endpoint_url: str, api_key: str, series_slug: str, chapter: int, timeout: int = 10) -> dict`
  — returns `{"status": "...", "post_url": "..."|None}`, raises `WPPublishError` on failure

- [ ] **Step 1: Write failing tests**

In `tests/test_wp_publisher.py`, add at the bottom (the imports `json`, `pytest`, `patch`, `MagicMock`, `URLError`, `HTTPError`, `WPPublishError` are already present):

```python
from translation_assistant.wp_publisher import check_status


def test_check_status_success():
    response_data = {"status": "future", "post_url": "https://example.com/series-c1/"}
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(response_data).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        result = check_status(
            "https://example.com/wp-json/ta-publisher/v1/publish",
            "key123", "my-series", 1,
        )
    assert result == {"status": "future", "post_url": "https://example.com/series-c1/"}
    called_url = mock_open.call_args[0][0].full_url
    assert "/wp-json/ta-publisher/v1/status" in called_url
    assert "series_slug=my-series" in called_url
    assert "chapter=1" in called_url


def test_check_status_derives_url_strips_publish_suffix():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({"status": "publish", "post_url": None}).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        check_status(
            "https://example.com/wp-json/ta-publisher/v1/publish",
            "k", "s", 0,
        )
    url = mock_open.call_args[0][0].full_url
    assert url.startswith("https://example.com/wp-json/ta-publisher/v1/status")


def test_check_status_401_raises():
    exc = HTTPError("url", 401, "Unauthorized", {}, None)
    exc.read = lambda: b'{"message": "Invalid API key"}'
    with patch("urllib.request.urlopen", side_effect=exc):
        with pytest.raises(WPPublishError) as info:
            check_status(
                "https://example.com/wp-json/ta-publisher/v1/publish",
                "bad", "s", 1,
            )
    assert info.value.status_code == 401


def test_check_status_network_error_raises():
    with patch("urllib.request.urlopen", side_effect=URLError("refused")):
        with pytest.raises(WPPublishError):
            check_status(
                "https://example.com/wp-json/ta-publisher/v1/publish",
                "k", "s", 1,
            )
```

- [ ] **Step 2: Run — verify fail**

```bash
source .venv/bin/activate && pytest tests/test_wp_publisher.py::test_check_status_success -q
```

Expected: `ImportError: cannot import name 'check_status'`

- [ ] **Step 3: Implement `check_status()` in `wp_publisher.py`**

At the top of `translation_assistant/wp_publisher.py`, add `import urllib.parse` after `import urllib.request`.

Then add after `normalize_endpoint_url()`:

```python
_STATUS_PATH = "/wp-json/ta-publisher/v1/status"


def check_status(
    endpoint_url: str,
    api_key: str,
    series_slug: str,
    chapter: int,
    timeout: int = 10,
) -> dict:
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "series_slug": series_slug,
        "chapter": chapter,
    })
    url = f"{base}{_STATUS_PATH}?{params}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise WPPublishError(
                    f"Server returned non-JSON response: {body[:200]!r}",
                    status_code=None,
                )
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
            msg = body.get("message", str(exc))
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(
            f"Could not reach {url}: {exc.reason}", status_code=None
        ) from exc
```

`_ENDPOINT_PATH` is already defined at module level as `"/wp-json/ta-publisher/v1/publish"`.

- [ ] **Step 4: Run all wp_publisher tests**

```bash
pytest tests/test_wp_publisher.py -q
```

Expected: all pass (existing + 4 new)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat: add check_status() to wp_publisher"
```

---

### Task 3: DB Schema & Status Methods

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `db.set_document_wp_status(doc_id: int, status: str, post_url: str | None) -> None`
  - `db.get_document_wp_status(doc_id: int) -> dict`  — `{"wp_status": str|None, "wp_post_url": str|None}`
  - `db.get_wp_status_by_series_position(series_title: str, series_order: int) -> dict | None`
  - `db.list_documents()` dicts now include `"wp_status"` key

- [ ] **Step 1: Write failing tests**

In `tests/test_db.py`, add at the bottom. The file's in-memory fixture is named `db` (not `mem_db`).

```python
def test_wp_status_columns_exist(db):
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(documents)").fetchall()}
    assert "wp_status" in cols
    assert "wp_post_url" in cols


def test_get_document_wp_status_defaults_none(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    info = db.get_document_wp_status(doc_id)
    assert info == {"wp_status": None, "wp_post_url": None}


def test_set_and_get_document_wp_status(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    db.set_document_wp_status(doc_id, "future", "https://ex.com/ch1/")
    info = db.get_document_wp_status(doc_id)
    assert info["wp_status"] == "future"
    assert info["wp_post_url"] == "https://ex.com/ch1/"


def test_set_document_wp_status_can_clear_url(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    db.set_document_wp_status(doc_id, "future", "https://ex.com/ch1/")
    db.set_document_wp_status(doc_id, "publish", None)
    assert db.get_document_wp_status(doc_id)["wp_post_url"] is None


def test_get_wp_status_by_series_position_found(db):
    doc_id = db.create_document("Ch 1", series_title="MySeries", series_order=1)
    db.set_document_wp_status(doc_id, "future", "https://ex.com/ch1/")
    result = db.get_wp_status_by_series_position("MySeries", 1)
    assert result == {"wp_status": "future", "wp_post_url": "https://ex.com/ch1/"}


def test_get_wp_status_by_series_position_not_found(db):
    assert db.get_wp_status_by_series_position("NoSeries", 99) is None


def test_list_documents_includes_wp_status(db):
    doc_id = db.create_document("Ch 1", series_title="S", series_order=1)
    db.set_document_wp_status(doc_id, "publish", "https://ex.com/ch1/")
    docs = db.list_documents()
    doc = next(d for d in docs if d["id"] == doc_id)
    assert doc["wp_status"] == "publish"
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_db.py::test_wp_status_columns_exist -q
```

Expected: FAIL — column does not exist yet

- [ ] **Step 3: Add columns in `_apply_schema()`**

In `translation_assistant/db.py`, after the `source_url` migration block (after line 140):

```python
        # Idempotent column migrations for WP publish status on documents
        wp_doc_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()}
        for col, defn in [
            ("wp_status",   "TEXT DEFAULT NULL"),
            ("wp_post_url", "TEXT DEFAULT NULL"),
        ]:
            if col not in wp_doc_existing:
                self._conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {defn}")
        self._conn.commit()
```

- [ ] **Step 4: Add three new DB methods**

In `translation_assistant/db.py`, after `get_document()` (after line 448):

```python
    def set_document_wp_status(self, doc_id: int, status: str, post_url: str | None) -> None:
        self._conn.execute(
            "UPDATE documents SET wp_status = ?, wp_post_url = ? WHERE id = ?",
            (status, post_url, doc_id),
        )
        self._conn.commit()

    def get_document_wp_status(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT wp_status, wp_post_url FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return {"wp_status": None, "wp_post_url": None}
        return dict(row)

    def get_wp_status_by_series_position(
        self, series_title: str, series_order: int
    ) -> dict | None:
        row = self._conn.execute(
            "SELECT wp_status, wp_post_url FROM documents "
            "WHERE series_title = ? AND series_order = ?",
            (series_title, series_order),
        ).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 5: Update `list_documents()` to include `wp_status`**

In `list_documents()`, change the SELECT (replace the entire method body):

```python
    def list_documents(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT d.id, d.title, d.series_title, d.series_order, d.chapter_title,
                   d.updated_at, d.last_position, d.source_url, d.wp_status,
                   CAST(COALESCE(
                       SUM(CASE WHEN TRIM(l.raw_text) != '' AND l.translated_text != '' THEN 1 ELSE 0 END) * 100
                       / NULLIF(SUM(CASE WHEN TRIM(l.raw_text) != '' THEN 1 ELSE 0 END), 0), 0
                   ) AS INTEGER) AS progress
            FROM documents d
            LEFT JOIN lines l ON l.document_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 6: Run all DB tests**

```bash
pytest tests/test_db.py -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat: add wp_status/wp_post_url columns and status methods to db"
```

---

### Task 4: Settings Property & WP Settings Dialog Row

**Files:**
- Modify: `translation_assistant/settings.py`
- Modify: `translation_assistant/ui/dlg_wp_settings.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_dialogs.py`

**Interfaces:**
- Produces: `settings.wp_default_schedule_time: str` — `"HH:MM"` or `""`

- [ ] **Step 1: Write failing settings tests**

In `tests/test_settings.py`, add:

```python
def test_wp_default_schedule_time_default(tmp_settings):
    assert tmp_settings.wp_default_schedule_time == ""

def test_wp_default_schedule_time_roundtrip(tmp_settings):
    tmp_settings.wp_default_schedule_time = "20:00"
    assert tmp_settings.wp_default_schedule_time == "20:00"
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_settings.py::test_wp_default_schedule_time_default -q
```

Expected: FAIL — `AttributeError`

- [ ] **Step 3: Add property to `settings.py`**

In `translation_assistant/settings.py`, after the `wp_unlock_after` setter (after line 192):

```python
    @property
    def wp_default_schedule_time(self) -> str:
        return self._qs.value("WPDefaultScheduleTime", "")

    @wp_default_schedule_time.setter
    def wp_default_schedule_time(self, value: str) -> None:
        self._qs.setValue("WPDefaultScheduleTime", value)
```

- [ ] **Step 4: Run settings tests**

```bash
pytest tests/test_settings.py -q
```

Expected: all pass

- [ ] **Step 5: Write failing dialog tests**

In `tests/test_dialogs.py`, add after `test_wp_settings_dialog_saves_on_accept`. `patch` is already imported at the top of the file.

```python
def test_wp_settings_dialog_has_schedule_time_controls(qapp, tmp_settings):
    from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
    dlg = WPSettingsDialog(tmp_settings)
    assert hasattr(dlg, "_schedule_cb")
    assert hasattr(dlg, "_schedule_time_edit")
    dlg.reject()


def test_wp_settings_dialog_saves_schedule_time_when_checked(qapp, tmp_settings):
    from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
    from PySide6.QtCore import QTime
    dlg = WPSettingsDialog(tmp_settings)
    dlg._schedule_cb.setChecked(True)
    dlg._schedule_time_edit.setTime(QTime(20, 30))
    with patch.object(dlg, "accept"):
        dlg._on_save()
    assert tmp_settings.wp_default_schedule_time == "20:30"


def test_wp_settings_dialog_clears_schedule_time_when_unchecked(qapp, tmp_settings):
    from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog
    tmp_settings.wp_default_schedule_time = "20:00"
    dlg = WPSettingsDialog(tmp_settings)
    dlg._schedule_cb.setChecked(False)
    with patch.object(dlg, "accept"):
        dlg._on_save()
    assert tmp_settings.wp_default_schedule_time == ""
```

- [ ] **Step 6: Run — verify fail**

```bash
pytest tests/test_dialogs.py::test_wp_settings_dialog_has_schedule_time_controls -q
```

Expected: FAIL — `AttributeError: _schedule_cb`

- [ ] **Step 7: Update `dlg_wp_settings.py` imports**

Change the `PySide6.QtWidgets` import to add `QTimeEdit`:

```python
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout,
)
```

Change the `PySide6.QtCore` import to add `QTime`:

```python
from PySide6.QtCore import Qt, QTime
```

- [ ] **Step 8: Add schedule time controls in `_setup_ui()`**

In `_setup_ui()`, after the `_unlock_spin` form row (after `form.addRow("Keep N chapters locked:", self._unlock_spin)`):

```python
        sched_time = self._settings.wp_default_schedule_time
        self._schedule_cb = QCheckBox("Set default schedule time")
        self._schedule_cb.setChecked(bool(sched_time))
        form.addRow("", self._schedule_cb)

        self._schedule_time_edit = QTimeEdit()
        self._schedule_time_edit.setDisplayFormat("HH:mm")
        if sched_time:
            h, m = map(int, sched_time.split(":"))
            self._schedule_time_edit.setTime(QTime(h, m))
        else:
            self._schedule_time_edit.setTime(QTime(20, 0))
        self._schedule_time_edit.setEnabled(bool(sched_time))
        self._schedule_cb.toggled.connect(self._schedule_time_edit.setEnabled)
        form.addRow("Time:", self._schedule_time_edit)
```

- [ ] **Step 9: Save schedule time in `_on_save()`**

In `_on_save()`, after `self._settings.wp_unlock_after = self._unlock_spin.value()`:

```python
        if self._schedule_cb.isChecked():
            self._settings.wp_default_schedule_time = self._schedule_time_edit.time().toString("HH:mm")
        else:
            self._settings.wp_default_schedule_time = ""
```

- [ ] **Step 10: Run all dialog tests**

```bash
pytest tests/test_dialogs.py -q
```

Expected: all pass

- [ ] **Step 11: Commit**

```bash
git add translation_assistant/settings.py translation_assistant/ui/dlg_wp_settings.py \
        tests/test_settings.py tests/test_dialogs.py
git commit -m "feat: add wp_default_schedule_time setting and WP settings dialog row"
```

---

### Task 5: Post-Publish Status Recording & Status Bar Label

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Test: `tests/test_combined_window.py`

**Interfaces:**
- Consumes: `db.set_document_wp_status()`, `db.get_document_wp_status()` (Task 3); `_ClickableLabel` (already in `main_widget.py`)
- Produces: `self._wp_status_label` (`_ClickableLabel` in status bar); `self._update_wp_status_label()` (called by Task 6)

- [ ] **Step 1: Write failing test**

In `tests/test_combined_window.py`, add:

```python
def test_wp_status_label_in_statusbar(win):
    ta = win._ta_widget
    assert hasattr(ta, "_wp_status_label")
    assert ta._wp_status_label.text() == ""
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_combined_window.py::test_wp_status_label_in_statusbar -q
```

Expected: FAIL — `AttributeError: _wp_status_label`

- [ ] **Step 3: Add `_wp_post_url` instance variable**

In `translation_assistant/ui/main_widget.py`, near where `self._last_scheduled_date` is initialised (around line 183):

```python
        self._wp_post_url: str | None = None
```

- [ ] **Step 4: Add `_wp_status_label` in `_setup_statusbar()`**

After `self._status_bar.addPermanentWidget(self._filesaved_label)` (around line 510):

```python
        self._wp_status_label = _ClickableLabel("")
        self._wp_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wp_status_label.clicked.connect(self._on_wp_status_clicked)
        self._status_bar.addPermanentWidget(self._wp_status_label)
```

- [ ] **Step 5: Add `_update_wp_status_label()` and `_on_wp_status_clicked()`**

After `_setup_statusbar()`:

```python
    def _update_wp_status_label(self) -> None:
        if self._doc_id is None:
            self._wp_status_label.setText("")
            self._wp_post_url = None
            return
        info = self._db.get_document_wp_status(self._doc_id)
        status_map = {
            "publish":   "WP: Published",
            "future":    "WP: Scheduled",
            "draft":     "WP: Draft",
            "not_found": "WP: —",
        }
        self._wp_status_label.setText(status_map.get(info["wp_status"] or "", "WP: —"))
        self._wp_post_url = info["wp_post_url"]

    def _on_wp_status_clicked(self) -> None:
        if self._wp_post_url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self._wp_post_url))
```

- [ ] **Step 6: Call `_update_wp_status_label()` at the end of `_finish_load()`**

`_finish_load()` (around line 618) is called by both `create_document_from_content()` and `open_document()`. Add at the very end of `_finish_load()` (after `self._update_progress_visibility()`, around line 687):

```python
        self._update_wp_status_label()
```

- [ ] **Step 7: Record status in `_on_publish_done()`**

In `_on_publish_done(self, result: dict)` (around line 1435), after the line `already = result.get("created") is False` and `post_url = result.get("post_url", "")`:

```python
        if not already:
            wp_status_val = "future" if self._last_scheduled_date else "publish"
            self._db.set_document_wp_status(self._doc_id, wp_status_val, post_url or None)
            self._update_wp_status_label()
```

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_combined_window.py -q
```

Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_combined_window.py
git commit -m "feat: add WP status bar label and record status after publish"
```

---

### Task 6: Publish Dialog — Status Check, Safeguard & Schedule Pre-fill

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`

**Interfaces:**
- Consumes: `check_status()` (Task 2), `db.get_wp_status_by_series_position()` (Task 3), `settings.wp_default_schedule_time` (Task 4), `db.set_document_wp_status()` (Task 3), `_update_wp_status_label()` (Task 5)

- [ ] **Step 1: Add `_StatusCheckWorker` class**

In `translation_assistant/ui/main_widget.py`, directly after `_PublishWorker` (after line 96):

```python
class _StatusCheckWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        endpoint_url: str,
        api_key: str,
        series_slug: str,
        chapter: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._series_slug = series_slug
        self._chapter = chapter

    def run(self) -> None:
        from translation_assistant.wp_publisher import check_status, WPPublishError
        try:
            result = check_status(
                self._endpoint_url, self._api_key, self._series_slug, self._chapter
            )
            self.succeeded.emit(result)
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:
            self.error.emit(str(exc))
```

- [ ] **Step 2: Add safeguard check before confirm dialog in `_on_publish_wp()`**

In `_on_publish_wp()`, after `series_meta = self._db.get_series_wp_meta(series_title)` (around line 1352):

```python
        prev_scheduled = False
        if doc_meta["series_order"] > 0:
            prev_status = self._db.get_wp_status_by_series_position(
                doc_meta["series_title"], doc_meta["series_order"] - 1
            )
            prev_scheduled = (
                prev_status is not None and prev_status.get("wp_status") == "future"
            )
```

- [ ] **Step 3: Replace confirm dialog block**

Find the confirm dialog block in `_on_publish_wp()` (starts with `confirm_dlg = QDialog(self)`, ends before `self._last_scheduled_date = None`). Replace the entire block — from `from PySide6.QtWidgets import QCheckBox, QDateTimeEdit...` through `if not confirm_dlg.exec(): return` — with:

```python
        from PySide6.QtWidgets import QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QVBoxLayout
        from PySide6.QtCore import QDateTime, QTime, Qt as _Qt

        confirm_dlg = QDialog(self)
        confirm_dlg.setWindowTitle("Publish to WordPress")
        confirm_dlg.setWindowFlags(confirm_dlg.windowFlags() & ~_Qt.WindowType.WindowContextHelpButtonHint)
        _cl = QVBoxLayout(confirm_dlg)

        # Cached WP status line
        _cached = self._db.get_document_wp_status(self._doc_id)
        _status_text_map = {"publish": "Published", "future": "Scheduled", "draft": "Draft"}
        _cached_text = _status_text_map.get(_cached["wp_status"] or "", "Not published")
        _status_lbl = QLabel(f"WP status: {_cached_text}")
        _cl.addWidget(_status_lbl)

        _cl.addWidget(QLabel(f'Publish <b>{doc_meta["chapter_title"]}</b> ({chapter_label}) to WordPress?'))

        if prev_scheduled:
            _warn = QLabel(
                f"Warning: Chapter {doc_meta['series_order'] - 1} is still scheduled "
                "and hasn't gone live yet."
            )
            _warn.setWordWrap(True)
            _cl.addWidget(_warn)

        schedule_cb = QCheckBox("Schedule for later")
        _cl.addWidget(schedule_cb)

        # Pre-fill schedule time from settings
        _default_time = self._settings.wp_default_schedule_time
        if _default_time:
            _h, _m = map(int, _default_time.split(":"))
            _candidate = QDateTime.currentDateTime()
            _candidate.setTime(QTime(_h, _m))
            if _candidate <= QDateTime.currentDateTime():
                _candidate = _candidate.addDays(1)
            dte = QDateTimeEdit(_candidate)
        else:
            dte = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        dte.setCalendarPopup(True)
        dte.setDisplayFormat("yyyy-MM-dd HH:mm")
        dte.setEnabled(False)
        schedule_cb.toggled.connect(dte.setEnabled)
        _cl.addWidget(dte)

        if prev_scheduled:
            _btns = QDialogButtonBox()
            _btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
            _btns.addButton("Publish Anyway", QDialogButtonBox.ButtonRole.AcceptRole)
        else:
            _btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
        _btns.accepted.connect(confirm_dlg.accept)
        _btns.rejected.connect(confirm_dlg.reject)
        _cl.addWidget(_btns)

        # Async status refresh
        _status_worker = _StatusCheckWorker(
            endpoint_url, api_key,
            series_meta["series_slug"], doc_meta["series_order"],
            parent=confirm_dlg,
        )

        def _on_status_ok(result: dict) -> None:
            _map = {
                "publish":   "Published",
                "future":    "Scheduled",
                "draft":     "Draft",
                "not_found": "Not published",
            }
            _status_lbl.setText(f"WP status: {_map.get(result.get('status', ''), 'Unknown')}")
            self._db.set_document_wp_status(
                self._doc_id, result.get("status", ""), result.get("post_url")
            )
            self._update_wp_status_label()

        def _on_status_err(_: str) -> None:
            _status_lbl.setText(f"WP status: {_cached_text} (could not reach WP)")

        _status_worker.succeeded.connect(_on_status_ok)
        _status_worker.error.connect(_on_status_err)
        _status_worker.start()

        if not confirm_dlg.exec():
            _status_worker.quit()
            return
```

- [ ] **Step 4: Run existing tests**

```bash
pytest tests/test_combined_window.py tests/test_main_window.py -q
```

Expected: all pass

- [ ] **Step 5: Manual test**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Verify:
- Publish dialog shows "WP status: Not published" (or cached value) at top
- Async check updates the label (shows "could not reach WP" if no WP server)
- Schedule checkbox pre-fills date+time to default schedule time from settings (if set)
- With a doc where previous chapter has `wp_status = "future"` in DB, the warning banner and "Publish Anyway" button appear

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat: add status check, safeguard, and schedule pre-fill to publish dialog"
```

---

### Task 7: Doc List WP Status Column

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`
- Test: `tests/test_dlg_open.py`

**Interfaces:**
- Consumes: `db.list_documents()` now includes `"wp_status"` key (Task 3)

- [ ] **Step 1: Write failing tests**

In `tests/test_dlg_open.py`, add. `Qt`, `mem_db`, `Database`, `OpenDocumentDialog` are already imported at the top of the file.

```python
def test_open_dialog_has_five_columns(qapp, mem_db):
    dlg = OpenDocumentDialog(mem_db)
    assert dlg._tree.columnCount() == 5
    dlg.reject()


def test_open_dialog_wp_column_shows_pub_badge(qapp, mem_db):
    doc_id = mem_db.create_document("Ch 1", series_title="S", series_order=1, chapter_title="Ch 1")
    mem_db.set_document_wp_status(doc_id, "publish", "https://ex.com/ch1/")
    dlg = OpenDocumentDialog(mem_db)
    # Select series S
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).data(Qt.ItemDataRole.UserRole) == "S":
            dlg._series_list.setCurrentRow(i)
            break
    assert dlg._tree.topLevelItemCount() == 1
    assert dlg._tree.topLevelItem(0).text(4) == "pub"
    dlg.reject()


def test_open_dialog_wp_column_shows_sched_badge(qapp, mem_db):
    doc_id = mem_db.create_document("Ch 1", series_title="S", series_order=1, chapter_title="Ch 1")
    mem_db.set_document_wp_status(doc_id, "future", None)
    dlg = OpenDocumentDialog(mem_db)
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).data(Qt.ItemDataRole.UserRole) == "S":
            dlg._series_list.setCurrentRow(i)
            break
    assert dlg._tree.topLevelItem(0).text(4) == "sched"
    dlg.reject()


def test_open_dialog_wp_column_blank_when_null(qapp, mem_db):
    mem_db.create_document("Ch 1", series_title="S", series_order=1, chapter_title="Ch 1")
    dlg = OpenDocumentDialog(mem_db)
    for i in range(dlg._series_list.count()):
        if dlg._series_list.item(i).data(Qt.ItemDataRole.UserRole) == "S":
            dlg._series_list.setCurrentRow(i)
            break
    assert dlg._tree.topLevelItem(0).text(4) == ""
    dlg.reject()
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_dlg_open.py::test_open_dialog_has_five_columns -q
```

Expected: FAIL — columnCount is 4

- [ ] **Step 3: Update `_CHAPTER_HEADERS` and column count**

In `translation_assistant/ui/dlg_open.py`:

Change:
```python
_CHAPTER_HEADERS = ["#", "Title", "Progress", "Last Edited"]
```
To:
```python
_CHAPTER_HEADERS = ["#", "Title", "Progress", "Last Edited", "WP"]
```

Change `self._tree.setColumnCount(4)` → `self._tree.setColumnCount(5)`

After the existing four `setSectionResizeMode` calls, add:
```python
        self._tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
```

- [ ] **Step 4: Populate WP column in `_load_chapters()`**

In `_load_chapters()`, change the `QTreeWidgetItem` constructor call:

From:
```python
            item = QTreeWidgetItem([
                str(doc["series_order"]),
                display,
                f"{progress_pct}%",
                _fmt_date(doc.get("updated_at", "")),
            ])
```
To:
```python
            _wp_badge = {"publish": "pub", "future": "sched"}.get(doc.get("wp_status") or "", "")
            item = QTreeWidgetItem([
                str(doc["series_order"]),
                display,
                f"{progress_pct}%",
                _fmt_date(doc.get("updated_at", "")),
                _wp_badge,
            ])
```

- [ ] **Step 5: Run all dlg_open tests**

```bash
pytest tests/test_dlg_open.py -q
```

Expected: all pass

- [ ] **Step 6: Manual test**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Open a doc, publish it, then open the doc picker — verify "pub" or "sched" badge appears in the WP column.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat: add WP status column to doc list"
```

---

## Full Test Run

After all tasks complete:

```bash
source .venv/bin/activate && pytest -q
```

Expected: all 535+ tests pass (no regressions).

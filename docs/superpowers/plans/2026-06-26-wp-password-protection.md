# WordPress Password Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-chapter auto-generated password protection to the WordPress publish flow, with per-series and global settings, keeping exactly N chapters locked at any time.

**Architecture:** Pure logic lives in `wp_publisher.py` (password computation + payload). Settings layer (`settings.py`, `db.py`) stores global defaults and per-series overrides. UI changes extend the existing WP Settings dialog and the "Set WP Fields" mini-dialog in the Series Manager. `main_widget.py` resolves effective settings and wires everything together.

**Tech Stack:** PySide6, Python `secrets` (stdlib), SQLite via `db.py`, `QSettings` via `settings.py`

## Global Constraints

- Python stdlib only — no new dependencies
- All DB migrations idempotent (`PRAGMA table_info` check before `ALTER TABLE`)
- No Qt imports in `wp_publisher.py` or `core.py`
- `_PublishWorker` must not be modified to carry new data — use instance vars on widget instead
- Run tests with: `source .venv/bin/activate && pytest`
- Single-test run: `pytest tests/test_X.py::test_name -q`

---

## File Map

| File | Change |
|---|---|
| `translation_assistant/wp_publisher.py` | Add `compute_password_fields()`, update `build_payload()` signature |
| `translation_assistant/settings.py` | Add `wp_password_enabled` and `wp_unlock_after` properties |
| `translation_assistant/db.py` | Add migration + `get/set_series_wp_password_settings()` |
| `translation_assistant/ui/dlg_wp_settings.py` | Add global password defaults section |
| `translation_assistant/ui/dlg_series.py` | Extend "Set WP Fields" mini-dialog |
| `translation_assistant/ui/main_widget.py` | Wire settings resolution, password generation, success dialog |
| `tests/test_wp_publisher.py` | Add `compute_password_fields` tests |
| `tests/test_settings.py` | Add 2 new property tests |
| `tests/test_db.py` | Add `get/set_series_wp_password_settings` tests |

---

### Task 1: `compute_password_fields` + `build_payload` update

**Files:**
- Modify: `translation_assistant/wp_publisher.py`
- Test: `tests/test_wp_publisher.py`

**Interfaces:**
- Produces:
  ```python
  def compute_password_fields(chapter_index: int, unlock_after: int) -> tuple[str | None, int | None]:
      ...

  def build_payload(
      doc_meta: dict, series_meta: dict, lines: list[dict], api_key: str,
      password: str | None = None,
      unlock_chapter_index: int | None = None,
  ) -> dict:
      ...
  ```

- [ ] **Step 1: Write failing tests**

Open `tests/test_wp_publisher.py`. Add at the bottom:

```python
import secrets as _secrets

from translation_assistant.wp_publisher import compute_password_fields, build_payload


@pytest.mark.parametrize("chapter_index,unlock_after,expect_pw,expect_unlock", [
    (0,  3, False, None),   # synopsis — always free
    (1,  3, False, None),   # within free window
    (3,  3, False, None),   # boundary — still free
    (4,  3, True,  None),   # first locked chapter, no unlock yet
    (6,  3, True,  None),   # 6-3=3, 3>3 is False — no unlock
    (7,  3, True,  4),      # 7-3=4, 4>3 — unlock ch4
    (11, 5, True,  6),      # 11-5=6, 6>5 — unlock ch6
])
def test_compute_password_fields(chapter_index, unlock_after, expect_pw, expect_unlock):
    pw, unlock_idx = compute_password_fields(chapter_index, unlock_after)
    assert (pw is not None) == expect_pw
    assert unlock_idx == expect_unlock
    if expect_pw:
        assert len(pw) > 0


def test_compute_password_fields_password_is_random():
    pw1, _ = compute_password_fields(5, 3)
    pw2, _ = compute_password_fields(5, 3)
    assert pw1 != pw2


def test_build_payload_includes_password_and_unlock():
    doc_meta = {"series_title": "T", "series_order": 7, "chapter_title": "Ch7"}
    series_meta = {"series_slug": "t", "series_title_short": "T", "syosetu_url": ""}
    lines = [{"prefix": "%", "translated_text": "Hello"}]
    payload = build_payload(doc_meta, series_meta, lines, "key",
                            password="abc123", unlock_chapter_index=4)
    assert payload["password"] == "abc123"
    assert payload["unlock_chapter_index"] == 4


def test_build_payload_omits_password_fields_when_none():
    doc_meta = {"series_title": "T", "series_order": 1, "chapter_title": "Ch1"}
    series_meta = {"series_slug": "t", "series_title_short": "T", "syosetu_url": ""}
    lines = [{"prefix": "%", "translated_text": "Hello"}]
    payload = build_payload(doc_meta, series_meta, lines, "key")
    assert "password" not in payload
    assert "unlock_chapter_index" not in payload
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_wp_publisher.py::test_compute_password_fields tests/test_wp_publisher.py::test_build_payload_includes_password_and_unlock -q
```

Expected: `ImportError` or `TypeError` — `compute_password_fields` doesn't exist yet.

- [ ] **Step 3: Implement `compute_password_fields` and update `build_payload`**

Open `translation_assistant/wp_publisher.py`. Add `import secrets` at the top (after existing imports). Then add this function before `build_payload`:

```python
import secrets


def compute_password_fields(
    chapter_index: int, unlock_after: int
) -> tuple[str | None, int | None]:
    if chapter_index == 0 or chapter_index <= unlock_after:
        return None, None
    password = secrets.token_urlsafe(8)
    unlock_idx = chapter_index - unlock_after
    return password, (unlock_idx if unlock_idx > unlock_after else None)
```

Update `build_payload` signature and body:

```python
def build_payload(
    doc_meta: dict,
    series_meta: dict,
    lines: list[dict],
    api_key: str,
    password: str | None = None,
    unlock_chapter_index: int | None = None,
) -> dict:
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
        "chapter_title":      f"{series_meta['series_title_short']} {doc_meta['chapter_title']}",
        "chapter_body":       build_chapter_body(lines),
    }
    if doc_meta["series_order"] != 0:
        payload["first_line"] = get_first_line(lines)
    if password is not None:
        payload["password"] = password
    if unlock_chapter_index is not None:
        payload["unlock_chapter_index"] = unlock_chapter_index
    return payload
```

- [ ] **Step 4: Run all new tests**

```bash
source .venv/bin/activate && pytest tests/test_wp_publisher.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): add compute_password_fields and extend build_payload"
```

---

### Task 2: AppSettings — global password defaults

**Files:**
- Modify: `translation_assistant/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: existing `AppSettings._qs` QSettings pattern
- Produces:
  ```python
  settings.wp_password_enabled: bool   # default False
  settings.wp_unlock_after: int        # default 3
  ```

- [ ] **Step 1: Write failing tests**

Open `tests/test_settings.py`. Find where existing WP tests live (search for `wp_endpoint_url`) and add below:

```python
def test_wp_password_enabled_default(tmp_settings):
    assert tmp_settings.wp_password_enabled is False


def test_wp_password_enabled_roundtrip(tmp_settings):
    tmp_settings.wp_password_enabled = True
    assert tmp_settings.wp_password_enabled is True
    tmp_settings.wp_password_enabled = False
    assert tmp_settings.wp_password_enabled is False


def test_wp_unlock_after_default(tmp_settings):
    assert tmp_settings.wp_unlock_after == 3


def test_wp_unlock_after_roundtrip(tmp_settings):
    tmp_settings.wp_unlock_after = 7
    assert tmp_settings.wp_unlock_after == 7
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_settings.py::test_wp_password_enabled_default tests/test_settings.py::test_wp_unlock_after_default -q
```

Expected: `AttributeError`.

- [ ] **Step 3: Add properties to AppSettings**

Open `translation_assistant/settings.py`. After the `wp_api_key` setter (around line 174), add:

```python
    # --- WordPress password protection defaults ---

    @property
    def wp_password_enabled(self) -> bool:
        return self._qs.value("WPPasswordEnabled", False, type=bool)

    @wp_password_enabled.setter
    def wp_password_enabled(self, value: bool) -> None:
        self._qs.setValue("WPPasswordEnabled", value)

    @property
    def wp_unlock_after(self) -> int:
        return self._qs.value("WPUnlockAfter", 3, type=int)

    @wp_unlock_after.setter
    def wp_unlock_after(self, value: int) -> None:
        self._qs.setValue("WPUnlockAfter", value)
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_settings.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add wp_password_enabled and wp_unlock_after"
```

---

### Task 3: DB — migration + password settings CRUD

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  ```python
  db.get_series_wp_password_settings(series_title: str) -> dict:
      # {"wp_password_enabled": "1"|"0"|None, "wp_unlock_after": int}

  db.set_series_wp_password_settings(
      series_title: str,
      enabled: str | None,   # "1", "0", or None
      unlock_after: int,     # positive or -1
  ) -> None:
  ```

- [ ] **Step 1: Write failing tests**

Open `tests/test_db.py`. Find an existing in-memory DB fixture (look for `Database(":memory:")` pattern) and add:

```python
def test_get_series_wp_password_settings_defaults(db):
    result = db.get_series_wp_password_settings("Unknown Series")
    assert result == {"wp_password_enabled": None, "wp_unlock_after": -1}


def test_set_series_wp_password_settings_enabled(db):
    db.set_series_wp_password_settings("My Series", "1", 5)
    result = db.get_series_wp_password_settings("My Series")
    assert result["wp_password_enabled"] == "1"
    assert result["wp_unlock_after"] == 5


def test_set_series_wp_password_settings_disabled(db):
    db.set_series_wp_password_settings("My Series", "0", -1)
    result = db.get_series_wp_password_settings("My Series")
    assert result["wp_password_enabled"] == "0"
    assert result["wp_unlock_after"] == -1


def test_set_series_wp_password_settings_inherit(db):
    # First set something, then clear to inherit
    db.set_series_wp_password_settings("My Series", "1", 5)
    db.set_series_wp_password_settings("My Series", None, -1)
    result = db.get_series_wp_password_settings("My Series")
    assert result["wp_password_enabled"] is None
    assert result["wp_unlock_after"] == -1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_db.py::test_get_series_wp_password_settings_defaults -q
```

Expected: `AttributeError` — method doesn't exist.

- [ ] **Step 3: Add migration to `_apply_schema`**

Open `translation_assistant/db.py`. Find the `sp_existing` block (around line 109). After the existing `series_slug`/`series_title_short` migration block (after the second `self._conn.commit()`), add:

```python
        for col, defn in [
            ("wp_password_enabled", "TEXT DEFAULT NULL"),
            ("wp_unlock_after",     "INTEGER NOT NULL DEFAULT -1"),
        ]:
            if col not in sp_existing:
                self._conn.execute(
                    f"ALTER TABLE series_profiles ADD COLUMN {col} {defn}"
                )
        self._conn.commit()
```

- [ ] **Step 4: Add `get_series_wp_password_settings` and `set_series_wp_password_settings`**

In `translation_assistant/db.py`, after `set_series_wp_meta` (around line 354), add:

```python
    def get_series_wp_password_settings(self, series_title: str) -> dict:
        row = self._conn.execute(
            "SELECT wp_password_enabled, wp_unlock_after "
            "FROM series_profiles WHERE series_title = ?",
            (series_title,),
        ).fetchone()
        if row is None:
            return {"wp_password_enabled": None, "wp_unlock_after": -1}
        return {
            "wp_password_enabled": row["wp_password_enabled"],
            "wp_unlock_after": row["wp_unlock_after"] if row["wp_unlock_after"] is not None else -1,
        }

    def set_series_wp_password_settings(
        self,
        series_title: str,
        enabled: str | None,
        unlock_after: int,
    ) -> None:
        self._conn.execute(
            "INSERT INTO series_profiles (series_title, wp_password_enabled, wp_unlock_after) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(series_title) DO UPDATE SET "
            "wp_password_enabled = excluded.wp_password_enabled, "
            "wp_unlock_after = excluded.wp_unlock_after",
            (series_title, enabled, unlock_after),
        )
        self._conn.commit()
```

- [ ] **Step 5: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_db.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add wp_password_enabled/wp_unlock_after to series_profiles"
```

---

### Task 4: `dlg_wp_settings.py` — global password defaults UI

**Files:**
- Modify: `translation_assistant/ui/dlg_wp_settings.py`

**Interfaces:**
- Consumes: `AppSettings.wp_password_enabled: bool`, `AppSettings.wp_unlock_after: int` (Task 2)
- No new public interface — saves to settings on Save

- [ ] **Step 1: Add password section to `_setup_ui`**

Open `translation_assistant/ui/dlg_wp_settings.py`. In `_setup_ui`, after `form.addRow("API Key:", self._key_edit)` and before `layout.addLayout(form)`, add:

```python
        from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSpinBox

        self._pw_check = QCheckBox("Enable password protection by default")
        self._pw_check.setChecked(self._settings.wp_password_enabled)
        form.addRow("", self._pw_check)

        self._unlock_spin = QSpinBox()
        self._unlock_spin.setRange(1, 99)
        self._unlock_spin.setValue(self._settings.wp_unlock_after)
        self._unlock_spin.setEnabled(self._settings.wp_password_enabled)
        self._pw_check.toggled.connect(self._unlock_spin.setEnabled)
        form.addRow("Keep N chapters locked:", self._unlock_spin)
```

- [ ] **Step 2: Save values in `_on_save`**

In `_on_save`, after the existing two `self._settings` assignments, add:

```python
        self._settings.wp_password_enabled = self._pw_check.isChecked()
        self._settings.wp_unlock_after = self._unlock_spin.value()
```

- [ ] **Step 3: Run existing dialog tests**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -q
```

Expected: all pass (no regressions).

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/dlg_wp_settings.py
git commit -m "feat(dlg_wp_settings): add global password protection defaults"
```

---

### Task 5: `dlg_series.py` — per-series password override UI

**Files:**
- Modify: `translation_assistant/ui/dlg_series.py`

**Interfaces:**
- Consumes: `db.get_series_wp_password_settings()`, `db.set_series_wp_password_settings()` (Task 3)
- No new public interface

- [ ] **Step 1: Extend the "Set WP Fields" mini-dialog**

Open `translation_assistant/ui/dlg_series.py`. Find `_on_set_wp_fields` (line 113). The method builds a `QDialog` inline. Extend it as follows.

After `from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout`, add `QComboBox, QSpinBox` to the import:

```python
        from PySide6.QtWidgets import (
            QComboBox, QDialog, QDialogButtonBox, QFormLayout,
            QLineEdit, QSpinBox, QVBoxLayout,
        )
```

After `form.addRow("Short Title:", short_edit)`, add:

```python
        pw_meta = self._db.get_series_wp_password_settings(s["title"])
        pw_enabled_val = pw_meta["wp_password_enabled"]  # "1", "0", or None
        unlock_after_val = pw_meta["wp_unlock_after"]    # int or -1

        pw_combo = QComboBox()
        pw_combo.addItems(["Use global", "Always on", "Always off"])
        if pw_enabled_val == "1":
            pw_combo.setCurrentIndex(1)
        elif pw_enabled_val == "0":
            pw_combo.setCurrentIndex(2)
        else:
            pw_combo.setCurrentIndex(0)
        form.addRow("Password protection:", pw_combo)

        unlock_spin = QSpinBox()
        unlock_spin.setRange(1, 99)
        unlock_spin.setValue(unlock_after_val if unlock_after_val > 0 else 3)
        unlock_spin.setEnabled(pw_combo.currentIndex() == 1)
        pw_combo.currentIndexChanged.connect(
            lambda idx: unlock_spin.setEnabled(idx == 1)
        )
        form.addRow("Keep locked:", unlock_spin)
```

Replace the `if dlg.exec():` block (currently only saves slug + short title) with:

```python
        if dlg.exec():
            self._db.set_series_wp_meta(s["title"], slug_edit.text().strip(), short_edit.text().strip())
            idx = pw_combo.currentIndex()
            enabled_out = ("1" if idx == 1 else "0" if idx == 2 else None)
            unlock_out = unlock_spin.value() if idx == 1 else -1
            self._db.set_series_wp_password_settings(s["title"], enabled_out, unlock_out)
```

- [ ] **Step 2: Run tests**

```bash
source .venv/bin/activate && pytest tests/test_dialogs.py -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add translation_assistant/ui/dlg_series.py
git commit -m "feat(dlg_series): add per-series password override to WP fields dialog"
```

---

### Task 6: `main_widget.py` — wire publish logic + success dialog

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`

**Interfaces:**
- Consumes: all Tasks 1–5

- [ ] **Step 1: Add instance vars for last publish password info**

In `TranslationAssistantWidget.__init__` (or just before `_on_publish_wp` is called — find it by searching `self._publish_worker`), add two instance vars. The cleanest place is near other `self._publish_worker` initialization. Find where `self._publish_worker` is first assigned (it's assigned inline in `_on_publish_wp`, but add the vars to `__init__`). Search for `def __init__` in the class, and somewhere in the body add:

```python
        self._last_pw: str | None = None
        self._last_unlock_idx: int | None = None
```

- [ ] **Step 2: Resolve password settings and compute fields in `_on_publish_wp`**

Open `_on_publish_wp` (line 1325). After the line:

```python
        series_meta = self._db.get_series_wp_meta(series_title)
```

Add (before the `if not series_meta[...]` check):

```python
        from translation_assistant.wp_publisher import compute_password_fields
        pw_settings = self._db.get_series_wp_password_settings(series_title)
        pw_enabled_raw = pw_settings["wp_password_enabled"]
        pw_enabled = (
            pw_enabled_raw == "1"
            if pw_enabled_raw is not None
            else self._settings.wp_password_enabled
        )
        unlock_after = (
            pw_settings["wp_unlock_after"]
            if pw_settings["wp_unlock_after"] != -1
            else self._settings.wp_unlock_after
        )
        self._last_pw = None
        self._last_unlock_idx = None
        if pw_enabled:
            self._last_pw, self._last_unlock_idx = compute_password_fields(
                doc_meta["series_order"], unlock_after
            )
```

- [ ] **Step 3: Pass password fields to `build_payload`**

Find the existing `build_payload` call:

```python
            payload = build_payload(doc_meta, series_meta, lines, api_key=api_key)
```

Replace with:

```python
            payload = build_payload(
                doc_meta, series_meta, lines, api_key=api_key,
                password=self._last_pw,
                unlock_chapter_index=self._last_unlock_idx,
            )
```

- [ ] **Step 4: Replace success dialog in `_on_publish_done`**

Find `_on_publish_done` (line 1383). Replace the entire method body with:

```python
    def _on_publish_done(self, result: dict) -> None:
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
        )
        from PySide6.QtCore import Qt

        already = result.get("created") is False
        page_url = result.get("page_url", "")
        post_url = result.get("post_url", "")

        dlg = QDialog(self)
        dlg.setWindowTitle("WordPress Publish")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)

        status_label = QLabel("Already published." if already else "Published!")
        layout.addWidget(status_label)

        form = QFormLayout()
        if page_url:
            form.addRow("Page:", QLabel(f'<a href="{page_url}">{page_url}</a>'))
        if post_url and not already:
            form.addRow("Post:", QLabel(f'<a href="{post_url}">{post_url}</a>'))
        layout.addLayout(form)

        if not already and self._last_pw:
            pw_edit = QLineEdit(self._last_pw)
            pw_edit.setReadOnly(True)
            pw_edit.selectAll()
            layout.addWidget(QLabel("Password (copy this):"))
            layout.addWidget(pw_edit)

        if self._last_unlock_idx is not None:
            layout.addWidget(QLabel(f"Chapter {self._last_unlock_idx} is now unlocked."))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)

        dlg.exec()
        self.action_publish_wp.setEnabled(True)
```

- [ ] **Step 5: Fix `_on_publish_error` — it still needs to re-enable the action**

The existing `_on_publish_error` already calls `self.action_publish_wp.setEnabled(True)`. Verify it's still there (it was moved out of `_on_publish_done`). No change needed if it exists.

- [ ] **Step 6: Run full test suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: all 535+ tests pass (plus new ones from Tasks 1–3).

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat(main_widget): wire WP password protection into publish flow"
```

# Translation Memory + Navigation Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a translation memory suggestion panel, go-to-line shortcut, automatic document resume on startup, and pre-selection of the current document in the Open dialog.

**Architecture:** Four independent changes layered on existing modules: a new `find_tm_matches` DB method feeds a new `_tm_panel` widget in `main_widget.py`; two new `AppSettings` properties (`tm_visible`, `last_doc_id`) back the TM toggle and resume; `dlg_open.py` gains an optional `current_doc_id` param; a `_on_go_to_line` handler + `action_go_to_line` wired into the View menu covers Ctrl+G.

**Tech Stack:** PySide6 (QWidget, QPushButton, QInputDialog, QAction), SQLite via existing `Database` class, pytest + in-memory DB fixture for tests.

---

## File Map

| File | What changes |
|------|-------------|
| `translation_assistant/db.py` | Add `find_tm_matches()` method |
| `translation_assistant/settings.py` | Add `tm_visible` and `last_doc_id` properties |
| `translation_assistant/ui/main_widget.py` | Add `_tm_panel`, `_update_tm_panel()`, `_on_toggle_tm()`, `action_tm`, `action_go_to_line`, `_on_go_to_line()`; update `_load_initial_state()` and `save_state()`; pass `_doc_id` to `OpenDocumentDialog` |
| `translation_assistant/ui/combined_window.py` | Wire `action_go_to_line` into View menu; wire `action_tm` into Settings menu |
| `translation_assistant/ui/dlg_open.py` | Add `current_doc_id` param; add `_select_doc()` helper |
| `tests/test_db.py` | Tests for `find_tm_matches` |
| `tests/test_settings.py` | Tests for `tm_visible` and `last_doc_id` |
| `tests/test_dlg_open.py` | Test pre-selection of `current_doc_id` |

---

## Task 1: `find_tm_matches` in db.py

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

### Background

`lines.raw_text` stores the sentence text **without** its `%`/`$` prefix (the prefix lives in `lines.prefix`). The query joins `lines` with `documents` to get the doc title and `updated_at` for display. Empty translations are excluded. When `current_doc_id` is `None` (no doc open), all documents are searched.

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_db.py`:

```python
# ---------------------------------------------------------------------------
# Translation Memory
# ---------------------------------------------------------------------------

def _make_doc_with_line(db: Database, title: str, raw: str, translation: str) -> int:
    doc_id = db.create_document(title)
    db.save_lines(doc_id, [{"line_number": 0, "prefix": "%", "raw_text": raw, "translated_text": translation}])
    return doc_id


def test_find_tm_matches_exact(db):
    _make_doc_with_line(db, "Doc A", "猫が鳴いた", "The cat meowed")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert len(matches) == 1
    assert matches[0]["translated_text"] == "The cat meowed"
    assert matches[0]["doc_title"] == "Doc A"


def test_find_tm_matches_excludes_current_doc(db):
    doc_id = _make_doc_with_line(db, "Current", "猫が鳴いた", "The cat meowed")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=doc_id)
    assert matches == []


def test_find_tm_matches_excludes_empty_translation(db):
    _make_doc_with_line(db, "Doc A", "猫が鳴いた", "")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert matches == []


def test_find_tm_matches_no_match(db):
    _make_doc_with_line(db, "Doc A", "犬が吠えた", "The dog barked")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert matches == []


def test_find_tm_matches_limit(db):
    for i in range(7):
        _make_doc_with_line(db, f"Doc {i}", "猫が鳴いた", f"Translation {i}")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None, limit=5)
    assert len(matches) == 5


def test_find_tm_matches_returns_doc_title_and_updated_at(db):
    _make_doc_with_line(db, "My Novel Ch1", "猫が鳴いた", "The cat meowed")
    matches = db.find_tm_matches("猫が鳴いた", current_doc_id=None)
    assert "doc_title" in matches[0]
    assert "updated_at" in matches[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_db.py -k "tm_matches" -v
```

Expected: 6 errors — `AttributeError: 'Database' object has no attribute 'find_tm_matches'`

- [ ] **Step 3: Implement `find_tm_matches` in `db.py`**

Add after `save_translation` (line ~396), before the `# ── Migration helper` comment:

```python
def find_tm_matches(
    self, raw_text: str, current_doc_id: int | None, limit: int = 5
) -> list[dict]:
    rows = self._conn.execute(
        "SELECT l.translated_text, d.title AS doc_title, d.updated_at "
        "FROM lines l "
        "JOIN documents d ON d.id = l.document_id "
        "WHERE l.raw_text = ? AND l.translated_text != '' "
        "AND (? IS NULL OR l.document_id != ?) "
        "ORDER BY d.updated_at DESC "
        "LIMIT ?",
        (raw_text, current_doc_id, current_doc_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -k "tm_matches" -v
```

Expected: 6 passed

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest -q
```

Expected: all pass (same count as before + 6 new)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add find_tm_matches for translation memory"
```

---

## Task 2: `tm_visible` and `last_doc_id` in settings.py

**Files:**
- Modify: `translation_assistant/settings.py`
- Test: `tests/test_settings.py`

### Background

`AppSettings` wraps `QSettings`. Follow the existing pattern: a `@property` getter with a typed default, and a `@setter`. `last_doc_id` can be `None` (no doc saved yet); remove the key on `None` to avoid storing a string `"None"`.

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_settings.py`:

```python
# ---------------------------------------------------------------------------
# tm_visible
# ---------------------------------------------------------------------------

def test_default_tm_visible(tmp_settings):
    assert tmp_settings.tm_visible is True


def test_tm_visible_roundtrip(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.tm_visible = False
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.tm_visible is False


# ---------------------------------------------------------------------------
# last_doc_id
# ---------------------------------------------------------------------------

def test_default_last_doc_id(tmp_settings):
    assert tmp_settings.last_doc_id is None


def test_last_doc_id_roundtrip(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.last_doc_id = 42
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.last_doc_id == 42


def test_last_doc_id_none_clears(qapp, tmp_path):
    ini = str(tmp_path / "settings.ini")
    s1 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    s1.last_doc_id = 7
    s1.last_doc_id = None
    s1.save()
    s2 = AppSettings(_qs=QSettings(ini, QSettings.Format.IniFormat))
    assert s2.last_doc_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_settings.py -k "tm_visible or last_doc_id" -v
```

Expected: 5 errors — `AttributeError: 'AppSettings' object has no attribute 'tm_visible'` / `'last_doc_id'`

- [ ] **Step 3: Add the two properties to `settings.py`**

Add after the `splitter_state` setter (after line 126), before `def save`:

```python
    # --- translation memory visible ---

    @property
    def tm_visible(self) -> bool:
        return self._qs.value("TMVisible", True, type=bool)

    @tm_visible.setter
    def tm_visible(self, value: bool) -> None:
        self._qs.setValue("TMVisible", value)

    # --- last opened document id ---

    @property
    def last_doc_id(self) -> int | None:
        val = self._qs.value("LastDocId", None)
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    @last_doc_id.setter
    def last_doc_id(self, value: int | None) -> None:
        if value is None:
            self._qs.remove("LastDocId")
        else:
            self._qs.setValue("LastDocId", value)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_settings.py -k "tm_visible or last_doc_id" -v
```

Expected: 5 passed

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add tm_visible and last_doc_id properties"
```

---

## Task 3: Translation Memory panel in main_widget.py

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`

### Background

The vertical splitter in `TranslationAssistantWidget` currently has 4 panes (indices 0–3): `_review_top`, `_raw_line`, `_translated_line`, `_review_bottom`. We insert `_tm_panel` at index 2, pushing `_translated_line` to index 3 and `_review_bottom` to index 4. The panel is a plain `QWidget` with a `QVBoxLayout`; each TM match is a flat `QPushButton`. The panel is hidden entirely when there are no matches or TM is disabled.

`raw_text` in the DB does **not** include the `%`/`$` prefix. In memory, `_raw_lines[p]` is stored as `prefix + raw_text` (e.g. `"%この物語は…"`). Strip the first character before querying.

- [ ] **Step 1: Add `_tm_panel` to `_setup_central_widget`**

In `main_widget.py`, locate `_setup_central_widget` (line ~215). The method builds the splitter. Add the TM panel widget between `_raw_line` and `_translated_line`. Replace the block that adds `_raw_line` and then `_translated_line` with:

```python
        self._raw_line = QTextEdit()
        self._raw_line.setReadOnly(True)
        self._raw_line.setFont(font)
        self._raw_line.setMinimumHeight(40)
        self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._splitter.addWidget(self._raw_line)

        self._tm_panel = QWidget()
        self._tm_panel.setMinimumHeight(0)
        self._tm_layout = QVBoxLayout(self._tm_panel)
        self._tm_layout.setContentsMargins(2, 2, 2, 2)
        self._tm_layout.setSpacing(2)
        self._tm_panel.setVisible(False)
        self._splitter.addWidget(self._tm_panel)

        self._translated_line = QTextEdit()
        self._translated_line.setFont(font)
        self._translated_line.setMinimumHeight(40)
        self._translated_line.setAcceptRichText(False)
        self._translated_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._translated_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._translated_line.customContextMenuRequested.connect(self._on_translated_context_menu)
        self._splitter.addWidget(self._translated_line)
        self._spell_highlighter = SpellHighlighter(self._translated_line.document())
```

Update the stretch factors (now 5 panes) and default sizes:

```python
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setStretchFactor(3, 0)
        self._splitter.setStretchFactor(4, 0)

        saved = self._settings.splitter_state
        if not saved.isEmpty():
            self._splitter.restoreState(saved)
        else:
            self._splitter.setSizes([300, 52, 0, 52, 137])
```

The event filter loop at the bottom of `_setup_central_widget` does not change — `_tm_panel` is not a text-input panel and does not need keyboard-navigation interception:

```python
        for widget in (self._review_top, self._raw_line,
                       self._translated_line, self._review_bottom):
            widget.installEventFilter(self)
```

- [ ] **Step 2: Add `_update_tm_panel()` method**

Add this method after `_update_ui_for_pointer` (after line ~513):

```python
    def _update_tm_panel(self) -> None:
        while self._tm_layout.count():
            item = self._tm_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._raw_lines or not self._settings.tm_visible:
            self._tm_panel.setVisible(False)
            return

        p = self._array_pointer
        raw = self._raw_lines[p]
        raw_text = raw[1:] if raw and raw[0] in ('%', '$') else raw
        matches = self._db.find_tm_matches(raw_text, self._doc_id)

        if not matches:
            self._tm_panel.setVisible(False)
            return

        self._tm_panel.setVisible(True)
        for m in matches:
            date_str = m["updated_at"][:10] if m.get("updated_at") else ""
            label = f"{m['translated_text']}  —  {m['doc_title']}, {date_str}"
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setStyleSheet("text-align: left; padding: 2px 4px;")
            translation = m["translated_text"]
            btn.clicked.connect(
                lambda checked, t=translation: self._translated_line.setPlainText(t)
            )
            self._tm_layout.addWidget(btn)
```

- [ ] **Step 3: Call `_update_tm_panel()` in `_update_ui_for_pointer`**

At the end of `_update_ui_for_pointer` (after line ~512, after `self.source_sentence_changed.emit(...)`), add:

```python
        self._update_tm_panel()
```

- [ ] **Step 4: Add `action_tm` and `_on_toggle_tm()` in `_build_actions`**

In `_build_actions` (line ~124), add after `action_progress`:

```python
        self.action_tm = QAction("Show Translation Memory", self)
        self.action_tm.setCheckable(True)
        self.action_tm.setChecked(self._settings.tm_visible)
        self.action_tm.triggered.connect(self._on_toggle_tm)
```

Add the handler near `_on_toggle_progress`:

```python
    def _on_toggle_tm(self) -> None:
        self._settings.tm_visible = self.action_tm.isChecked()
        self._settings.save()
        self._update_tm_panel()
```

- [ ] **Step 5: Wire `action_tm` into combined_window.py Settings menu**

In `combined_window.py`, locate the Settings menu block (line ~85). Add after `settings_menu.addAction(ta.action_progress)`:

```python
        settings_menu.addAction(ta.action_tm)
```

- [ ] **Step 6: Add QPushButton to imports in main_widget.py**

Check the imports at the top of `main_widget.py`. `QPushButton` is not currently imported. Add it to the `QWidgets` import line:

```python
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)
```

- [ ] **Step 7: Run the app to verify TM panel renders**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

- Open a document, navigate between lines. When a line has a past translation in another document, buttons appear. When no match, panel is hidden. Settings menu shows "Show Translation Memory" toggle.

- [ ] **Step 8: Run full test suite**

```bash
pytest -q
```

Expected: all pass (no regressions from splitter index change)

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py
git commit -m "feat(ui): add translation memory suggestion panel"
```

---

## Task 4: Go-to-Line (Ctrl+G)

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`

### Background

`QInputDialog.getInt` provides an integer input dialog with range validation — no custom dialog file needed. The internal jump pattern mirrors `_jump_to_first`: stop clipboard timer, save current translation, update pointer, update UI.

- [ ] **Step 1: Add `action_go_to_line` in `_build_actions`**

In `_build_actions`, add after `action_tm`:

```python
        self.action_go_to_line = QAction("Go to Line… (Ctrl+G)", self)
        self.action_go_to_line.setShortcut("Ctrl+G")
        self.action_go_to_line.triggered.connect(self._on_go_to_line)
        self.action_go_to_line.setEnabled(False)
```

- [ ] **Step 2: Add `_on_go_to_line()` handler**

Add after `_on_toggle_tm`:

```python
    def _on_go_to_line(self) -> None:
        if not self._raw_lines:
            return
        n = len(self._raw_lines)
        from PySide6.QtWidgets import QInputDialog
        line_num, ok = QInputDialog.getInt(
            self,
            "Go to Line",
            f"Line number (1–{n}):",
            value=self._array_pointer + 1,
            min=1,
            max=n,
        )
        if not ok:
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = line_num - 1
        self._update_ui_for_pointer()
        self._translated_line.setFocus()
```

- [ ] **Step 3: Enable `action_go_to_line` when a document is loaded**

Search for `action_save.setEnabled(True)` in `main_widget.py` (it is called in `_finish_load`, line ~445 area). Add alongside it:

```python
        self.action_go_to_line.setEnabled(True)
```

- [ ] **Step 4: Wire into combined_window.py View menu**

In `combined_window.py`, locate the View menu block (line ~107). Add after `view_menu.addAction(self._action_on_top)`:

```python
        view_menu.addAction(ta.action_go_to_line)
```

- [ ] **Step 5: Run the app to verify**

```bash
python -m translation_assistant.main
```

- Open a document. Press Ctrl+G — a dialog appears with current line pre-filled. Enter a valid line number — navigates there. Enter an out-of-range number — dialog enforces min/max.

- [ ] **Step 6: Run full test suite**

```bash
pytest -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py
git commit -m "feat(ui): add go-to-line Ctrl+G shortcut"
```

---

## Task 5: Reliable Resume (Last Document)

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`

### Background

`AppSettings.last_doc_id` (added in Task 2) stores the doc ID on close. On startup, `_load_initial_state` attempts to open it. `get_document` raises `ValueError` if the ID doesn't exist — catch it and fall back to blank. Position within the document is already handled by `open_document` which reads `documents.last_position`.

- [ ] **Step 1: Update `save_state()` to persist `_doc_id`**

`save_state` is at line ~1125. Replace:

```python
    def save_state(self) -> None:
        """Called by CombinedMainWindow.closeEvent."""
        self._settings.splitter_state = self._splitter.saveState()
        self._save_current_translation()
        self._settings.save()
```

with:

```python
    def save_state(self) -> None:
        """Called by CombinedMainWindow.closeEvent."""
        self._settings.splitter_state = self._splitter.saveState()
        self._save_current_translation()
        self._settings.last_doc_id = self._doc_id
        self._settings.save()
```

- [ ] **Step 2: Update `_load_initial_state()` to restore last doc**

Replace:

```python
    def _load_initial_state(self) -> None:
        self._update_parse_chars()
        self._load_glossary_for_profile()
        self._load_spell_dict()
        self._try_init_tts()
```

with:

```python
    def _load_initial_state(self) -> None:
        self._update_parse_chars()
        self._load_glossary_for_profile()
        self._load_spell_dict()
        self._try_init_tts()
        last = self._settings.last_doc_id
        if last is not None:
            try:
                self.open_document(last)
            except (ValueError, Exception):
                pass
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -q
```

Expected: all pass (no existing test exercises startup with a persisted doc_id; this is verified manually)

- [ ] **Step 4: Verify manually**

```bash
python -m translation_assistant.main
```

1. Open a document, navigate to line 10.
2. Close the app.
3. Re-launch — app opens the same document at line 10 automatically.
4. Test with a DB that doesn't have the saved doc (delete the doc first) — app starts blank with no error.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat(ui): restore last opened document on startup"
```

---

## Task 6: Open Dialog Pre-Selects Current Document

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`
- Modify: `translation_assistant/ui/main_widget.py`
- Test: `tests/test_dlg_open.py`

### Background

`OpenDocumentDialog._doc_ids` is a `dict[int, int]` mapping `id(QTreeWidgetItem)` → `doc_id`. To find a leaf by `doc_id`, iterate group items and their children comparing against that dict. After finding the item, call `setCurrentItem` and `scrollToItem`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dlg_open.py`:

```python
    def test_current_doc_preselected(self, qapp, mem_db):
        doc_id = mem_db.create_document("My Doc")
        dlg = OpenDocumentDialog(mem_db, current_doc_id=doc_id)
        current = dlg._tree.currentItem()
        assert current is not None
        assert current.childCount() == 0  # it's a leaf
        assert current.text(0) == "My Doc"

    def test_no_crash_when_current_doc_not_in_db(self, qapp, mem_db):
        mem_db.create_document("My Doc")
        dlg = OpenDocumentDialog(mem_db, current_doc_id=9999)
        # Should not raise; just no pre-selection
        assert dlg is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dlg_open.py -k "preselect or not_in_db" -v
```

Expected: 2 errors — `TypeError: __init__() got an unexpected keyword argument 'current_doc_id'`

- [ ] **Step 3: Update `OpenDocumentDialog.__init__` and add `_select_doc()`**

In `dlg_open.py`, update `__init__` signature and call:

```python
    def __init__(self, db: Database, parent=None, *, current_doc_id: int | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._selected_doc_id: int | None = None
        self._doc_ids: dict[int, int] = {}
        self._setup_ui()
        self._load_documents()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
```

Add the helper method after `_load_documents`:

```python
    def _select_doc(self, doc_id: int) -> None:
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                leaf = group.child(j)
                if self._doc_ids.get(id(leaf)) == doc_id:
                    self._tree.setCurrentItem(leaf)
                    self._tree.scrollToItem(leaf)
                    return
```

- [ ] **Step 4: Pass `self._doc_id` from `_on_open()` in `main_widget.py`**

In `main_widget.py`, locate `_on_open` (~line 767). Replace:

```python
            dlg = OpenDocumentDialog(self._db, parent=self)
```

with:

```python
            dlg = OpenDocumentDialog(self._db, parent=self, current_doc_id=self._doc_id)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_dlg_open.py -k "preselect or not_in_db" -v
```

Expected: 2 passed

- [ ] **Step 6: Run full test suite**

```bash
pytest -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_open.py translation_assistant/ui/main_widget.py tests/test_dlg_open.py
git commit -m "feat(ui): pre-select current document in Open dialog"
```

---

## Final Verification

- [ ] **Run full test suite one last time**

```bash
pytest -q
```

Expected: all pass, 6+ new tests added across `test_db.py`, `test_settings.py`, `test_dlg_open.py`.

- [ ] **Smoke-test the full workflow manually**

1. Launch app — last document auto-opens at saved line.
2. Navigate a few lines — TM panel shows/hides as expected.
3. Click a TM suggestion — translation box fills.
4. Toggle "Show Translation Memory" in Settings — panel stays hidden even on lines with matches.
5. Press Ctrl+G — dialog opens, enter line number, navigation works.
6. Press Ctrl+O — Open dialog highlights the currently open document.
7. Close and reopen — last position restored.

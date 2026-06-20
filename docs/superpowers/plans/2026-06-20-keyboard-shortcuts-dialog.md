# Keyboard Shortcuts Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Settings > Keyboard Shortcuts… dialog that lets users view and remap QAction-based shortcuts, with persistence via QSettings and read-only display of `_handle_key` event shortcuts.

**Architecture:** `AppSettings` gains shortcut get/set/clear methods; `TranslationAssistantWidget` builds a shortcut registry after `_build_actions()` and applies saved shortcuts at startup; `ShortcutsDialog` renders an editable `QTableWidget` with `QKeySequenceEdit` per QAction row and a read-only section for `_handle_key` shortcuts; `CombinedMainWindow` adds the menu entry and launches the dialog.

**Tech Stack:** PySide6 (`QDialog`, `QTableWidget`, `QKeySequenceEdit`, `QKeySequence`, `QMessageBox`), QSettings, pytest

## Global Constraints

- All QSettings access through `AppSettings` — never use `QSettings` directly outside `settings.py`
- Never import `sqlite3` outside `db.py`
- New dialog file: `translation_assistant/ui/dlg_shortcuts.py`
- Tests go in existing test files: `tests/test_settings.py`, `tests/test_main_window.py`, `tests/test_dialogs.py`, `tests/test_combined_window.py`
- Python 3.11+, PySide6

---

### Task 1: AppSettings shortcut persistence methods

**Files:**
- Modify: `translation_assistant/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `AppSettings.get_shortcut(key: str) -> str | None`
  - `AppSettings.set_shortcut(key: str, value: str) -> None`
  - `AppSettings.clear_shortcuts() -> None`

- [ ] **Step 1: Write the failing tests**

Open `tests/test_settings.py` and add at the end:

```python
class TestShortcutPersistence:
    def test_get_shortcut_returns_none_when_unset(self, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        s = AppSettings(_qs=qs)
        assert s.get_shortcut("new_doc") is None

    def test_set_and_get_shortcut(self, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        s = AppSettings(_qs=qs)
        s.set_shortcut("new_doc", "Ctrl+Z")
        assert s.get_shortcut("new_doc") == "Ctrl+Z"

    def test_clear_shortcuts(self, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        s = AppSettings(_qs=qs)
        s.set_shortcut("new_doc", "Ctrl+Z")
        s.set_shortcut("open", "Ctrl+Y")
        s.clear_shortcuts()
        assert s.get_shortcut("new_doc") is None
        assert s.get_shortcut("open") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pun/workspace/TranslationAssistant-PySide6-Port && source .venv/bin/activate && pytest tests/test_settings.py::TestShortcutPersistence -v
```

Expected: FAIL — `AttributeError: 'AppSettings' object has no attribute 'get_shortcut'`

- [ ] **Step 3: Add methods to AppSettings**

In `translation_assistant/settings.py`, add after the `save()` method:

```python
    # --- keyboard shortcuts ---

    def get_shortcut(self, key: str) -> str | None:
        return self._qs.value(f"shortcuts/{key}", None)

    def set_shortcut(self, key: str, value: str) -> None:
        self._qs.setValue(f"shortcuts/{key}", value)

    def clear_shortcuts(self) -> None:
        self._qs.remove("shortcuts")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_settings.py::TestShortcutPersistence -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add shortcut persistence methods"
```

---

### Task 2: Shortcut registry and startup loading in TranslationAssistantWidget

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `AppSettings.get_shortcut(key: str) -> str | None` from Task 1
- Produces:
  - `TranslationAssistantWidget.action_series_phrases: QAction` (shortcut "Ctrl+Shift+P")
  - `TranslationAssistantWidget._shortcut_registry: list[tuple[str, str, QAction, str]]` — each entry is `(key, display_name, action, default_shortcut)` where `key` is a stable string id, `display_name` is shown in the dialog, `action` is the live `QAction`, and `default_shortcut` is the original key string (e.g. `"Ctrl+N"`)
  - `TranslationAssistantWidget._apply_saved_shortcuts() -> None` — reads QSettings and updates action shortcuts

- [ ] **Step 1: Write failing tests**

In `tests/test_main_window.py`, add this import at top if not present:

```python
import sqlite3
from translation_assistant.db import Database
```

Then add this test class at the end of the file:

```python
def _make_widget(tmp_path):
    from PySide6.QtCore import QSettings
    from translation_assistant.settings import AppSettings
    from translation_assistant.ui.main_widget import TranslationAssistantWidget
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings = AppSettings(_qs=qs)
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return TranslationAssistantWidget(_settings=settings, _db=db), settings


class TestShortcutRegistry:
    def test_registry_has_expected_keys(self, qapp, tmp_path):
        w, _ = _make_widget(tmp_path)
        keys = [e[0] for e in w._shortcut_registry]
        for expected in ("new_doc", "open", "save", "profile", "phrase",
                         "go_to_line", "clipboard", "series_phrases",
                         "punct_0", "punct_8"):
            assert expected in keys, f"missing key: {expected}"

    def test_apply_saved_shortcuts_overrides_default(self, qapp, tmp_path):
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        from translation_assistant.ui.main_widget import TranslationAssistantWidget
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        settings = AppSettings(_qs=qs)
        settings.set_shortcut("save", "Ctrl+Z")
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        db.create_profile("Default", is_default=True)
        w = TranslationAssistantWidget(_settings=settings, _db=db)
        entry = next(e for e in w._shortcut_registry if e[0] == "save")
        _, _, action, _ = entry
        assert action.shortcut().toString() == "Ctrl+Z"

    def test_action_series_phrases_exists(self, qapp, tmp_path):
        w, _ = _make_widget(tmp_path)
        assert hasattr(w, "action_series_phrases")
        assert w.action_series_phrases.shortcut().toString() == "Ctrl+Shift+P"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_window.py::TestShortcutRegistry -v
```

Expected: FAIL — `AttributeError: 'TranslationAssistantWidget' object has no attribute '_shortcut_registry'`

- [ ] **Step 3: Move series_phrases action to main_widget**

In `translation_assistant/ui/main_widget.py`, at the end of `_build_actions()` (after `self.action_stats = ...`), add:

```python
        self.action_series_phrases = QAction("Series Phrase Suggestions…", self)
        self.action_series_phrases.setShortcut("Ctrl+Shift+P")
        self.action_series_phrases.triggered.connect(self._on_series_phrases)
```

In `main_widget.py`, add `_on_series_phrases` method near the other dialog launchers (e.g. after `_on_stats`):

```python
    def _on_series_phrases(self) -> None:
        from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog, _get_series_for_doc
        dlg = SeriesPhrasesDialog(
            self._db, self._settings,
            current_series=_get_series_for_doc(self._db, self._doc_id),
            parent=self,
        )
        dlg.exec()
```

- [ ] **Step 4: Clean up embedded shortcut text in action labels**

In `translation_assistant/ui/main_widget.py`, inside `_build_actions()`, change these six `QAction` constructors (keep everything else the same — triggers, setShortcut calls, setEnabled calls):

| Old label | New label |
|---|---|
| `"New Document (CTRL+N)"` | `"New Document"` |
| `"Open (CTRL+O)"` | `"Open"` |
| `"Save (CTRL+S)"` | `"Save"` |
| `"Profile (CTRL+P)"` | `"Profile"` |
| `"Phrase (CTRL+L)"` | `"Phrase"` |
| `"Go to Line… (Ctrl+G)"` | `"Go to Line…"` |
| `"Clipboard (CTRL+I)"` | `"Clipboard"` |

Also replace the `_punct_labels` list to strip the `(F_)` suffixes:

```python
        _punct_labels = [
            "Single Quote : 「　」",
            "Double Quote : 『　』",
            "Lenticular : 【　】",
            "Ellipsis : …",
            "Wave Dash : 〜",
            "Single Title Bracket : 〈 〉",
            "Double Title Bracket : 《 》",
            "Long Dash : ー",
            "Heart : ♡",
        ]
```

- [ ] **Step 5: Add _build_shortcut_registry and _apply_saved_shortcuts to main_widget**

In `translation_assistant/ui/main_widget.py`, add two new methods after `_build_actions`:

```python
    def _build_shortcut_registry(self) -> None:
        self._shortcut_registry: list[tuple[str, str, QAction, str]] = [
            ("new_doc",        "New Document",              self.action_new_doc,        "Ctrl+N"),
            ("open",           "Open",                      self.action_open,           "Ctrl+O"),
            ("save",           "Save",                      self.action_save,           "Ctrl+S"),
            ("profile",        "Profile",                   self.action_profile,        "Ctrl+P"),
            ("phrase",         "Phrase",                    self.action_phrase,         "Ctrl+L"),
            ("go_to_line",     "Go to Line",                self.action_go_to_line,     "Ctrl+G"),
            ("clipboard",      "Clipboard",                 self.action_clipboard,      "Ctrl+I"),
            ("series_phrases", "Series Phrase Suggestions", self.action_series_phrases, "Ctrl+Shift+P"),
        ]
        _punct_names = [
            "Single Quote", "Double Quote", "Lenticular",
            "Ellipsis", "Wave Dash", "Single Title Bracket",
            "Double Title Bracket", "Long Dash", "Heart",
        ]
        for i, (act, name) in enumerate(zip(self.punct_actions, _punct_names)):
            self._shortcut_registry.append(
                (f"punct_{i}", f"Special: {name}", act, f"F{i + 1}")
            )
        self._apply_saved_shortcuts()

    def _apply_saved_shortcuts(self) -> None:
        for key, _, action, _ in self._shortcut_registry:
            saved = self._settings.get_shortcut(key)
            if saved:
                action.setShortcut(saved)
```

In `__init__`, insert `self._build_shortcut_registry()` immediately after `self._build_actions()`:

```python
        self._build_actions()
        self._build_shortcut_registry()   # ← add this line
        self._setup_central_widget()
```

- [ ] **Step 6: Update combined_window.py to use ta.action_series_phrases**

In `translation_assistant/ui/combined_window.py`, find these lines in `_setup_menubar()`:

```python
        series_phrases_action = QAction("Series Phrase Suggestions… (Ctrl+Shift+P)", self)
        series_phrases_action.setShortcut("Ctrl+Shift+P")
        series_phrases_action.triggered.connect(self._on_series_phrases)
        tools_menu.addAction(series_phrases_action)
```

Replace with:

```python
        tools_menu.addAction(ta.action_series_phrases)
```

Then remove the `_on_series_phrases` method from `CombinedMainWindow` entirely (it now lives in `TranslationAssistantWidget`).

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/test_main_window.py::TestShortcutRegistry -v
```

Expected: 3 PASSED

- [ ] **Step 8: Run full test suite**

```bash
pytest -q
```

Expected: all pass (same count as before)

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/test_main_window.py
git commit -m "feat(widget): shortcut registry, migrate series_phrases action, clean action labels"
```

---

### Task 3: ShortcutsDialog

**Files:**
- Create: `translation_assistant/ui/dlg_shortcuts.py`
- Test: `tests/test_dialogs.py`

**Interfaces:**
- Consumes:
  - `registry: list[tuple[str, str, QAction, str]]` — from `TranslationAssistantWidget._shortcut_registry` (Task 2)
  - `settings: AppSettings` — `get_shortcut(key)`, `set_shortcut(key, value)`, `clear_shortcuts()` (Task 1)
- Produces:
  - `ShortcutsDialog(registry, settings, parent=None)` — `QDialog` subclass
  - `ShortcutsDialog._on_ok() -> None` — validates, saves, applies, accepts dialog
  - `ShortcutsDialog._on_reset() -> None` — resets all `QKeySequenceEdit` fields to defaults without saving
  - Module-level constant `_HANDLE_KEY_SHORTCUTS: list[tuple[str, str]]`

- [ ] **Step 1: Write failing tests**

In `tests/test_dialogs.py`, add these imports at the top of the file (after existing imports):

```python
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QKeySequenceEdit
```

Add this test class at the end of `test_dialogs.py`:

```python
class TestShortcutsDialog:
    def _make_registry(self, qapp):
        """Two-entry registry for testing."""
        entries = []
        for key, name, default in [
            ("new_doc", "New Document", "Ctrl+N"),
            ("open",    "Open",         "Ctrl+O"),
        ]:
            act = QAction(name, qapp)
            act.setShortcut(default)
            entries.append((key, name, act, default))
        return entries

    def test_row_count(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog, _HANDLE_KEY_SHORTCUTS
        from PySide6.QtWidgets import QTableWidget
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # 1 "Editable" header + len(registry) rows + 1 "View Only" header + len(_HANDLE_KEY_SHORTCUTS) rows
        expected = 2 + len(registry) + len(_HANDLE_KEY_SHORTCUTS)
        assert table.rowCount() == expected

    def test_edit_and_save(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        from PySide6.QtWidgets import QTableWidget
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # Row 0: "Editable" section header. Row 1: first editable row (new_doc).
        cell_widget = table.cellWidget(1, 1)
        assert cell_widget is not None, "Expected cell widget at row 1, col 1"
        kse = cell_widget.findChild(QKeySequenceEdit)
        kse.setKeySequence(QKeySequence("Ctrl+Z"))
        dlg._on_ok()
        assert settings.get_shortcut("new_doc") == "Ctrl+Z"
        _, _, action, _ = registry[0]
        assert action.shortcut().toString() == "Ctrl+Z"

    def test_reset_defaults(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        from PySide6.QtWidgets import QTableWidget
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # Change new_doc shortcut in the UI
        cell_widget = table.cellWidget(1, 1)
        kse = cell_widget.findChild(QKeySequenceEdit)
        kse.setKeySequence(QKeySequence("Ctrl+Z"))
        # Reset — should revert to default without saving
        dlg._on_reset()
        assert kse.keySequence().toString() == "Ctrl+N"
        assert settings.get_shortcut("new_doc") is None  # not saved

    def test_conflict_blocks_save(self, qapp, tmp_path):
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        from PySide6.QtWidgets import QTableWidget
        from unittest.mock import patch
        settings = make_settings(tmp_path)
        registry = self._make_registry(qapp)
        dlg = ShortcutsDialog(registry, settings)
        table = dlg.findChild(QTableWidget)
        # Set both rows (new_doc=row1, open=row2) to the same shortcut
        for row in (1, 2):
            cell_widget = table.cellWidget(row, 1)
            kse = cell_widget.findChild(QKeySequenceEdit)
            kse.setKeySequence(QKeySequence("Ctrl+Z"))
        with patch("translation_assistant.ui.dlg_shortcuts.QMessageBox.warning") as mock_warn:
            dlg._on_ok()
            mock_warn.assert_called_once()
        # Settings must remain unchanged
        assert settings.get_shortcut("new_doc") is None
        assert settings.get_shortcut("open") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dialogs.py::TestShortcutsDialog -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'translation_assistant.ui.dlg_shortcuts'`

- [ ] **Step 3: Implement ShortcutsDialog**

Create `translation_assistant/ui/dlg_shortcuts.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QKeySequenceEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QAction
    from translation_assistant.settings import AppSettings

_HANDLE_KEY_SHORTCUTS: list[tuple[str, str]] = [
    ("Enter",       "Save & Next"),
    ("PageDown",    "Next (no save)"),
    ("PageUp",      "Previous"),
    ("Ctrl+End",    "Jump to next untranslated"),
    ("Ctrl+Home",   "Jump to first"),
    ("Ctrl+Right",  "Advance parse"),
    ("Ctrl+Left",   "Retreat parse"),
    ("Ctrl+F",      "Copy translation to clipboard"),
    ("Ctrl+A",      "Select all in translation field"),
    ("Ctrl+J",      "Add word to dictionary"),
]


class ShortcutsDialog(QDialog):
    def __init__(
        self,
        registry: list[tuple[str, str, "QAction", str]],
        settings: "AppSettings",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(520, 560)
        self._registry = registry
        self._settings = settings
        self._editors: dict[str, QKeySequenceEdit] = {}

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 200)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self._populate()

        btn_box = QDialogButtonBox()
        self._btn_reset = QPushButton("Reset Defaults")
        self._btn_reset.clicked.connect(self._on_reset)
        btn_box.addButton(self._btn_reset, QDialogButtonBox.ButtonRole.ResetRole)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_box.addButton(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addWidget(btn_box)

    def _add_section_header(self, label: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        item = QTableWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setBackground(self.palette().mid())
        self._table.setItem(row, 0, item)
        self._table.setSpan(row, 0, 1, 2)

    def _add_editable_row(self, key: str, name: str, action: "QAction", default: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, 0, name_item)

        current = self._settings.get_shortcut(key) or default
        kse = QKeySequenceEdit(QKeySequence(current))
        kse.setProperty("_default", default)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(28)
        clear_btn.setToolTip("Reset to default")
        clear_btn.clicked.connect(lambda: kse.setKeySequence(QKeySequence(default)))

        cell_widget = QWidget()
        h = QHBoxLayout(cell_widget)
        h.setContentsMargins(2, 2, 2, 2)
        h.addWidget(kse)
        h.addWidget(clear_btn)

        self._table.setCellWidget(row, 1, cell_widget)
        self._editors[key] = kse

    def _add_readonly_row(self, key_str: str, name: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, 0, name_item)

        key_item = QTableWidgetItem(key_str)
        key_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._table.setItem(row, 1, key_item)

    def _populate(self) -> None:
        self._table.setRowCount(0)
        self._editors.clear()
        self._add_section_header("─── Editable ───")
        for key, name, action, default in self._registry:
            self._add_editable_row(key, name, action, default)
        self._add_section_header("─── View Only ───")
        for key_str, name in _HANDLE_KEY_SHORTCUTS:
            self._add_readonly_row(key_str, name)

    def _on_reset(self) -> None:
        for key, _, _, default in self._registry:
            editor = self._editors.get(key)
            if editor is not None:
                editor.setKeySequence(QKeySequence(default))

    def _on_ok(self) -> None:
        seen: dict[str, str] = {}  # sequence string -> display name
        conflicts: list[str] = []
        for key, name, _, _ in self._registry:
            kse = self._editors.get(key)
            if kse is None:
                continue
            seq = kse.keySequence().toString()
            if not seq:
                continue
            if seq in seen:
                conflicts.append(f'"{name}" and "{seen[seq]}"')
            else:
                seen[seq] = name

        if conflicts:
            QMessageBox.warning(
                self,
                "Shortcut Conflict",
                "The following shortcuts conflict:\n\n" + "\n".join(conflicts)
                + "\n\nPlease resolve before saving.",
            )
            return

        for key, _, action, _ in self._registry:
            kse = self._editors.get(key)
            if kse is None:
                continue
            seq = kse.keySequence().toString()
            self._settings.set_shortcut(key, seq)
            action.setShortcut(seq)

        self.accept()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dialogs.py::TestShortcutsDialog -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_shortcuts.py tests/test_dialogs.py
git commit -m "feat(ui): add ShortcutsDialog with editable and read-only shortcut table"
```

---

### Task 4: Wire menu entry in CombinedMainWindow

**Files:**
- Modify: `translation_assistant/ui/combined_window.py`
- Test: `tests/test_combined_window.py`

**Interfaces:**
- Consumes: `TranslationAssistantWidget._shortcut_registry` and `TranslationAssistantWidget._settings` (Task 2)
- Consumes: `ShortcutsDialog(registry, settings, parent)` (Task 3)

- [ ] **Step 1: Write failing test**

In `tests/test_combined_window.py`, add this test class at the end:

```python
class TestShortcutsMenuEntry:
    def test_settings_menu_has_shortcuts_action(self, qapp, tmp_path):
        from unittest.mock import patch
        from PySide6.QtCore import QSettings
        from translation_assistant.settings import AppSettings
        from translation_assistant.ui.combined_window import CombinedMainWindow
        qs = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        settings = AppSettings(_qs=qs)
        with patch("ta.ui.aggregator_widget.ClipboardMonitor"):
            win = CombinedMainWindow(_settings=settings, _db=_make_db())
        mb = win.menuBar()
        settings_menu = next(
            (a.menu() for a in mb.actions() if a.text() == "Settings"), None
        )
        assert settings_menu is not None
        action_texts = [a.text() for a in settings_menu.actions()]
        assert "Keyboard Shortcuts…" in action_texts
        win.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_combined_window.py::TestShortcutsMenuEntry -v
```

Expected: FAIL — `"Keyboard Shortcuts…" not in action_texts`

- [ ] **Step 3: Add menu entry and handler to combined_window.py**

In `translation_assistant/ui/combined_window.py`, in `_setup_menubar()`, find the Settings menu block (around the `settings_menu.addMenu(tts_menu)` line) and add after it:

```python
        settings_menu.addSeparator()
        shortcuts_action = QAction("Keyboard Shortcuts…", self)
        shortcuts_action.triggered.connect(self._on_shortcuts)
        settings_menu.addAction(shortcuts_action)
```

Add `_on_shortcuts` method to `CombinedMainWindow` (near the other `_on_*` methods):

```python
    def _on_shortcuts(self) -> None:
        from translation_assistant.ui.dlg_shortcuts import ShortcutsDialog
        ta = self._ta_widget
        dlg = ShortcutsDialog(ta._shortcut_registry, ta._settings, self)
        dlg.exec()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_combined_window.py::TestShortcutsMenuEntry -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/combined_window.py tests/test_combined_window.py
git commit -m "feat(ui): wire Keyboard Shortcuts… menu entry under Settings"
```

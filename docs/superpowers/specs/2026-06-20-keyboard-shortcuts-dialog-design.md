# Keyboard Shortcuts Dialog — Design Spec

**Date:** 2026-06-20  
**Status:** Approved

## Overview

Add a "Keyboard Shortcuts…" dialog under Settings that lets users view all shortcuts and remap QAction-based ones. `_handle_key` event-filter shortcuts are shown read-only. Custom shortcuts persist via QSettings.

---

## Architecture

### New file
`translation_assistant/ui/dlg_shortcuts.py` — `ShortcutsDialog(QDialog)`

### Shortcut registry
Defined in `TranslationAssistantWidget` after `_build_actions()` completes:

```python
# list[tuple[str, str, QAction, str]]  (key, display_name, action, default)
self._shortcut_registry = [
    ("new_doc",            "New Document",                self.action_new_doc,            "Ctrl+N"),
    ("open",               "Open",                        self.action_open,               "Ctrl+O"),
    ("save",               "Save",                        self.action_save,               "Ctrl+S"),
    ("profile",            "Profile",                     self.action_profile,            "Ctrl+P"),
    ("phrase",             "Phrase",                      self.action_phrase,             "Ctrl+L"),
    ("go_to_line",         "Go to Line",                  self.action_go_to_line,         "Ctrl+G"),
    ("clipboard",          "Clipboard",                   self.action_clipboard,          "Ctrl+I"),
    ("series_phrases",     "Series Phrase Suggestions",   self.action_series_phrases,     "Ctrl+Shift+P"),
]
```

Special punctuation F-key actions (F1–FN) are included as separate registry entries, keyed `punct_0` … `punct_N`.

### Read-only handle_key list
Constant in `dlg_shortcuts.py`:

```python
_HANDLE_KEY_SHORTCUTS = [
    ("Enter",      "Save & Next"),
    ("PageDown",   "Next (no save)"),
    ("PageUp",     "Previous"),
    ("Ctrl+End",   "Jump to next untranslated"),
    ("Ctrl+Home",  "Jump to first"),
    ("Ctrl+Right", "Advance parse"),
    ("Ctrl+Left",  "Retreat parse"),
    ("Ctrl+F",     "Copy translation to clipboard"),
    ("Ctrl+A",     "Select all in translation field"),
    ("Ctrl+J",     "Add word to dictionary"),
]
```

### Persistence
`AppSettings` gains two methods:

```python
def get_shortcut(self, key: str) -> str | None:
    return self._qs.value(f"shortcuts/{key}", None)

def set_shortcut(self, key: str, value: str) -> None:
    self._qs.setValue(f"shortcuts/{key}", value)

def clear_shortcuts(self) -> None:
    self._qs.remove("shortcuts")
```

### Startup loading
After `_build_actions()` in `TranslationAssistantWidget.__init__`, call:

```python
self._apply_saved_shortcuts()
```

Which iterates `_shortcut_registry` and calls `action.setShortcut(saved)` for any non-empty stored override. Invalid/empty values are skipped.

### Menu label cleanup
Action labels currently embed shortcuts in the display name (e.g. `"New Document (CTRL+N)"`). These are stripped to plain names (e.g. `"New Document"`). Qt renders shortcuts natively via `setShortcut`. This is done as part of this work.

---

## Dialog UI

```
┌─ Keyboard Shortcuts ──────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Action                    │ Shortcut                │  │
│  │ ─────────────── Editable ───────────────────────────│  │
│  │ New Document              │ [Ctrl+N          ] [X]  │  │
│  │ Open                      │ [Ctrl+O          ] [X]  │  │
│  │ Save                      │ [Ctrl+S          ] [X]  │  │
│  │ ...                       │ ...                     │  │
│  │ ─────────────── View Only ──────────────────────────│  │
│  │ Save & Next               │  Enter           (read) │  │
│  │ Next (no save)            │  PageDown        (read) │  │
│  │ ...                       │ ...                     │  │
│  └─────────────────────────────────────────────────────┘  │
│                   [Reset Defaults]  [Cancel]  [OK]         │
└───────────────────────────────────────────────────────────┘
```

**Table:** `QTableWidget`, 2 columns ("Action", "Shortcut"), no row numbers, no grid lines on section headers.

**Editable rows:**
- Column 1: `QTableWidgetItem` (read-only flags)
- Column 2: `QKeySequenceEdit` set via `setCellWidget`
- Clear button `[X]` in column 2 via a `QWidget` containing `QKeySequenceEdit` + `QPushButton` in an `QHBoxLayout`; clicking X resets the field to the default sequence

**Section header rows:** Disabled `QTableWidgetItem` spanning both columns, bold text, grey background (`palette.mid()` color).

**Read-only rows:**
- Column 2: plain `QTableWidgetItem` with `Qt.ItemFlag.NoItemFlags`; text is the key string

**Buttons:**
- `Reset Defaults` — clears all `QKeySequenceEdit` fields back to defaults (does not save yet)
- `Cancel` — closes, no changes
- `OK` — runs conflict check, saves to QSettings, applies to QActions, closes

---

## Conflict Detection

On OK:
1. Collect all non-empty `QKeySequenceEdit` values.
2. If any two entries share the same sequence, show `QMessageBox.warning` listing the conflicting action names.
3. Block save until resolved. User must change or clear one of the conflicting entries.

Empty sequence (cleared shortcut) is allowed — no conflict possible with another empty.

---

## Menu Integration

In `CombinedMainWindow._setup_menubar()`, Settings menu:

```python
shortcuts_action = QAction("Keyboard Shortcuts…", self)
shortcuts_action.triggered.connect(self._on_shortcuts)
settings_menu.addAction(shortcuts_action)
```

`_on_shortcuts` instantiates `ShortcutsDialog(ta._shortcut_registry, ta._settings, self)` and calls `.exec()`.

---

## Testing

One test class in `tests/test_dialogs.py`:

- **`test_shortcuts_dialog_row_count`** — open dialog, assert total rows = len(registry) + len(_HANDLE_KEY_SHORTCUTS) + 2 section headers
- **`test_shortcuts_dialog_edit_and_save`** — set a `QKeySequenceEdit` to a new sequence, click OK, assert `settings.get_shortcut(key)` returns new value and `action.shortcut()` matches
- **`test_shortcuts_dialog_reset`** — change a field, click Reset Defaults, assert fields revert to defaults (without saving)
- **`test_shortcuts_dialog_conflict`** — set two rows to same sequence, click OK, assert warning shown and dialog not closed

---

## Out of Scope

- `_handle_key` event-filter shortcuts are not remappable in this iteration.
- No per-profile shortcut sets (global only).
- No import/export of shortcut configurations.

# New Series Feature Design

**Date:** 2026-06-10
**Status:** Approved

## Summary

Split the existing "New" action into "New Document" and "New Series". Add a toolbar with both actions to `CombinedMainWindow`. Add a "New Series…" button to `SeriesManagerDialog`. Create a new `NewSeriesDialog` for registering a series (title, profile, URL) without requiring a document.

## Scope

Only `CombinedMainWindow` / `TranslationAssistantWidget` path is in scope. `main_window.py` is dead code (used only by legacy tests) and is not touched.

---

## Components

### New file: `translation_assistant/ui/dlg_new_series.py`

Class `NewSeriesDialog(QDialog)`:

- **Fields:**
  - Series Title — `QLineEdit`, required
  - "Create new profile for this series" — `QCheckBox`
  - Syosetu URL — `QLineEdit`, optional
- **Validation:** empty title shows `QMessageBox.warning`; dialog stays open
- **On accept:**
  1. `db.set_series_url(title, url)` — idempotent upsert
  2. If checkbox checked and `db.get_profile_id(title) is None`: `db.create_profile(title)`, then `db.set_series_profile(title, title)`
  3. Store `series_title` and `created_profile` as read-only properties
- **Guard:** if `db is None`, show warning and return without accepting

### Changed: `translation_assistant/ui/main_widget.py`

In `_build_actions()`:
- Replace `action_new` with `action_new_doc` — text `"New Document (CTRL+N)"`, shortcut `Ctrl+N`, connects to `_on_new_doc`
- Add `action_new_series` — text `"New Series"`, connects to `_on_new_series`

Rename `_on_new` → `_on_new_doc` (behaviour unchanged).

Add `_on_new_series`:
1. Guard: return if `self._db is None`
2. Open `NewSeriesDialog(self._db, parent=self)` inside `_topmost_suspended()`
3. On accept: open `SeriesManagerDialog(self._db, parent=self)` (table auto-loads new series)

### Changed: `translation_assistant/ui/combined_window.py`

In `_setup_menubar()`, File menu:
- Replace `ta.action_new` with `ta.action_new_doc` followed by `ta.action_new_series`

Add `_setup_toolbar()`:
```python
def _setup_toolbar(self) -> None:
    tb = self.addToolBar("Main")
    tb.setMovable(False)
    ta = self._ta_widget
    tb.addAction(ta.action_new_doc)
    tb.addAction(ta.action_new_series)
```

Call `self._setup_toolbar()` from `__init__` after `_setup_menubar()`.

### Changed: `translation_assistant/ui/dlg_series.py`

Add "New Series…" `QPushButton` to the button row (before "Set URL…"):
- On click: open `NewSeriesDialog(self._db, parent=self)`; on accept, call `self._load()` to refresh table

---

## Data Flow

```
_on_new_series()
  └─ NewSeriesDialog.exec()
       ├─ db.set_series_url(title, url)
       ├─ [if checkbox] db.create_profile(title)   # guarded by get_profile_id check
       └─ [if checkbox] db.set_series_profile(title, title)
  └─ [on accept] SeriesManagerDialog.exec()
       └─ _load() → get_series_list_full() → shows new row
```

No new DB methods required. All DB calls use existing upsert semantics.

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| Empty title | `QMessageBox.warning`, dialog stays open |
| Duplicate series | `set_series_url` / `set_series_profile` use `ON CONFLICT DO UPDATE` — idempotent |
| Profile already exists | `get_profile_id` guard skips `create_profile` |
| `db is None` | `QMessageBox.warning`, handler returns early |

---

## Testing

New file: `tests/test_dlg_new_series.py`

- Empty title rejected (dialog does not accept)
- Series + URL saved to DB on accept
- Profile created and linked when checkbox checked
- Profile not created when checkbox unchecked
- Duplicate series upsert — no error, URL updated
- Profile-already-exists guard — `create_profile` not called twice

No tests for toolbar wiring (pure Qt, no logic). `SeriesManagerDialog` "New Series…" button covered by `dlg_new_series` unit tests.

---

## Files Not Touched

- `translation_assistant/ui/main_window.py` — legacy standalone window; not imported by `main.py`; excluded from this feature
- `translation_assistant/db.py` — no new methods needed
- `translation_assistant/core.py` — pure text logic; unaffected

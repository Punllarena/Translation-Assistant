# UI/UX Improvements Checklist

Audit of improvement areas. Grouped by category, ordered high→low impact within each group.

---

## Menu Bar

- [x] **#1** Move "Clipboard" (Ctrl+I) from top-level menu item into File as "Copy to Clipboard"
- [x] **#2** Move "About" from Tools → Help
- [x] **#3** Move "Statistics…" from Help → Tools
- [x] **#4** Split Settings menu: keep dialogs (Profile, Phrase, Shortcuts); move toggles (Show Progress, Show Translation Memory) into View
- [x] **#5** Demote "Special Punctuations" from top-level to submenu under Tools
- [x] **#6** Add recent documents list (last 5–10) in File menu above the Import separator

---

## Empty / No-Document State

- [x] **#7** Replace raw help text injected into context panels with a styled placeholder or welcome screen; clear on first document open
- [x] **#8** Hide or gray out status bar labels (Words, Line) when no document is loaded
- [x] **#9** Disable translation input or show placeholder text when no document is open

---

## Working Panels

- [x] **#10** Add asterisk to window title (`Translation Assistant *`) when there are unsaved changes
- [x] **#11** Indicate Source panel is read-only in its label (e.g. append `(read-only)` or lock icon)
- [x] **#12** Show active profile name in status bar (e.g. `Profile: Default`)
- [x] **#13** Hide "TM Matches" label when TM panel is collapsed
- [x] **#14** Make "TM Matches" label clickable to toggle the panel; also add toggle to View menu

---

## Dialogs

- [x] **#15** Wire Enter key in OpenDocumentDialog tree to trigger Open
- [x] **#16** Style the Delete button in OpenDocumentDialog as destructive (red text or moved behind ellipsis)
- [x] **#17** Show progress indicator (spinner / disabled buttons + "Fetching…" label) during Re-fetch in OpenDocumentDialog

---

## Minor / Polish

- [x] **#18** Change Clipboard action shortcut from Ctrl+I to Ctrl+Shift+C (Ctrl+I conflicts with italic convention)
- [x] **#19** Group database backup actions (Export/Import Database Backup) under a "Database" submenu or labeled separator in File
- [x] **#20** Expose autosave interval in Settings, or display autosave badge in status bar

---

## Implementation Order (recommended)

1. #1, #2, #3, #4, #5 — menu hygiene (one pass through `combined_window.py`)
2. #7, #8, #9 — no-document empty state (`main_widget.py`)
3. #10 — dirty indicator (window title)
4. #12 — profile in status bar
5. #6 — recent documents
6. #13, #14 — TM panel label/toggle
7. #15, #16, #17 — dialog polish
8. #11, #18, #19, #20 — minor polish

# Design: Merge Translation Assistant + Translation Aggregator

**Date:** 2026-06-10
**Repo:** TranslationAssistant-PySide6-Port

## Goal

Combine the Translation Assistant (human translation workflow) and Translation Aggregator (machine translation reference) into one application window. Assistant on the left, Aggregator on the right. When the user navigates to a new sentence in the Assistant, the Aggregator automatically translates it as a reference.

---

## Architecture

### Approach

Two packages coexist in this repo. The `ta/` package is copied verbatim from ta-python. Both existing `MainWindow` classes are refactored into `QWidget` subclasses. A new `CombinedMainWindow` hosts both in a horizontal `QSplitter`.

### File structure changes

```
translation_assistant/
└── ui/
    ├── main_window.py        # DELETED: replaced by main_widget.py + combined_window.py
    ├── main_widget.py        # NEW: TranslationAssistantWidget(QWidget) — all TA logic
    ├── combined_window.py    # NEW: CombinedMainWindow(QMainWindow) — merged app
    └── ...                   # all dialogs unchanged

ta/                           # NEW: copied verbatim from ta-python
├── config/
├── core/
├── translators/
└── ui/
    ├── aggregator_widget.py  # NEW: AggregatorWidget(QWidget) — extracted from ta-python MainWindow
    ├── source_panel.py       # verbatim
    ├── panels_container.py   # verbatim
    └── translation_panel.py  # verbatim
```

`main.py` launches `CombinedMainWindow` directly.

---

## Signal Bridge

One-way push from Assistant to Aggregator. No other coupling.

### `TranslationAssistantWidget`

Gains one new signal:

```python
source_sentence_changed = Signal(str)
```

Emitted in `_move_to_line` with the raw source text of the newly active sentence.

### `AggregatorWidget`

Gains one public slot:

```python
def translate_source(self, text: str) -> None:
    self._source_panel.set_text(text)
    self._on_translate(text)
```

### `CombinedMainWindow` wiring

```python
self._ta_widget.source_sentence_changed.connect(
    self._agg_widget.translate_source
)
```

---

## Unified Menu Bar

`CombinedMainWindow` builds one menu bar. Both widgets lose their `_setup_menu` methods.

| Menu | Items |
|------|-------|
| **File** | New, Open, Save, ─, Import, Export, Manage Series, ─, Quit |
| **Settings** | Profile…, Add Phrase…, ─, Aggregator Settings…, Substitutions… |
| **View** | Always on Top |
| **Tools** | History…, ─, Help |

- File / TA actions → delegate to `TranslationAssistantWidget`
- Aggregator Settings / Substitutions / History → delegate to `AggregatorWidget`
- Always on Top, opacity shortcuts → handled by `CombinedMainWindow`

---

## Settings Coexistence

No merging of settings systems.

- **TA-Port**: `AppSettings` (QSettings + SQLite `ta.db`) — unchanged
- **Aggregator**: JSON config at `~/.config/ta-python/config.json` — unchanged

Each widget initializes its own settings on construction.

---

## Layout Persistence

`CombinedMainWindow.closeEvent` saves:

- `QSplitter` left/right ratio via `QSettings` key `combined/splitter`
- Each widget's internal geometry saved as before

---

## Testing

- **`tests/test_main_window.py`**: updated to instantiate `TranslationAssistantWidget` directly (replaces `MainWindow`)
- **`tests/test_aggregator_widget.py`**: ta-python tests copied in, updated to use `AggregatorWidget`
- **`tests/test_combined_window.py`**: new — verifies signal bridge: navigating in TA calls `translate_source` on Aggregator

All existing TA-Port tests remain green. ta-python tests migrated and green.

---

## Out of Scope

- Merging `ta/` into `translation_assistant/` (can be done later)
- Bidirectional communication (Aggregator → Assistant)
- Shared settings system
- Mode flags (`--mode assistant|aggregator|combined`)

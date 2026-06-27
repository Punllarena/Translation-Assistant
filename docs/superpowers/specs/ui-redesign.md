# Translation Assistant — UI Overhaul Spec

> Adapted from `~/Downloads/translation-assistant-ui-redesign.md`.  
> Conflicts with the current codebase are **called out inline**.

---

## Conflict Summary (read first)

| # | Redesign doc says | Reality / Resolution |
|---|---|---|
| 1 | Refactor `ui/main_window.py` | **LEGACY — do not touch.** Target `ui/main_widget.py` + `ui/combined_window.py`. |
| 2 | `from PyQt5.QtWidgets import …` | Project uses **PySide6** throughout. All QSS and Python code must use PySide6. |
| 3 | 2-panel layout: editable Source \| read-only Translation | **Wrong.** Actual layout is a **5-panel vertical QSplitter**: Context Above / Source (read-only JP) / TM Matches / Translation (editable EN) / Context Below. |
| 4 | Engine Bar in main widget | Engine/language selection lives in **`AggregatorWidget`** (right pane, `ta/ui/`). Do not add to `TranslationAssistantWidget`. See §8 for Aggregator redesign. |
| 5 | Language Swap Bar in main widget | Language pair lives in `SourcePanel` (`ta/ui/source_panel.py`). Redesign applies there. See §8. |
| 6 | "Translate →" button | **Does not belong in main widget** — this is a human translation tool, not an MT tool. `AggregatorWidget` handles MT. |
| 7 | WP button in Translation panel | WP publishing is per-document (not per-paragraph). It's already a menu action + dialog. Expose it as a **toolbar button** (see §4.4), not an inline panel button. |
| 8 | Status bar: custom QFrame | Main widget already owns a `QStatusBar` with multiple widgets (`_line_label`, `_word_label`, `_progress_bar`, etc.). **Restyle in-place** — don't replace the widget tree. |
| 9 | Frameless custom title bar | `CombinedMainWindow` is the `QMainWindow`. Frameless mode is optional / Phase 2 — high risk for window manager integration. |
| 10 | `assets/` dir doesn't exist | Create `translation_assistant/resources/style.qss` (fonts dir already at `translation_assistant/resources/`). |

---

## 1. Design Tokens

### 1.1 Color Palette

| Token | Hex | Role |
|---|---|---|
| `--bg-base` | `#0F1117` | App background |
| `--bg-surface` | `#1A1D27` | Panel backgrounds |
| `--bg-elevated` | `#23263A` | Input fields, hover states |
| `--border` | `#2E3350` | Dividers, input outlines |
| `--accent` | `#5C6BFF` | Primary action, focus ring |
| `--accent-muted` | `#3D4AB3` | Secondary accents |
| `--text-primary` | `#E8E6F0` | Primary body text |
| `--text-secondary` | `#8B8FA8` | Labels, hints, placeholders |
| `--text-source` | `#F0EDE8` | Source text (warm — JP) |
| `--text-translated` | `#EAF0FF` | Translation text (cool — EN) |
| `--success` | `#3ECF8E` | Complete / OK |
| `--warning` | `#F5A623` | Warning / fallback |
| `--danger` | `#FF5E5E` | Error |

### 1.2 Typography

| Role | Font | Size | Weight |
|---|---|---|---|
| App title | `IBM Plex Mono` | 13px | 600 |
| Source / Translation text | `Noto Sans JP` | 16px | 400 |
| UI labels | `Inter` | 12px | 500 |
| Status / captions | `Inter` | 11px | 400 |

**Font files** go in `translation_assistant/resources/fonts/`:
- `NotoSansJP-Regular.ttf`
- `Inter-Regular.ttf`, `Inter-Medium.ttf`, `Inter-SemiBold.ttf`
- `IBMPlexMono-SemiBold.ttf`

Load at startup in `main.py` via `QFontDatabase.addApplicationFont`.

### 1.3 Spacing Scale

```
4px  — micro (icon padding, tag spacing)
8px  — small (label ↔ control)
12px — base (input internal padding)
16px — medium (section padding)
24px — large (panel padding)
```

### 1.4 Border Radius

| Element | Radius |
|---|---|
| Buttons | `8px` |
| Input fields | `8px` |
| Panels | `12px` |
| Status badge | `4px` |

---

## 2. Actual Layout Architecture

```
CombinedMainWindow (QMainWindow)  ← combined_window.py
├── QMenuBar
└── QSplitter (Horizontal)
    ├── TranslationAssistantWidget (QWidget)  ← main_widget.py
    │   ├── QSplitter (Vertical)
    │   │   ├── Context Above  (ReviewTextEdit, read-only)
    │   │   ├── Source         (QTextEdit, read-only, raw JP)
    │   │   ├── TM Matches     (collapsible panel)
    │   │   ├── Translation    (QTextEdit, editable EN)
    │   │   └── Context Below  (ReviewTextEdit, read-only)
    │   └── QStatusBar         (progress, line, word, profile, autosave, stats)
    └── AggregatorWidget (QWidget)  ← ta/ui/aggregator_widget.py
        └── (engine selector, language pair, MT panels — OUT OF SCOPE)
```

The redesign's "Source | Translation" horizontal two-panel layout **does not match** this. Adapt panel styling to the **vertical splitter** model.

---

## 3. Stylesheet (QSS)

Create `translation_assistant/resources/style.qss`. Load in `main.py`:

```python
from pathlib import Path
from PySide6.QtWidgets import QApplication

def _load_qss() -> str:
    p = Path(__file__).parent / "resources" / "style.qss"
    return p.read_text(encoding="utf-8") if p.exists() else ""

# in main():
app.setStyleSheet(_load_qss())
```

### QSS Section Map

```
/* === Base === */
/* === Typography === */
/* === QTextEdit / QPlainTextEdit === */
/* === Buttons === */
/* === Panels === */
/* === Splitter === */
/* === ComboBox === */
/* === Dialogs === */
/* === Status Bar === */
/* === Scrollbars === */
/* === Context panels === */
```

### Key QSS rules (PySide6-compatible)

```css
/* Base */
QWidget {
    background-color: #0F1117;
    color: #E8E6F0;
    font-family: 'Inter';
    font-size: 12px;
}

/* Source text panel — warm tint */
QTextEdit#SourceText {
    background: #1A1D27;
    color: #F0EDE8;
    border: none;
    font-family: 'Noto Sans JP';
    font-size: 16px;
    padding: 12px;
    selection-background-color: #3D4AB3;
}

/* Translation text panel — cool tint */
QTextEdit#TranslationText {
    background: #161929;
    color: #EAF0FF;
    border: none;
    font-family: 'Noto Sans JP';
    font-size: 16px;
    padding: 12px;
    selection-background-color: #3D4AB3;
}

/* Context panels (read-only review areas) */
QTextEdit#ContextAbove,
QTextEdit#ContextBelow {
    background: #13151E;
    color: #8B8FA8;
    border: none;
    font-family: 'Noto Sans JP';
    font-size: 13px;
    padding: 8px;
}

/* Splitter handle */
QSplitter::handle {
    background: #2E3350;
    height: 1px;
}

/* Buttons */
QPushButton {
    background: #23263A;
    border: 1px solid #2E3350;
    border-radius: 8px;
    color: #E8E6F0;
    padding: 6px 14px;
    font-family: 'Inter';
    font-size: 12px;
}
QPushButton:hover  { background: #2E3350; }
QPushButton:pressed { background: #3D4AB3; }
QPushButton:disabled { color: #8B8FA8; }

/* Accent (primary) button */
QPushButton#AccentBtn {
    background: #5C6BFF;
    border: none;
    font-weight: 600;
}
QPushButton#AccentBtn:hover { background: #7380FF; }

/* ComboBox */
QComboBox {
    background: #23263A;
    border: 1px solid #2E3350;
    border-radius: 8px;
    padding: 6px 12px;
    color: #E8E6F0;
    font-family: 'Inter';
}
QComboBox QAbstractItemView {
    background: #23263A;
    border: 1px solid #2E3350;
    color: #E8E6F0;
    selection-background-color: #3D4AB3;
}

/* LineEdit */
QLineEdit {
    background: #23263A;
    border: 1px solid #2E3350;
    border-radius: 8px;
    padding: 6px 12px;
    color: #E8E6F0;
}
QLineEdit:focus { border-color: #5C6BFF; }

/* Dialogs */
QDialog {
    background: #1A1D27;
    border: 1px solid #2E3350;
    border-radius: 12px;
}

/* Status bar */
QStatusBar {
    background: #0F1117;
    border-top: 1px solid #2E3350;
    font-family: 'Inter';
    font-size: 11px;
    color: #8B8FA8;
}
QStatusBar QLabel { color: #8B8FA8; }

/* Slim scrollbars */
QScrollBar:vertical {
    background: #1A1D27;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #2E3350;
    border-radius: 3px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover { background: #5C6BFF; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }

/* Menu */
QMenuBar {
    background: #0F1117;
    border-bottom: 1px solid #2E3350;
    color: #8B8FA8;
}
QMenuBar::item:selected { background: #23263A; color: #E8E6F0; }
QMenu {
    background: #1A1D27;
    border: 1px solid #2E3350;
    color: #E8E6F0;
}
QMenu::item:selected { background: #3D4AB3; }
```

---

## 4. Component Adaptations

### 4.1 Panel Labels

Current labels (`"Context (Above)"`, `"Source (read-only)"`, `"TM Matches"`, `"Translation"`) use inline `setStyleSheet("font-size: 9pt; color: gray; …")`. **Replace with QSS object-name rules:**

```css
QLabel#PanelLabel {
    font-family: 'Inter';
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2px;
    color: #8B8FA8;
    text-transform: uppercase;
    padding: 2px 6px;
    background: transparent;
}
```

Set `setObjectName("PanelLabel")` on each label widget. Remove inline `setStyleSheet` calls from `_setup_central_widget`.

### 4.2 Source Panel

- `_raw_line` → `setObjectName("SourceText")`
- Styled via `QTextEdit#SourceText` in QSS (warm tint, Noto Sans JP)
- Keep read-only; add `setPlaceholderText` already present
- Wrap in `QFrame#SourcePanel` with `border: 1px solid #2E3350; border-radius: 12px` if desired (optional — splitter handles separation)

### 4.3 Translation Panel

- `_translated_line` → `setObjectName("TranslationText")`
- Styled via `QTextEdit#TranslationText` (cool tint, Noto Sans JP)
- Spell highlighter already wired — no change

### 4.4 Context Panels

- `_review_top` → `setObjectName("ContextAbove")`
- `_review_bottom` → `setObjectName("ContextBelow")`
- Styled more muted than source/translation to visually recede

### 4.5 Toolbar / Publish Button

The redesign's "↑ WordPress" panel button is wrong for this app (WP push is per-document).  
Instead, add a **slim icon toolbar** in `CombinedMainWindow` above the horizontal splitter:

```
┌──────────────────────────────────────────────────────────────┐
│ [Open] [Save]  ···  [Profile ▼]  ···  [↑ WordPress]  [Stats] │
└──────────────────────────────────────────────────────────────┘
```

Bind to existing `ta.action_open`, `ta.action_save`, `ta.action_publish_wp`, `ta.action_stats`. This avoids duplicating action logic.

### 4.6 Status Bar

`_status_bar` in `TranslationAssistantWidget` is a `QStatusBar`. Restyle in-place via QSS (`QStatusBar`, `QStatusBar QLabel`). No structural change needed.

Add object names for colored status dots if wanted:
```css
QLabel#StatusDot[state="ok"]      { color: #3ECF8E; }
QLabel#StatusDot[state="working"] { color: #F5A623; }
QLabel#StatusDot[state="error"]   { color: #FF5E5E; }
QLabel#StatusDot[state="idle"]    { color: #8B8FA8; }
```

### 4.7 Dialogs

All existing dialogs (`dlg_open`, `dlg_new`, `dlg_series`, `dlg_phrase`, etc.) inherit `QDialog` — they pick up the global `QDialog` QSS rule automatically. No structural changes needed for Phase 1.

The redesign's unified Settings sidebar dialog is Phase 2 work — it would need to consolidate `dlg_setup.py`, `dlg_wp_settings`, series fields, etc.

### 4.8 Custom Title Bar (Optional / Phase 2)

`CombinedMainWindow` would need `Qt.WindowType.FramelessWindowHint`. High risk — window dragging, resize, tray icon, compositor hints all need manual wiring. Defer unless explicitly prioritized.

---

## 5. File Changes

```
translation_assistant/
├── resources/
│   ├── fonts/                    ← NEW: font TTF files (see §1.2)
│   │   ├── NotoSansJP-Regular.ttf
│   │   ├── Inter-Regular.ttf
│   │   ├── Inter-Medium.ttf
│   │   ├── Inter-SemiBold.ttf
│   │   └── IBMPlexMono-SemiBold.ttf
│   └── style.qss                 ← NEW: global stylesheet
├── main.py                       ← ADD: font loading + setStyleSheet
└── ui/
    ├── main_widget.py            ← MODIFY: setObjectName on text widgets + labels
    └── combined_window.py        ← MODIFY: optional toolbar
```

No new Python widget classes required for Phase 1. QSS does the heavy lifting.

---

## 6. Implementation Order

1. **QSS file** — write `style.qss` with all tokens. Load in `main.py`. Observe baseline.
2. **Object names** — add `setObjectName(…)` to `_raw_line`, `_translated_line`, `_review_top`, `_review_bottom`, and panel labels. Remove inline `setStyleSheet` calls on those labels.
3. **Font loading** — add font TTF files, load in `main.py`.
4. **Splitter handle** — style via QSS.
5. **Toolbar** (optional) — add slim action toolbar in `CombinedMainWindow`.
6. **Dialog polish** — verify all dialogs look correct under global QSS; fix any overrides.
7. **Status bar dot colors** — add object-name state styling if desired.
8. **Title bar** (Phase 2, optional) — frameless window + drag logic.
9. **Settings sidebar dialog** (Phase 2) — consolidate settings dialogs.

---

## 7. Out of Scope (from original doc, main widget only)

- "Translate →" button in main widget — wrong app model (human translation workbench)
- WP button inline in translation panel — use toolbar/menu instead
- `ui/main_window.py` changes — legacy file, do not touch

---

## 8. AggregatorWidget Redesign (`ta/ui/`)

The redesign doc's Engine Bar and Language Swap Bar **do** apply — they map to the Aggregator's actual widget tree:

```
AggregatorWidget (QVBoxLayout)
├── SourcePanel                      ← Language Swap Bar + source input
│   ├── toolbar: [▶▶ Translate All] [src_combo] [dst_combo] [Clipboard] [◀ Hist] [Hist ▶]
│   └── QTextEdit (source input, max 120px)
├── TranslationPanel (Ollama)        ← Engine Bar pattern (one per engine)
│   ├── title bar: [☑ Ollama] ... [status ✓/✗/…] [▶]
│   └── QTextEdit (output, read-only)
└── PanelsContainer                  ← 2-column horizontal splitter of TranslationPanels
    ├── col0 (vertical): [TranslationPanel, …]
    └── col1 (vertical): [TranslationPanel, …]
```

### 8.1 SourcePanel — Language Bar

**Current:** `[▶▶ Translate All]  [src_combo]  [dst_combo]  [Clipboard ✓]  [◀ Hist]  [Hist ▶]`

**Target:** Restyle toolbar. Add `⇄` swap button between combos (pill aesthetic from doc §4.3).

Changes in `ta/ui/source_panel.py`:
- `_translate_btn` → `setObjectName("TranslateAllBtn")` — accent style
- `_src_combo` → `setObjectName("LangSource")`
- `_dst_combo` → `setObjectName("LangTarget")`
- Add `QPushButton("⇄")` between combos, `setObjectName("LangSwap")`, wire to swap combo selections
- `_clipboard_cb` → no structural change, just inherits dark checkbox QSS
- History buttons → ghost style

```css
QPushButton#TranslateAllBtn {
    background: #5C6BFF;
    border: none;
    border-radius: 8px;
    color: #FFFFFF;
    font-weight: 600;
    padding: 6px 14px;
}
QPushButton#TranslateAllBtn:hover { background: #7380FF; }
QPushButton#TranslateAllBtn:disabled { background: #2E3350; color: #8B8FA8; }

QPushButton#LangSwap {
    background: #23263A;
    border: 1px solid #2E3350;
    border-radius: 16px;
    color: #5C6BFF;
    font-size: 14px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}
QPushButton#LangSwap:hover { background: #3D4AB3; color: #E8E6F0; }
```

Swap logic (add to `SourcePanel`):
```python
def _on_swap(self) -> None:
    src_idx = self._src_combo.currentIndex()
    dst_idx = self._dst_combo.currentIndex()
    self._src_combo.setCurrentIndex(dst_idx)
    self._dst_combo.setCurrentIndex(src_idx)
```

### 8.2 SourcePanel — Source Text Input

- `_text_edit` → `setObjectName("AggSourceText")`

```css
QTextEdit#AggSourceText {
    background: #1A1D27;
    color: #F0EDE8;
    border: 1px solid #2E3350;
    border-radius: 8px;
    font-family: 'Noto Sans JP';
    font-size: 15px;
    padding: 8px;
}
QTextEdit#AggSourceText:focus { border-color: #5C6BFF; }
```

### 8.3 TranslationPanel — Engine Bar

Each `TranslationPanel` title bar maps to the doc's "Engine Bar" concept.

**Current:** `[☑ engine_name] ... [status label] [▶]`

**Target:** Keep structure, restyle components.

Changes in `ta/ui/translation_panel.py`:
- `_enable_cb` → `setObjectName("EngineCheckbox")`
- `_status_label` → `setObjectName("EngineStatus")` + set `state` property for dot coloring
- `_translate_btn` → `setObjectName("EngineRunBtn")`
- `_output` → `setObjectName("AggTranslationText")`

```css
QCheckBox#EngineCheckbox {
    font-family: 'Inter';
    font-size: 12px;
    font-weight: 500;
    color: #E8E6F0;
    spacing: 6px;
}
QCheckBox#EngineCheckbox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #2E3350;
    border-radius: 3px;
    background: #23263A;
}
QCheckBox#EngineCheckbox::indicator:checked {
    background: #5C6BFF;
    border-color: #5C6BFF;
}

QLabel#EngineStatus[state="ok"]      { color: #3ECF8E; font-size: 13px; }
QLabel#EngineStatus[state="working"] { color: #F5A623; font-size: 13px; }
QLabel#EngineStatus[state="error"]   { color: #FF5E5E; font-size: 13px; }
QLabel#EngineStatus[state="idle"]    { color: #8B8FA8; font-size: 13px; }

QPushButton#EngineRunBtn {
    background: #23263A;
    border: 1px solid #2E3350;
    border-radius: 6px;
    color: #5C6BFF;
    font-size: 12px;
    min-width: 28px; max-width: 28px;
    min-height: 24px; max-height: 24px;
}
QPushButton#EngineRunBtn:hover { background: #3D4AB3; color: #E8E6F0; }

QTextEdit#AggTranslationText {
    background: #161929;
    color: #EAF0FF;
    border: none;
    font-family: 'Noto Sans JP';
    font-size: 15px;
    padding: 8px;
}
```

Update `_on_started` / `_on_ready` / `_on_error` in `TranslationPanel` to set the `state` property and call `style().unpolish/polish` to trigger QSS re-evaluation:

```python
def _set_status(self, state: str, text: str) -> None:
    self._status_label.setText(text)
    self._status_label.setProperty("state", state)
    self._status_label.style().unpolish(self._status_label)
    self._status_label.style().polish(self._status_label)
```

### 8.4 PanelsContainer — Splitter

```css
/* Already covered by global QSplitter::handle rule */
```

No code change needed.

### 8.5 File Changes (Aggregator)

```
ta/ui/
├── source_panel.py       ← ADD: swap button + setObjectName calls
└── translation_panel.py  ← ADD: setObjectName calls + _set_status helper
```

All QSS goes into the shared `translation_assistant/resources/style.qss` — global stylesheet covers `ta/ui/` widgets too since it's applied at `QApplication` level.

### 8.6 Implementation Order (Aggregator additions)

Insert after §6 step 2:

- 2a. `ta/ui/translation_panel.py` — `setObjectName` + `_set_status` helper
- 2b. `ta/ui/source_panel.py` — `setObjectName` + swap button wiring

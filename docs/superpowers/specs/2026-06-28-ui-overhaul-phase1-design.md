# UI Overhaul Phase 1 Design

**Date:** 2026-06-28
**Status:** Approved
**Source:** `docs/superpowers/ui-overhaul.md` — Phase 1 items only

---

## Scope

Phase 1 delivers:

- New 2D workspace layout (unified TA + Aggregator)
- Card-based panels
- Larger JP source text
- Larger translation editor prominence via default sizing
- Improved spacing
- Typography improvements

Explicitly out of Phase 1:

- Toolbar widget (deferred to Phase 2)
- Collapsible panels (Phase 3)
- Tabbed dictionary, conversation-style context, icon integration (Phase 2+)

---

## Architecture Decision

**CombinedMainWindow as layout orchestrator (Approach 2).**

`TranslationAssistantWidget` exposes its panels as public properties and acts as a pure logic controller — no layout of its own. `CombinedMainWindow` assembles the full 2D layout using panels from both TA widget and `AggregatorWidget`.

This replaces:
- The vertical `QSplitter` inside `TranslationAssistantWidget`
- The horizontal `QSplitter` in `CombinedMainWindow` (old TA/Aggregator side-by-side)

---

## Layout Architecture

New nested splitter structure, set as `CombinedMainWindow`'s central widget:

```
outer_splitter  (QSplitter — Vertical)
├── mid_splitter  (QSplitter — Horizontal)        stretch=3
│   ├── left_splitter  (QSplitter — Vertical)     stretch=2
│   │   ├── context_above_panel                   stretch=2
│   │   └── source_panel                          stretch=1
│   └── right_splitter  (QSplitter — Vertical)    stretch=1
│       ├── AggregatorWidget                      stretch=2
│       └── tm_panel                              stretch=1
├── translation_panel                             stretch=2
└── context_below_panel                           stretch=1
```

**Collapsible:** `setChildrenCollapsible(False)` on all splitters. Panels always visible; Phase 3 adds explicit collapse buttons.

**Default sizes (pixels):**

| Splitter | Sizes |
|---|---|
| outer | `[500, 200, 100]` |
| mid | `[500, 400]` |
| left | `[300, 120]` |
| right | `[300, 150]` |

**Status bar:** `CombinedMainWindow` adopts the TA widget's existing `QStatusBar` via `self.setStatusBar(ta.status_bar)`. No separate layout entry needed.

---

## TranslationAssistantWidget Changes

### Panel exposure

`_setup_central_widget()` creates all panels as before but stores them as named attributes instead of adding them to `self._splitter`. The method no longer creates a splitter or sets a `QVBoxLayout` on `self`.

Six new public properties:

```python
@property
def context_above_panel(self) -> QWidget: return self._panel_ctx_above

@property
def source_panel(self) -> QWidget: return self._panel_source

@property
def tm_panel(self) -> QWidget: return self._panel_tm

@property
def translation_panel(self) -> QWidget: return self._panel_translation

@property
def context_below_panel(self) -> QWidget: return self._panel_ctx_below

@property
def status_bar(self) -> QStatusBar: return self._status_bar
```

Each panel is the labeled wrapper widget (`QFrame` — see Cards section).

### Object lifetime

`TranslationAssistantWidget` is instantiated as a child of `CombinedMainWindow` but not added to any layout. Qt's object tree keeps it alive. All signal connections, event filters, timers, and actions remain on `self` and are unaffected by the layout change — the widgets they reference are still owned by `self` as Qt children (even after reparenting into splitters).

### Splitter state

`closeEvent` in `TranslationAssistantWidget` no longer saves splitter state. That responsibility moves to `CombinedMainWindow`.

---

## CombinedMainWindow Changes

### Layout construction

Replaces the old `QSplitter(Horizontal)` + `setCentralWidget` pattern with:

```python
def _build_workspace(self) -> QSplitter:
    left = QSplitter(Qt.Orientation.Vertical)
    left.setChildrenCollapsible(False)
    left.addWidget(ta.context_above_panel)
    left.addWidget(ta.source_panel)
    left.setStretchFactor(0, 2)
    left.setStretchFactor(1, 1)

    right = QSplitter(Qt.Orientation.Vertical)
    right.setChildrenCollapsible(False)
    right.addWidget(self._agg_widget)
    right.addWidget(ta.tm_panel)
    right.setStretchFactor(0, 2)
    right.setStretchFactor(1, 1)

    mid = QSplitter(Qt.Orientation.Horizontal)
    mid.setChildrenCollapsible(False)
    mid.addWidget(left)
    mid.addWidget(right)
    mid.setStretchFactor(0, 2)
    mid.setStretchFactor(1, 1)

    outer = QSplitter(Qt.Orientation.Vertical)
    outer.setChildrenCollapsible(False)
    outer.addWidget(mid)
    outer.addWidget(ta.translation_panel)
    outer.addWidget(ta.context_below_panel)
    outer.setStretchFactor(0, 3)
    outer.setStretchFactor(1, 2)
    outer.setStretchFactor(2, 1)
    return outer
```

### Splitter state persistence

`_restore_splitter()` extended to restore all 4 splitters. `closeEvent` saves all 4.

---

## Settings Changes (`settings.py`)

Four new property pairs added to `AppSettings`, identical pattern to existing `splitter_state`:

| Property | QSettings key | Default |
|---|---|---|
| `splitter_state_outer` | `SplitterStateOuter` | `QByteArray()` |
| `splitter_state_mid` | `SplitterStateMid` | `QByteArray()` |
| `splitter_state_left` | `SplitterStateLeft` | `QByteArray()` |
| `splitter_state_right` | `SplitterStateRight` | `QByteArray()` |

Old `splitter_state` / `SplitterState` key remains intact — existing tests pass, app stops reading/writing it. State resets once on first launch after upgrade (acceptable).

---

## Card Styling

`_labeled()` in `TranslationAssistantWidget` returns `QFrame` instead of `QWidget`. Each frame gets `objectName("Card")`.

QSS addition to `style.qss`:

```css
QFrame#Card {
    background: #1A1D27;
    border: 1px solid #2E3350;
    border-radius: 8px;
    padding: 4px;
}
```

PanelLabel stays as card header. Content widget inside the card body, below the label.

---

## Typography + Spacing

### Font size changes in `style.qss`

| Rule | Old | New |
|---|---|---|
| `QWidget` base | 12px | 13px |
| `QLabel#PanelLabel` | 10px | 11px |
| `QTextEdit#SourceText` | 16px | 20px |
| All others | unchanged | unchanged |

### Spacing changes in `_setup_central_widget`

| Setting | Old | New |
|---|---|---|
| `QVBoxLayout` margins | `(5,5,5,0)` | `(12,12,12,0)` |
| Layout spacing | `0` | `8` |

Splitter handle width: set to `6` on all 4 splitters for comfortable dragging.

---

## Files Touched

| File | Change |
|---|---|
| `translation_assistant/ui/main_widget.py` | Remove splitter; store panels; add 6 properties; remove closeEvent splitter save |
| `translation_assistant/ui/combined_window.py` | Build 2D layout; adopt status bar; save/restore 4 splitter states |
| `translation_assistant/settings.py` | Add 4 new splitter state property pairs |
| `translation_assistant/resources/style.qss` | Card rule; font size bumps; no structural changes |

---

## Success Criteria

- App launches with the new 2D layout
- All 4 splitters are independently resizable
- Splitter positions persist across restarts
- JP source text visually dominant (20px vs 13px base)
- Panels render as cards (rounded corners, thin border, slightly lighter background)
- All existing tests pass unchanged
- No regression in TA widget functionality (navigation, translation, clipboard, WP publish, etc.)

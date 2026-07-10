# Card-List Editor Redesign

**Date:** 2026-07-10
**Source design:** claude.ai/design project `ebb91e1a-2cc6-4606-a63b-0d18b4f5936b`, file `Translation Editor.dc.html`

## Overview

Replace the one-line-at-a-time editing model (Context Above / Source / Translation /
Context Below panes) with a scrollable card list showing the whole chapter: one card
per line, each displaying source text and translation, editable in place. Apply the
design's dark theme app-wide.

Decisions made during brainstorming:

- **Editing model:** full card list (design's model), not a re-skin of the pane layout.
- **MT panel:** keep the existing `AggregatorWidget` embedded, restyled dark. No
  per-engine Insert panel.
- **Navigation rail:** none. Menu bar stays as-is.
- **Top toolbar:** none. Bottom status bar keeps its current content, dark-themed.
- **Theme:** dark, app-wide (menus, dialogs, status bar, aggregator, cards).
- **Scale target:** chapters of 300–1000 lines must load and scroll acceptably.
- **Implementation approach:** shared moving editor (approach A) — lightweight cards,
  one real `QTextEdit` that re-parents into the active card.

## Goals

- Whole chapter visible and editable as a card list.
- Preserve every existing feature and keyboard workflow (see Feature migrations).
- Dark theme per design's palette across the whole app.
- No changes to `core.py`, `db.py`, storage format, or any dialog's behavior.

## Non-goals (out of scope)

- Icon navigation rail.
- Top toolbar (breadcrumb, go-to-line box, autosave countdown, always-on-top toggle
  widget — the menu actions for these stay).
- Per-engine MT suggestion panel with Insert buttons.
- Light theme / following the OS theme.
- Virtualized rendering (revisit only if 1000-line load is measurably slow; see Risks).

## Layout

```
┌─ Menu bar (unchanged) ────────────────────────────────┐
│ ┌─ Card list (QScrollArea) ──────┬─ Right column ───┐ │
│ │  ┌ LineCard ┐                  │  AggregatorWidget│ │
│ │  ┌ LineCard ┐  ← active        │  ──────────────  │ │
│ │  ┌ LineCard ┐                  │  TM Matches      │ │
│ └────────────────────────────────┴──────────────────┘ │
└─ Status bar (current content, dark-themed) ───────────┘
```

`CombinedMainWindow._build_workspace()` simplifies to one horizontal splitter:

- **Left:** `CardListView` (new widget).
- **Right:** vertical splitter — `AggregatorWidget` over the TM matches panel
  (collapsible, as today).

The four current splitters (`outer`, `mid`, `left`, `right`) reduce to two
(`main` horizontal, `right` vertical). Old splitter QSettings keys are ignored;
new keys `combined/splitter_main`, `combined/splitter_right2` store the new state.

## New component: `ui/card_list.py`

### `LineCard(QFrame)`

One card per document line. Contents, top to bottom:

1. **Header row:** line number (1-based), status dot, status label, and a transient
   "Copied source to clipboard" pill (right-aligned, auto-hides after ~1.6 s).
2. **Source block:** `SOURCE · JA` micro-label, then the source text — read-only,
   word-wrapped, serif, glossary terms highlighted amber (see Feature migrations).
   Implemented as a `QLabel` with rich text (`setWordWrap(True)`, `setTextFormat(RichText)`);
   wraps and sizes to content, no inner scrollbar. Phrase-parse highlighting rewrites
   the label's rich text with a highlighted span.
3. **Translation block:** `TRANSLATION · EN` micro-label, then the translation area.

Card states (visuals per design):

| State        | Border                  | Background     | Dot                  | Label         |
|--------------|-------------------------|----------------|----------------------|---------------|
| Active       | 1.5 px solid accent     | slightly green | accent, pulsing      | "In progress" |
| Translated   | 1 px solid border-gray  | panel          | accent, static       | "Translated"  |
| Not started  | 1 px dashed border-gray | dimmer         | gray, static         | "Not started" |

"Translated" = non-empty translation and not active. Status pulse uses a `QTimer`
driven opacity animation on the dot (or `QPropertyAnimation`); one timer shared by
the view, only the active card animates.

Clicking anywhere in a card activates it.

### `CardListView(QScrollArea)`

- `load_lines(lines)` builds all cards on document load. Cards are lightweight:
  labels only, no editors, no per-card highlighters.
- Tracks `active_index`; exposes `set_active(index)`, `active_line_changed(int)` signal.
- On activation: moves the shared editor into the card, scrolls the card into view
  (`ensureWidgetVisible` with margin), updates previous card's state.
- `update_line(index, text)` / `line_edited(int, str)` signal for text changes.
- API for existing features: `jump_to(index)`, `next_untranslated()`, font-size
  propagation, per-card source phrase highlighting.

### Shared moving editor

One `QTextEdit` instance owned by `CardListView`:

- The existing `SpellHighlighter` attaches to its document — one highlighter total.
- Inactive cards render translation as a wrapped label (or placeholder styling when
  empty: "Type your translation…" muted text).
- On card activation: editor re-parents into the card's translation block, label
  hides, editor takes focus and receives the line's text. On deactivation: text is
  committed to the in-memory line and the label, editor detaches.
- Clicking an inactive card's translation label activates the card; caret placement
  at click position is best-effort (end-of-text acceptable for v1).
- The editor keeps the current custom context menu (dictionary suggestions) and
  `textChanged` → dirty wiring.

## Interaction and keyboard (parity with current behavior)

All routed through the existing `_handle_key` event filter, now installed on the
shared editor and the card list:

- **Enter / PgDn** — commit and activate next line. **PgUp** — previous line.
  **Shift+Enter** — literal newline in the translation.
- **Ctrl+↓ / Ctrl+↑** — next / previous line (new, from design).
- **Ctrl+← / Ctrl+→** — phrase parse steps within the active card's source
  (see Feature migrations).
- **Ctrl+G** — go-to-line dialog (unchanged) → `jump_to(index)`.
- **Jump to next untranslated** (existing action) → `next_untranslated()`.
- **Ctrl+= / Ctrl+-** — font size: resizes source and translation text in all cards
  (source serif and editor font track `settings.font_size` as today).
- **Jump to first line** (`_jump_to_first`) and other menu navigation actions keep
  working via the same slots, re-pointed at `CardListView`.

Active-line change side effects (existing wiring, re-pointed):

1. Restart the 400 ms clipboard debounce timer; on fire, copy the active line's
   source to the clipboard and show the card's "Copied" pill.
2. Emit `source_sentence_changed` → aggregator translates the new source.
3. Update the TM matches panel for the new source.
4. Update status bar progress / line labels.

Autosave, dirty tracking, and `_save_to_db` are unchanged: edits mutate the
in-memory lines list; the autosave timer and manual save persist as today.

## Feature migrations

- **Phrase parse navigation (Ctrl+←/→):** operates on the active card. The current
  phrase is highlighted inside the card's source text (selection or background span)
  and copied to the clipboard, replacing the old `_highlight_parse_sentence` on the
  source pane. Parse position resets on line change (current behavior).
- **TM matches panel:** unchanged widget, lives under the aggregator in the right
  column; clicking a match inserts into the shared editor.
- **Glossary term highlighting:** source text in every card highlights glossary
  terms amber. `JpSyntaxHighlighter` currently attaches to one document; for cards,
  highlighting is applied at card-build time by generating rich text spans from the
  same glossary matching logic (cheap, static — source is read-only). Re-applied on
  glossary/profile change.
- **Spellcheck:** active card only — the single `SpellHighlighter` on the shared
  editor. Inactive translations are not spellchecked.
- **Review colors** (`_apply_review_colors` on context panes): replaced by card
  status visuals. The setting/actions tied to context-pane colors are removed.
- **Double-click-to-edit context lines:** obsolete — every card is directly editable.

## Removals from `main_widget.py`

- `_review_top`, `_review_bottom`, `_raw_line`, `_translated_line` panes and their
  `_labeled()` card wrappers, collapse persistence for `ctx_above`/`ctx_below`.
- `ReviewTextEdit` class, `_on_review_top_double_click`, `_on_review_bottom_double_click`,
  `_apply_review_colors`, `_update_ui_for_pointer`'s pane-fill logic (rewired to
  `CardListView.set_active`).
- Exposed panel properties consumed by `combined_window.py`
  (`context_above_panel`, `source_panel`, `translation_panel`) are replaced by a
  single `card_view` property; `tm_panel` stays.

Everything else in `main_widget.py` (actions, dialogs, import/export, WP publish,
scraper, stats) is untouched.

## Theme: `ui/theme.py`

- `apply_dark_theme(app)` sets a global QSS stylesheet + `QPalette`, called from
  `main.py` after `QApplication` creation.
- Palette (hex approximations of the design's oklch values — tune visually):
  - Window/root background `#191b19`; panel `#222522`; card active bg `#232a24`;
    untranslated card bg `#1d201d`; editor field bg `#2a2f2a`.
  - Borders `#3a3e3a` (panels) / `#454a45` (inputs).
  - Accent green `#4fc47f` (active borders, dots, progress bar, selection, focus).
  - Text `#ecefec`; secondary `#a3a8a3`; muted `#6f746f`.
  - Glossary highlight: amber text `#e6c46a` on `#453a22`.
- Fonts: UI font family chain `Inter, "Noto Sans", sans-serif`; source/translation
  text `"Source Serif 4", "Noto Serif CJK JP", serif` merged with the existing
  `_CJK_FAMILIES` chain so CJK glyphs render correctly. No font bundling — system
  fallbacks only.
- QSS covers: `QMenuBar`, `QMenu`, `QStatusBar`, `QDialog`, `QPushButton`,
  `QLineEdit`, `QComboBox`, `QScrollBar`, `QSplitter`, `QToolTip`, aggregator
  widgets, and the card object names (`LineCard[state="active"]` etc. via dynamic
  properties).
- Card state styling uses Qt dynamic properties (`card.setProperty("state", "active")`
  + style repolish) so QSS drives the visuals.

## File changes

| File | Change |
|------|--------|
| `translation_assistant/ui/card_list.py` | **New** — `LineCard`, `CardListView`, shared editor. |
| `translation_assistant/ui/theme.py` | **New** — dark palette + QSS. |
| `translation_assistant/main.py` | Call `apply_dark_theme(app)`. |
| `translation_assistant/ui/main_widget.py` | Panes removed, card view wired in, navigation/parse/clipboard/TM slots re-pointed. |
| `translation_assistant/ui/combined_window.py` | Splitters simplified, new panel properties. |
| `tests/test_card_list.py` | **New** — card list behavior. |
| `tests/test_main_window.py`, `tests/test_combined_window.py`, `tests/test_integration.py` | Rewritten where they touch removed panes. |

## Testing

New `tests/test_card_list.py` (offscreen Qt, existing `qapp` fixture):

- `load_lines` builds N cards; states reflect translation emptiness.
- Activating a card moves the shared editor, commits previous text, emits
  `active_line_changed`.
- Enter advances, PgUp goes back, Shift+Enter inserts newline, bounds respected.
- Editing marks dirty and updates the in-memory line.
- `next_untranslated`, `jump_to`, font-size propagation.
- Glossary highlight spans present in card source rich text.

Existing suite: tests referencing removed panes (`_review_top`, `_raw_line`,
`_translated_line`, review colors, double-click editing) are rewritten against the
card list; core/db/settings/dialog/scraper tests (majority of the 535) unaffected.

## Risks

- **1000-line load time:** building ~1000 cards with rich-text source labels may be
  slow. Mitigation order: (1) measure with a generated 1000-line doc; (2) chunked
  build via a zero-interval timer (build 100 cards per tick, UI stays responsive);
  (3) only then consider virtualization. Do not pre-build virtualization.
- **QSS regressions in dialogs:** global stylesheet can break dialog layouts;
  verify each dialog opens legibly under the theme (manual pass + existing dialog
  tests catch crashes, not looks).
- **Shared-editor focus churn:** re-parenting must not steal focus during programmatic
  updates (e.g. autosave, TM insert); guard with an updating flag as done today for
  `textChanged`.

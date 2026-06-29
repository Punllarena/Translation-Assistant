# UI Overhaul Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 3 of the UI modernisation: collapsible context panels, Japanese syntax colouring on the source text, and word-click MeCab tooltips.

**Source spec:** `docs/superpowers/ui-overhaul.md` — Phase 3 items: collapsible panels, word highlighting, syntax colouring. Theme customisation deferred (CSS-only work, no logic; can be done independently at any time). Animations deferred (no functional value).

**Architecture:** All three tasks touch at most two files each. Tasks 2 and 3 share a new helper module `translation_assistant/jp_highlighter.py` — Task 3 depends on Task 2.

**Tech Stack:** PySide6, pytest, MeCab/fugashi (already in venv, optional — features degrade gracefully when unavailable)

## Global Constraints

- All existing tests must pass after each task
- Activate venv before running any command: `source .venv/bin/activate`
- Run tests with: `pytest tests/ -q`
- No new pip dependencies
- Do not touch `translation_assistant/ui/main_window.py` (legacy — not launched)
- Features that depend on MeCab must degrade silently when MeCab is unavailable

---

## Task Overview

| # | Task | Files |
|---|------|-------|
| 1 | Collapsible context panels | `translation_assistant/ui/main_widget.py` |
| 2 | JP syntax highlighter | `translation_assistant/jp_highlighter.py` (new), `translation_assistant/ui/main_widget.py` |
| 3 | Word-click MeCab tooltip | `translation_assistant/jp_highlighter.py`, `translation_assistant/ui/main_widget.py` |

---

### Task 1: Collapsible context panels

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Test: `tests/test_main_window.py`

**What this task does:**

Makes `_panel_ctx_above` and `_panel_ctx_below` collapsible. Clicking the panel's `PanelLabel` toggles the inner widget's visibility and updates the chevron prefix (`▼` expanded, `▶` collapsed). Collapsed state is persisted per-panel in QSettings at `panels/ctx_above_collapsed` and `panels/ctx_below_collapsed`.

The existing `_labeled()` nested function is extended with an optional `collapse_key` parameter. Only the two context panels pass this key; all other panels behave exactly as before. The TM panel's existing toggle logic (`_ClickableLabel` + `action_tm`) is unaffected.

**Interfaces:**
- Consumes: `_ClickableLabel` (already defined at line 140 of `main_widget.py`), `self._settings._qs` (QSettings instance)
- Produces: `_panel_ctx_above` and `_panel_ctx_below` panels that toggle their inner widget's visibility on label click

- [ ] **Step 1: Write failing tests**

Add to `tests/test_main_window.py` at end of `TestInstantiation`:

```python
def test_ctx_above_label_has_expand_chevron(self, win, qapp):
    """Context Above label starts with ▼ (expanded by default)."""
    from PySide6.QtWidgets import QLabel
    labels = win._panel_ctx_above.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    assert any(t.startswith("▼") for t in texts)

def test_ctx_below_label_has_expand_chevron(self, win, qapp):
    """Context Below label starts with ▼ (expanded by default)."""
    from PySide6.QtWidgets import QLabel
    labels = win._panel_ctx_below.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    assert any(t.startswith("▼") for t in texts)

def test_ctx_above_inner_visible_by_default(self, win):
    assert win._review_top.isVisible()

def test_ctx_below_inner_visible_by_default(self, win):
    assert win._review_bottom.isVisible()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestInstantiation::test_ctx_above_label_has_expand_chevron tests/test_main_window.py::TestInstantiation::test_ctx_below_label_has_expand_chevron -q
```

Expected: 2 tests FAIL (labels have no `▼` prefix yet).

- [ ] **Step 3: Modify `_labeled()` in `_setup_central_widget`**

In `translation_assistant/ui/main_widget.py`, find the `_labeled` nested function inside `_setup_central_widget` (around line 397):

```python
        def _labeled(title, inner: QWidget) -> QFrame:
            w = QFrame()
            w.setObjectName("Card")
            vbox = QVBoxLayout(w)
            vbox.setContentsMargins(8, 8, 8, 8)
            vbox.setSpacing(4)
            if isinstance(title, str):
                lbl = QLabel(title)
                lbl.setObjectName("PanelLabel")
            else:
                lbl = title  # already a QLabel/ClickableLabel
            vbox.addWidget(lbl)
            vbox.addWidget(inner)
            return w
```

Replace with:

```python
        def _labeled(title, inner: QWidget, *, collapse_key: str = "") -> QFrame:
            w = QFrame()
            w.setObjectName("Card")
            vbox = QVBoxLayout(w)
            vbox.setContentsMargins(8, 8, 8, 8)
            vbox.setSpacing(4)
            if isinstance(title, str):
                if collapse_key:
                    lbl = _ClickableLabel(f"▼ {title}")
                else:
                    lbl = QLabel(title)
                lbl.setObjectName("PanelLabel")
            else:
                lbl = title
            vbox.addWidget(lbl)
            vbox.addWidget(inner)

            if collapse_key and isinstance(title, str):
                collapsed = self._settings._qs.value(
                    f"panels/{collapse_key}_collapsed", False, type=bool
                )
                if collapsed:
                    inner.setVisible(False)
                    lbl.setText(f"▶ {title}")

                def _toggle(_t=title, _l=lbl, _i=inner, _k=collapse_key):
                    vis = not _i.isVisible()
                    _i.setVisible(vis)
                    _l.setText(f"{'▼' if vis else '▶'} {_t}")
                    self._settings._qs.setValue(f"panels/{_k}_collapsed", not vis)

                lbl.clicked.connect(_toggle)

            return w
```

- [ ] **Step 4: Update the two context panel `_labeled()` calls**

Find (around line 425):

```python
        self._panel_ctx_above = _labeled("Context (Above)", self._review_top)
```

Replace with:

```python
        self._panel_ctx_above = _labeled("Context (Above)", self._review_top, collapse_key="ctx_above")
```

Find (around line 473):

```python
        self._panel_ctx_below = _labeled("Context (Below)", self._review_bottom)
```

Replace with:

```python
        self._panel_ctx_below = _labeled("Context (Below)", self._review_bottom, collapse_key="ctx_below")
```

- [ ] **Step 5: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass including the 4 new ones.

- [ ] **Step 6: Run the app and verify**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Verify:
- Context Above and Context Below labels show `▼` prefix
- Clicking the label hides the inner widget and changes to `▶`
- Clicking again restores
- Close and reopen the app — collapsed state is remembered

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(panels): collapsible context panels with persisted state"
```

---

### Task 2: JP syntax highlighter

**Files:**
- Create: `translation_assistant/jp_highlighter.py`
- Modify: `translation_assistant/ui/main_widget.py`
- Test: `tests/test_jp_highlighter.py` (new)

**What this task does:**

Adds `JpSyntaxHighlighter`, a `QSyntaxHighlighter` subclass that colours Japanese tokens in the source text by MeCab POS tag. Silently does nothing when MeCab/fugashi is unavailable. Attached to `self._raw_line.document()` in `_setup_central_widget`. Re-runs automatically whenever the source text changes (Qt behaviour).

Colour scheme (Dracula-adjacent, consistent with existing MeCab panel colours):
- 名詞 (noun) → `#FFB86C` (amber)
- 動詞 (verb) → `#8BE9FD` (cyan)
- 形容詞 (adjective) → `#50FA7B` (green)
- 助詞 (particle) → `#6272A4` (muted blue-grey)
- 助動詞 (aux verb) → `#BD93F9` (purple)

Also exposes `token_info_at(text, char_pos) -> str` for Task 3's tooltip feature.

**Interfaces:**
- Produces: `JpSyntaxHighlighter(document: QTextDocument)` class with `token_info_at(text: str, char_pos: int) -> str` method
- Consumed by: `main_widget.py` — stored as `self._jp_highlighter`; `token_info_at` called in Task 3's click handler

- [ ] **Step 1: Write failing tests**

Create `tests/test_jp_highlighter.py`:

```python
import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def highlighter(qapp):
    from PySide6.QtGui import QTextDocument
    from translation_assistant.jp_highlighter import JpSyntaxHighlighter
    doc = QTextDocument()
    h = JpSyntaxHighlighter(doc)
    return h


def _make_fugashi_word(surface, pos1="名詞", kana="", lemma=""):
    from unittest.mock import MagicMock
    w = MagicMock()
    w.surface = surface
    w.feature.pos1 = pos1
    w.feature.kana = kana
    w.feature.lemma = lemma
    w.feature.pron = ""
    return w


def test_token_info_at_no_tagger(highlighter):
    """Returns empty string when no tagger available."""
    highlighter._tagger = None
    assert highlighter.token_info_at("語彙", 0) == ""


def test_token_info_at_returns_surface(highlighter):
    """Surface form always appears in tooltip text."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("語彙", pos1="名詞", kana="ゴイ", lemma="語彙")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    result = highlighter.token_info_at("語彙", 0)
    assert "語彙" in result


def test_token_info_at_includes_pos(highlighter):
    """POS tag appears in tooltip text."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("走る", pos1="動詞", kana="ハシル", lemma="走る")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    result = highlighter.token_info_at("走る", 0)
    assert "動詞" in result


def test_token_info_at_includes_reading(highlighter):
    """Kana reading appears when different from surface."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("語彙", pos1="名詞", kana="ゴイ", lemma="語彙")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    result = highlighter.token_info_at("語彙", 0)
    assert "ゴイ" in result


def test_token_info_at_char_pos_selects_correct_token(highlighter):
    """char_pos selects the token that spans that position."""
    from unittest.mock import MagicMock
    words = [
        _make_fugashi_word("語彙", pos1="名詞", kana="ゴイ"),   # pos 0–1
        _make_fugashi_word("が", pos1="助詞", kana="ガ"),         # pos 2
    ]
    highlighter._tagger = MagicMock(return_value=words)
    highlighter._use_fugashi = True
    result_noun = highlighter.token_info_at("語彙が", 0)
    result_particle = highlighter.token_info_at("語彙が", 2)
    assert "名詞" in result_noun
    assert "助詞" in result_particle


def test_token_info_at_out_of_range(highlighter):
    """Returns empty string for char_pos beyond all tokens."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("語彙")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    assert highlighter.token_info_at("語彙", 99) == ""


def test_instantiation_does_not_raise(qapp):
    """JpSyntaxHighlighter instantiates without error even if MeCab absent."""
    from PySide6.QtGui import QTextDocument
    from translation_assistant.jp_highlighter import JpSyntaxHighlighter
    doc = QTextDocument()
    h = JpSyntaxHighlighter(doc)  # must not raise
    assert h is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_jp_highlighter.py -q
```

Expected: all 7 tests fail with `ModuleNotFoundError: No module named 'translation_assistant.jp_highlighter'`.

- [ ] **Step 3: Create `translation_assistant/jp_highlighter.py`**

```python
from __future__ import annotations

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

_POS_COLORS: dict[str, str] = {
    "名詞": "#FFB86C",
    "動詞": "#8BE9FD",
    "形容詞": "#50FA7B",
    "助詞": "#6272A4",
    "助動詞": "#BD93F9",
}


class JpSyntaxHighlighter(QSyntaxHighlighter):
    """Colours Japanese tokens by MeCab POS tag. Silent no-op if MeCab absent."""

    def __init__(self, document):
        super().__init__(document)
        self._tagger = None
        self._use_fugashi = False
        self._fmts: dict[str, QTextCharFormat] = {}
        for pos_tag, color in _POS_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._fmts[pos_tag] = fmt
        self._init_tagger()

    def _init_tagger(self) -> None:
        try:
            import fugashi
            self._tagger = fugashi.Tagger()
            self._use_fugashi = True
            return
        except Exception:
            pass
        try:
            import MeCab  # type: ignore
            self._tagger = MeCab.Tagger()
        except Exception:
            pass

    def highlightBlock(self, text: str) -> None:
        if not self._tagger or not text.strip():
            return
        try:
            pos = 0
            if self._use_fugashi:
                for word in self._tagger(text):
                    surface = word.surface
                    pos_tag = getattr(word.feature, "pos1", "") or ""
                    fmt = self._fmts.get(pos_tag)
                    if fmt:
                        self.setFormat(pos, len(surface), fmt)
                    pos += len(surface)
            else:
                for line in self._tagger.parse(text).splitlines():
                    if line in ("EOS", ""):
                        continue
                    if "\t" in line:
                        surface, rest = line.split("\t", 1)
                        pos_tag = rest.split(",")[0] if rest else ""
                        fmt = self._fmts.get(pos_tag)
                        if fmt:
                            self.setFormat(pos, len(surface), fmt)
                        pos += len(surface)
        except Exception:
            pass

    def token_info_at(self, text: str, char_pos: int) -> str:
        """Return a one-line tooltip for the MeCab token at char_pos, or ''."""
        if not self._tagger or not text:
            return ""
        try:
            pos = 0
            if self._use_fugashi:
                for word in self._tagger(text):
                    surface = word.surface
                    end = pos + len(surface)
                    if pos <= char_pos < end:
                        f = word.feature
                        reading = getattr(f, "kana", "") or getattr(f, "pron", "") or ""
                        lemma = getattr(f, "lemma", "") or ""
                        pos_tag = getattr(f, "pos1", "") or ""
                        parts = [surface]
                        if reading and reading != surface:
                            parts.append(f"[{reading}]")
                        if lemma and lemma != surface:
                            parts.append(f"({lemma})")
                        if pos_tag:
                            parts.append(f"<{pos_tag}>")
                        return "  ".join(parts)
                    pos = end
            else:
                for line in self._tagger.parse(text).splitlines():
                    if line in ("EOS", ""):
                        continue
                    if "\t" in line:
                        surface, rest = line.split("\t", 1)
                        fields = rest.split(",")
                        end = pos + len(surface)
                        if pos <= char_pos < end:
                            pos_tag = fields[0] if fields else ""
                            reading = fields[7] if len(fields) > 7 else ""
                            base = fields[6] if len(fields) > 6 else ""
                            parts = [surface]
                            if reading and reading not in ("*", surface):
                                parts.append(f"[{reading}]")
                            if base and base not in ("*", surface):
                                parts.append(f"({base})")
                            if pos_tag:
                                parts.append(f"<{pos_tag}>")
                            return "  ".join(parts)
                        pos = end
        except Exception:
            pass
        return ""
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_jp_highlighter.py -q
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Attach highlighter to `_raw_line` in `main_widget.py`**

Add import near the top of `main_widget.py`, after the existing local imports (around line 17):

```python
from translation_assistant.jp_highlighter import JpSyntaxHighlighter
```

In `_setup_central_widget`, after the `_raw_line` block (after the line that sets `self._raw_line.setPlaceholderText(...)`, around line 433), add:

```python
        self._jp_highlighter = JpSyntaxHighlighter(self._raw_line.document())
```

- [ ] **Step 6: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 7: Run the app and verify**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Open a document with Japanese text. Navigate to a sentence. The source text panel should show:
- Nouns in amber
- Verbs in cyan
- Particles in muted blue-grey
- Adjectives in green
- Other tokens in the default colour

If MeCab is not installed, the source text renders with no colouring (no error, no crash).

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/jp_highlighter.py translation_assistant/ui/main_widget.py tests/test_jp_highlighter.py
git commit -m "feat(source): JP syntax colouring by MeCab POS tag"
```

---

### Task 3: Word-click MeCab tooltip

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Test: `tests/test_jp_highlighter.py` (existing — Task 2's tests already cover `token_info_at`)

**What this task does:**

When the user clicks a word in the read-only source text panel (`_raw_line`), a `QToolTip` appears at the cursor showing the MeCab token info: surface form, kana reading, lemma, and POS tag. The tooltip dismisses automatically when the mouse moves. Silently does nothing if MeCab is unavailable or `_jp_highlighter._tagger` is None.

The `_raw_line` widget already has an event filter installed (see `eventFilter` at line 1812). This task adds a `MouseButtonPress` branch to that filter.

**Interfaces:**
- Consumes: `self._jp_highlighter.token_info_at(text, char_pos) -> str` from Task 2
- Consumes: `self._raw_line` QTextEdit with installed event filter

No new tests beyond what Task 2 already covers for `token_info_at`. Manual verification in the app is the gate.

- [ ] **Step 1: Add `MouseButtonPress` handling in `eventFilter`**

In `translation_assistant/ui/main_widget.py`, find `eventFilter` (around line 1812):

```python
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            watched = (
                self._review_top, self._raw_line,
                self._translated_line, self._review_bottom,
            )
            if obj in watched and self._handle_key(event):
                return True
        return super().eventFilter(obj, event)
```

Replace with:

```python
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            watched = (
                self._review_top, self._raw_line,
                self._translated_line, self._review_bottom,
            )
            if obj in watched and self._handle_key(event):
                return True
        if obj is self._raw_line and event.type() == QEvent.Type.MouseButtonPress:
            self._show_source_word_tooltip(event)
        return super().eventFilter(obj, event)
```

- [ ] **Step 2: Add `_show_source_word_tooltip` method**

Add the following method after `eventFilter` (before `_handle_key`):

```python
    def _show_source_word_tooltip(self, event) -> None:
        text = self._raw_line.toPlainText()
        if not text:
            return
        cursor = self._raw_line.cursorForPosition(event.pos())
        info = self._jp_highlighter.token_info_at(text, cursor.position())
        if info:
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(
                event.globalPosition().toPoint(), info, self._raw_line
            )
```

- [ ] **Step 3: Run all tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Run the app and verify**

```bash
source .venv/bin/activate && python -m translation_assistant.main
```

Open a document. Navigate to a sentence with Japanese text. Click a word in the Source panel. A tooltip should appear showing, for example:

```
語彙  [ゴイ]  <名詞>
```

Click a particle (`が`, `は`, `を`) — tooltip shows `<助詞>`. Click a verb — `<動詞>`. Moving the mouse dismisses the tooltip. No tooltip when MeCab is absent.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py
git commit -m "feat(source): word-click MeCab tooltip on source text"
```

---

## Phase 3 Complete

After all 3 tasks:

- Context Above and Context Below panels collapse on label click; state persists across sessions
- Source text shows MeCab POS colouring (amber nouns, cyan verbs, green adjectives, muted particles, purple aux verbs) when MeCab/fugashi is installed
- Clicking any word in the source text shows a one-line tooltip with reading, lemma, and POS

Deferred out of scope:
- **Theme customisation** (light/dark QSS variants) — pure CSS work, no logic; add a second `style_light.qss` file and a `theme` QSettings key at any time without touching Python code
- **Additional animations** (QPropertyAnimation on panel collapse) — no functional value; add if desired

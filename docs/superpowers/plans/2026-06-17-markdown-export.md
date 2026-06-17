# Markdown Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four File menu items that export the current document or its series as Markdown — one translation-only format and one ruby-annotated (`<ruby>original<rt>translation</rt></ruby>`) format.

**Architecture:** Two pure functions added to `core.py` handle all text assembly; four handlers in `main_widget.py` drive file dialogs and call those functions; `combined_window.py` wires the actions into an "Export Markdown" submenu. No new files.

**Tech Stack:** Python 3.12, PySide6, SQLite (via existing `db.py`), `pathlib.Path` for file I/O.

## Global Constraints

- All new `core.py` functions must be pure Python (no Qt imports) — testable without a display.
- Follow the `%`/`$` grouping convention from `build_clipboard_output` exactly.
- `main_widget.py` handlers must use `self._topmost_suspended()` before every `QFileDialog` call.
- Series export must skip (not overwrite) files that already exist in the target folder.
- Completion notification via `QMessageBox.information` for both doc and series exports.
- Filename sanitization required: strip characters forbidden on Windows filesystems (`<>:"/\|?*` and control chars).
- Activate venv before running any commands: `source .venv/bin/activate`.

---

## File Map

| File | Change |
|---|---|
| `translation_assistant/core.py` | Add `build_markdown_translation`, `build_markdown_ruby` |
| `translation_assistant/ui/main_widget.py` | Add `import re`; add 4 `QAction`s in `_build_actions()`; add `_sanitize_filename` helper; add `_export_md_doc`, `_export_md_series` helpers; add 4 handler stubs; update `_finish_load()` |
| `translation_assistant/ui/combined_window.py` | Add "Export Markdown" submenu in `_setup_menubar()` |
| `tests/test_core.py` | Add `build_markdown_translation`, `build_markdown_ruby` to import; add `TestBuildMarkdownTranslation`, `TestBuildMarkdownRuby` classes |

---

## Task 1: Core functions (`core.py` + `test_core.py`)

**Files:**
- Modify: `translation_assistant/core.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Produces:
  - `build_markdown_translation(raw_lines: list[str], translated_lines: list[str], title: str = "") -> str`
  - `build_markdown_ruby(raw_lines: list[str], translated_lines: list[str], title: str = "") -> str`

---

- [ ] **Step 1: Add imports to test file**

Open `tests/test_core.py`. The import block at the top (lines 7–23) currently ends with `batch_import_folder,`. Add the two new names:

```python
from translation_assistant.core import (
    SEPARATOR,
    parse_file_content,
    build_new_file,
    save_file,
    load_glossary,
    replace_and_parse,
    build_review_text,
    calculate_progress,
    build_clipboard_output,
    lines_to_db_rows,
    db_rows_to_arrays,
    import_txt,
    export_txt,
    extract_frequent_nouns,
    batch_import_folder,
    build_markdown_translation,
    build_markdown_ruby,
)
```

- [ ] **Step 2: Write failing tests for `build_markdown_translation`**

Append to `tests/test_core.py` (after the existing `TestBuildClipboardOutput` class):

```python
# ---------------------------------------------------------------------------
# build_markdown_translation
# ---------------------------------------------------------------------------

class TestBuildMarkdownTranslation:
    def test_title_heading(self):
        result = build_markdown_translation(["%A"], ["hello"], title="My Chapter")
        assert result.startswith("# My Chapter\n\n")

    def test_no_title_no_heading(self):
        result = build_markdown_translation(["%A"], ["hello"])
        assert not result.startswith("#")

    def test_single_group(self):
        result = build_markdown_translation(["%A"], ["hello"])
        assert result == "hello\n\n"

    def test_continuation_joined(self):
        raw = ["%A。", "$B"]
        tl = ["first", "second"]
        result = build_markdown_translation(raw, tl)
        assert "first second\n\n" in result

    def test_empty_raw_line_preserved(self):
        raw = ["%A", "", "%B"]
        tl = ["alpha", "", "beta"]
        result = build_markdown_translation(raw, tl)
        assert "alpha\n\n" in result
        assert "beta\n\n" in result

    def test_untranslated_group_omitted(self):
        raw = ["%A", "%B"]
        tl = ["", "beta"]
        result = build_markdown_translation(raw, tl)
        assert "beta\n\n" in result
        non_blank = [l for l in result.split("\n") if l.strip()]
        assert len(non_blank) == 1

    def test_empty_inputs(self):
        assert build_markdown_translation([], []) == ""
```

- [ ] **Step 3: Write failing tests for `build_markdown_ruby`**

Append to `tests/test_core.py` (after `TestBuildMarkdownTranslation`):

```python
# ---------------------------------------------------------------------------
# build_markdown_ruby
# ---------------------------------------------------------------------------

class TestBuildMarkdownRuby:
    def test_ruby_wrapper(self):
        result = build_markdown_ruby(["%原文"], ["original text"])
        assert "<ruby>原文<rt>original text</rt></ruby>\n\n" in result

    def test_title_heading(self):
        result = build_markdown_ruby(["%A"], ["b"], title="Chapter 1")
        assert result.startswith("# Chapter 1\n\n")

    def test_continuation_concatenated(self):
        raw = ["%第一。", "$第二"]
        tl = ["first", "second"]
        result = build_markdown_ruby(raw, tl)
        assert "<ruby>第一。第二<rt>first second</rt></ruby>" in result

    def test_missing_translation_no_ruby(self):
        result = build_markdown_ruby(["%原文"], [""])
        assert "<ruby>" not in result
        assert "原文\n\n" in result

    def test_empty_raw_line_preserved(self):
        raw = ["%A", "", "%B"]
        tl = ["alpha", "", "beta"]
        result = build_markdown_ruby(raw, tl)
        assert "<ruby>A<rt>alpha</rt></ruby>" in result
        assert "<ruby>B<rt>beta</rt></ruby>" in result

    def test_empty_inputs(self):
        assert build_markdown_ruby([], []) == ""
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_core.py::TestBuildMarkdownTranslation tests/test_core.py::TestBuildMarkdownRuby -v
```

Expected: all tests fail with `ImportError: cannot import name 'build_markdown_translation'`.

- [ ] **Step 5: Implement `build_markdown_translation` in `core.py`**

Add after `build_clipboard_output` (around line 428):

```python
def build_markdown_translation(
    raw_lines: list[str],
    translated_lines: list[str],
    title: str = "",
) -> str:
    """
    Render translated lines as a plain Markdown document.

    Follows the same %/$ grouping as build_clipboard_output:
    consecutive $-prefixed lines merge with their % head.
    Untranslated groups are omitted. Empty raw lines become blank lines.
    """
    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n\n")
    count = 0
    n = len(raw_lines)
    while count < n:
        line = raw_lines[count]
        if line:
            group_size = 1
            while (count + group_size < n
                   and raw_lines[count + group_size].startswith("$")):
                group_size += 1
            translations = [translated_lines[count + x] for x in range(group_size)]
            text = " ".join(t for t in translations if t).strip()
            if text:
                parts.append(text + "\n\n")
            count += group_size
        else:
            parts.append("\n")
            count += 1
    return "".join(parts)


def build_markdown_ruby(
    raw_lines: list[str],
    translated_lines: list[str],
    title: str = "",
) -> str:
    """
    Render an HTML ruby-annotated Markdown document.

    Each %/$ group becomes <ruby>original<rt>translation</rt></ruby>.
    Groups with no translation emit the raw text without a ruby wrapper.
    """
    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n\n")
    count = 0
    n = len(raw_lines)
    while count < n:
        line = raw_lines[count]
        if line:
            group_size = 1
            while (count + group_size < n
                   and raw_lines[count + group_size].startswith("$")):
                group_size += 1
            raw_text = "".join(
                raw_lines[count + x].lstrip("%$") for x in range(group_size)
            )
            translations = [translated_lines[count + x] for x in range(group_size)]
            translation = " ".join(t for t in translations if t).strip()
            if raw_text:
                if translation:
                    parts.append(
                        f"<ruby>{raw_text}<rt>{translation}</rt></ruby>\n\n"
                    )
                else:
                    parts.append(f"{raw_text}\n\n")
            count += group_size
        else:
            parts.append("\n")
            count += 1
    return "".join(parts)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_core.py::TestBuildMarkdownTranslation tests/test_core.py::TestBuildMarkdownRuby -v
```

Expected: all 13 tests PASS.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
pytest -q
```

Expected: all 236 existing tests + 13 new = 249 pass.

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat: add build_markdown_translation and build_markdown_ruby to core"
```

---

## Task 2: UI wiring (`main_widget.py` + `combined_window.py`)

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`

**Interfaces:**
- Consumes (from Task 1):
  - `build_markdown_translation(raw_lines, translated_lines, title="") -> str`
  - `build_markdown_ruby(raw_lines, translated_lines, title="") -> str`
- Consumes (existing `db.py`):
  - `db.get_document(doc_id: int) -> dict` — keys: `title`, `chapter_title`, `series_title`, `series_order`
  - `db.get_document_ids_by_series(series_title: str) -> list[int]` — ordered by `series_order`
  - `db.get_lines(doc_id: int) -> list[dict]`
- Consumes (existing `core.py`):
  - `db_rows_to_arrays(rows: list[dict]) -> tuple[list[str], list[str]]`

---

- [ ] **Step 1: Add `import re` to `main_widget.py`**

In `translation_assistant/ui/main_widget.py`, add `import re` to the stdlib imports at the top (after `from contextlib import contextmanager`):

```python
from contextlib import contextmanager
import re
from pathlib import Path
```

- [ ] **Step 2: Add `_sanitize_filename` module-level helper**

Add this function just before the `ReviewTextEdit` class definition (around line 73):

```python
def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
```

- [ ] **Step 3: Add 4 new `QAction`s in `_build_actions()`**

In `TranslationAssistantWidget._build_actions()`, add these four actions after `self.action_about` (around line 203). All start disabled:

```python
        self.action_export_md_tl_doc = QAction("Export Markdown (Translation)…", self)
        self.action_export_md_tl_doc.triggered.connect(self._on_export_md_tl_doc)
        self.action_export_md_tl_doc.setEnabled(False)

        self.action_export_md_ruby_doc = QAction("Export Markdown (Ruby)…", self)
        self.action_export_md_ruby_doc.triggered.connect(self._on_export_md_ruby_doc)
        self.action_export_md_ruby_doc.setEnabled(False)

        self.action_export_md_tl_series = QAction("Export Series Markdown (Translation)…", self)
        self.action_export_md_tl_series.triggered.connect(self._on_export_md_tl_series)
        self.action_export_md_tl_series.setEnabled(False)

        self.action_export_md_ruby_series = QAction("Export Series Markdown (Ruby)…", self)
        self.action_export_md_ruby_series.triggered.connect(self._on_export_md_ruby_series)
        self.action_export_md_ruby_series.setEnabled(False)
```

- [ ] **Step 4: Update `_finish_load()` to enable/disable the new actions**

In `_finish_load()`, find the block that enables actions (around lines 474–477):

```python
        self.action_save.setEnabled(True)
        self.action_export.setEnabled(True)
        self.action_clipboard.setEnabled(True)
        self.action_go_to_line.setEnabled(True)
```

Add immediately after that block:

```python
        self.action_export_md_tl_doc.setEnabled(True)
        self.action_export_md_ruby_doc.setEnabled(True)
        _doc_meta = self._db.get_document(self._doc_id)
        _has_series = bool(_doc_meta.get("series_title", ""))
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
```

- [ ] **Step 5: Add `_export_md_doc` shared helper**

Add this method inside `TranslationAssistantWidget`, in the "File operations" section (after `_on_export`, around line 874):

```python
    def _export_md_doc(self, builder) -> None:
        if not self._raw_lines:
            return
        self._save_current_translation()
        with self._topmost_suspended():
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Export Markdown", "", "Markdown (*.md)"
            )
        if not filepath:
            return
        meta = self._db.get_document(self._doc_id)
        title = meta.get("chapter_title") or meta.get("title", "")
        result = builder(self._raw_lines, self._translated_lines, title)
        Path(filepath).write_text(result, encoding="utf-8")
        QMessageBox.information(self, "Export Complete", f"Markdown saved to:\n{filepath}")
```

- [ ] **Step 6: Add `_export_md_series` shared helper**

Add this method immediately after `_export_md_doc`:

```python
    def _export_md_series(self, builder) -> None:
        if self._doc_id is None:
            return
        meta = self._db.get_document(self._doc_id)
        series_title = meta.get("series_title", "")
        if not series_title:
            return
        with self._topmost_suspended():
            folder = QFileDialog.getExistingDirectory(
                self, f"Export Series: {series_title}"
            )
        if not folder:
            return
        from translation_assistant.core import db_rows_to_arrays
        doc_ids = self._db.get_document_ids_by_series(series_title)
        written = 0
        skipped = 0
        for doc_id in doc_ids:
            doc_meta = self._db.get_document(doc_id)
            rows = self._db.get_lines(doc_id)
            raw_lines, translated_lines = db_rows_to_arrays(rows)
            heading = doc_meta.get("chapter_title") or doc_meta.get("title", "")
            stem = _sanitize_filename(doc_meta.get("title") or f"doc_{doc_id}")
            filename = f"{doc_meta['series_order']:03d} - {stem}.md"
            dest = Path(folder) / filename
            if dest.exists():
                skipped += 1
                continue
            result = builder(raw_lines, translated_lines, heading)
            dest.write_text(result, encoding="utf-8")
            written += 1
        QMessageBox.information(
            self, "Export Complete",
            f"Exported {written} file(s) to:\n{folder}\n\n"
            f"{skipped} file(s) skipped (already exist).",
        )
```

- [ ] **Step 7: Add 4 thin handler methods**

Add these immediately after `_export_md_series`:

```python
    def _on_export_md_tl_doc(self) -> None:
        from translation_assistant.core import build_markdown_translation
        self._export_md_doc(build_markdown_translation)

    def _on_export_md_ruby_doc(self) -> None:
        from translation_assistant.core import build_markdown_ruby
        self._export_md_doc(build_markdown_ruby)

    def _on_export_md_tl_series(self) -> None:
        from translation_assistant.core import build_markdown_translation
        self._export_md_series(build_markdown_translation)

    def _on_export_md_ruby_series(self) -> None:
        from translation_assistant.core import build_markdown_ruby
        self._export_md_series(build_markdown_ruby)
```

- [ ] **Step 8: Add "Export Markdown" submenu in `combined_window.py`**

In `translation_assistant/ui/combined_window.py`, in `_setup_menubar()`, find the File menu section. After the line `file_menu.addAction(ta.action_export)` (line 74), add:

```python
        md_menu = QMenu("Export Markdown", self)
        md_menu.addAction(ta.action_export_md_tl_doc)
        md_menu.addAction(ta.action_export_md_ruby_doc)
        md_menu.addSeparator()
        md_menu.addAction(ta.action_export_md_tl_series)
        md_menu.addAction(ta.action_export_md_ruby_series)
        file_menu.addMenu(md_menu)
```

- [ ] **Step 9: Run the full test suite**

```bash
source .venv/bin/activate
pytest -q
```

Expected: 249 tests pass (the 13 from Task 1 plus all existing).

- [ ] **Step 10: Manual smoke test**

```bash
python -m translation_assistant.main
```

1. Open any document. Check File menu → "Export Markdown" submenu appears. "Export Markdown (Translation)…" and "Export Markdown (Ruby)…" are enabled.
2. If the document has no series, the two series actions are greyed out.
3. Open a document that belongs to a series. The series actions become enabled.
4. Export a single doc as Translation Markdown. Verify the `.md` file contains a `# Title` heading and translated paragraphs.
5. Export the same doc as Ruby Markdown. Verify each group is wrapped in `<ruby>…<rt>…</rt></ruby>`.
6. Export the series as Translation Markdown to an empty folder. Verify one `.md` file per chapter, named `000 - Title.md`, `001 - Title.md`, etc.
7. Export again to the same folder. Verify all files are skipped and the dialog reports "0 file(s)" written.

- [ ] **Step 11: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py
git commit -m "feat: add Export Markdown submenu with translation and ruby formats"
```

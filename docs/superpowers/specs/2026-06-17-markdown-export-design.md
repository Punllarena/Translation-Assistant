# Markdown Export — Design Spec

**Date:** 2026-06-17
**Status:** Approved

## Summary

Add four "Export Markdown" actions to the File menu that export the current document or its entire series as Markdown files. Two format variants: translation-only and ruby-annotated (original text as `<ruby>` base, translation as `<rt>`).

---

## Scope

| Action | Scope | Format |
|---|---|---|
| Export Markdown (Translation)… | Current doc | Translation-only |
| Export Markdown (Ruby)… | Current doc | Ruby-annotated |
| Export Series Markdown (Translation)… | All docs in series | Translation-only |
| Export Series Markdown (Ruby)… | All docs in series | Ruby-annotated |

Series actions disabled when current doc has no `series_title`.

---

## Output Format

### Translation-only

```markdown
# Chapter Title

Translated paragraph 1 sentence 1. Sentence 2.

Translated paragraph 2.
```

- `%`+`$` groups merged; translations space-joined per group.
- Empty raw lines → blank lines (paragraph break).
- `title` parameter → H1 heading.

### Ruby-annotated

```markdown
# Chapter Title

<ruby>原文一段目<rt>Translation paragraph 1</rt></ruby>

<ruby>原文二段目<rt>Translation paragraph 2</rt></ruby>
```

- Same grouping as translation-only.
- Raw text: strip `%`/`$` prefix, concatenate all lines in group.
- Translation: space-join all translations in group.
- Groups with no translation: emit raw text without ruby wrapper.

---

## Architecture

### `core.py` — 2 new pure functions

```python
def build_markdown_translation(
    raw_lines: list[str],
    translated_lines: list[str],
    title: str = "",
) -> str: ...

def build_markdown_ruby(
    raw_lines: list[str],
    translated_lines: list[str],
    title: str = "",
) -> str: ...
```

Both follow the `%`/`$` grouping loop established in `build_clipboard_output`. Pure Python, no Qt — testable without a display.

### `translation_assistant/ui/main_widget.py`

**`_build_actions()` additions** (4 new `QAction` objects, all start disabled):

```python
self.action_export_md_tl_doc      = QAction("Export Markdown (Translation)…", self)
self.action_export_md_ruby_doc    = QAction("Export Markdown (Ruby)…", self)
self.action_export_md_tl_series   = QAction("Export Series Markdown (Translation)…", self)
self.action_export_md_ruby_series = QAction("Export Series Markdown (Ruby)…", self)
```

**`_finish_load()` additions:**

- Doc actions (`_tl_doc`, `_ruby_doc`): enabled alongside `action_export`.
- Series actions (`_tl_series`, `_ruby_series`): enabled only when `db.get_document(doc_id)["series_title"]` is non-empty.

**4 new handlers:**

*Doc handlers* (`_on_export_md_tl_doc`, `_on_export_md_ruby_doc`):
1. `self._save_current_translation()`
2. `QFileDialog.getSaveFileName(filter="Markdown (*.md)")`
3. Get `doc` metadata via `self._db.get_document(self._doc_id)` for title (`chapter_title or title`).
4. Call `build_markdown_translation` or `build_markdown_ruby` with `self._raw_lines`, `self._translated_lines`, title.
5. `Path(filepath).write_text(result, encoding="utf-8")`.
6. Flash `_filesaved_label` ("Markdown exported.").

*Series handlers* (`_on_export_md_tl_series`, `_on_export_md_ruby_series`):
1. Get current doc metadata → `series_title`.
2. `QFileDialog.getExistingDirectory` to pick output folder.
3. `self._db.get_document_ids_by_series(series_title)` → ordered list of doc IDs.
4. For each doc ID:
   - `rows = self._db.get_lines(doc_id)`
   - `raw_lines, translated_lines = db_rows_to_arrays(rows)`
   - `meta = self._db.get_document(doc_id)` → `series_order`, `title`, `chapter_title`
   - `doc_title = meta["chapter_title"] or meta["title"]`
   - `filename = f"{meta['series_order']:03d} - {meta['title']}.md"`
   - `dest = Path(folder) / filename`
   - **Skip if `dest.exists()`**
   - Call builder → `dest.write_text(result, encoding="utf-8")`
5. Show summary: `QMessageBox.information` with count written / count skipped.

### `translation_assistant/ui/combined_window.py`

Add "Export Markdown" submenu in the File menu, after `action_export`:

```python
md_menu = QMenu("Export Markdown", self)
md_menu.addAction(ta.action_export_md_tl_doc)
md_menu.addAction(ta.action_export_md_ruby_doc)
md_menu.addSeparator()
md_menu.addAction(ta.action_export_md_tl_series)
md_menu.addAction(ta.action_export_md_ruby_series)
file_menu.addMenu(md_menu)
```

---

## Series File Naming

```
<output_folder>/
  000 - Chapter Title.md
  001 - Another Chapter.md
  002 - Third Chapter.md
```

- Filename = `f"{series_order:03d} - {title}.md"` using `title` (not `chapter_title`) for a stable, filesystem-safe name.
- Folder = chosen by user; typically named after the series.
- Existing files skipped, not overwritten.

---

## Enable/Disable Logic

| Action | Enabled when |
|---|---|
| `action_export_md_tl_doc` | Doc is loaded (`_doc_id is not None`) |
| `action_export_md_ruby_doc` | Doc is loaded |
| `action_export_md_tl_series` | Doc is loaded AND `series_title != ""` |
| `action_export_md_ruby_series` | Doc is loaded AND `series_title != ""` |

Updated in `_finish_load()`, same location as `action_export`.

---

## Testing

Two new test functions in `test_core.py`:

```python
def test_build_markdown_translation_groups():
    # Verifies %+$ grouping, space-join, blank lines, title heading

def test_build_markdown_ruby_groups():
    # Verifies ruby wrapping, missing-translation fallback, grouping
```

No Qt required.

---

## Out of Scope (future)

- EPUB export (separate plan)
- Per-chapter heading structure beyond H1
- Progress dialog for large series exports

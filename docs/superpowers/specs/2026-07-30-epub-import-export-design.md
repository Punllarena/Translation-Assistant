# EPUB Import/Export (Text Only, Volume-Tracked)

## Goal

Import chapters from a purchased EPUB (one volume per import) into the existing
document/series model, translate as normal, and export a translated series back
out as one `.epub` file per volume — mirroring the original volume boundaries.

Out of scope for this spec: inline illustrations and cover art (see "Deferred"
below — tracked as a follow-up spec).

## Sample data

Two BookWalker-purchased EPUB volumes live in `EPUB/` at the repo root
(untracked; being added to `.gitignore` — see "Repo hygiene"). They were used
to validate the design (chapter char-counts, ruby markup, gaiji markup, nav
structure) but tests use small synthetic EPUB fixtures, not these files.

## Data model change

`documents` gets one new column, added the same way every other column was
added in `db.py`'s `_apply_schema()` (idempotent `ALTER TABLE` via
`PRAGMA table_info` check):

```
volume_title TEXT NOT NULL DEFAULT ''
```

`series_order` is unchanged in meaning — it stays the global, monotonically
increasing order across an entire series, exactly as every other screen
(card list, series listing, stats) already relies on. It is *not* reset per
volume; the importer fetches `get_next_series_order(series_title)` once per
import and increments locally per chapter.

`db.py` changes:
- `create_document(..., volume_title: str = "")` — new keyword param, included
  in the `INSERT`.
- `get_document()` — add `volume_title` to the `SELECT` column list.
- New method `get_volume_chapter_titles(series_title: str, volume_title: str) -> set[str]`
  — `SELECT chapter_title FROM documents WHERE series_title=? AND volume_title=?`.
  Powers import dedup (see below).

No new method is needed for export-side grouping: the existing
`get_document_ids_by_series(series_title)` already returns ids ordered by
`series_order`; the export handler groups them by `volume_title` in Python
(preserves encounter order, robust even if imports were interleaved across
volumes).

## Import

### `translation_assistant/epub.py` (new module)

Framework-agnostic (no Qt, no db import) — mirrors the parsing style of
`scraper.py`.

```python
def open_book(path: Path) -> dict:
    """Returns {"title": str, "chapters": [{"order": int, "title": str,
    "href": str, "char_count": int}, ...]} in TOC order. hrefs are resolved to
    full zip-internal paths.

    Raises ValueError if the file isn't a zip / has no OPF / has neither an
    EPUB3 nav doc nor an EPUB2 toc.ncx.
    """

def extract_chapter_text(path: Path, href: str) -> str:
    """Reads the given xhtml from the zip, walks <p> tags, and returns
    paragraphs joined by "\\n" — ready for core.build_new_file().

    Per <p>, text is built by:
      - <ruby>base<rt>reading</rt></ruby>  -> "base(reading)"  (matches the
        existing convention in scraper._para_text)
      - inline <img alt="..."> (non-empty alt, appearing alongside other
        content in the same <p>) -> alt text. This handles "gaiji" glyph
        substitution, e.g. <img class="gaiji-line" src="..." alt="〜"/> used
        by some publishers to render a wave-dash as a picture instead of a
        Unicode character. Skipping this would silently drop characters from
        the extracted text.
      - a <p> whose only meaningful child is a single <img> (a standalone
        illustration paragraph, e.g. <p><img class="fit" src="..."/></p>) is
        skipped entirely — no placeholder emitted. Illustration preservation
        is deferred (see below); for this spec, dropping them is equivalent
        to today's behavior for every other text source in the app (plain
        text has no images either).
    """
```

Book title (for the default `dc:title` prefill) comes from the OPF's
`<dc:title>` in the same parse pass as `open_book()`.

### `translation_assistant/ui/dlg_import_epub.py` (new dialog)

Same browse → configure → import → summary shape as `dlg_batch_import.py`.

- **Browse…** picks a `.epub` file; `epub.open_book()` runs synchronously
  (reading ~20 small xhtml files out of a local zip is fast — no QThread
  needed).
- **Series title**: editable combo box (`QComboBox` + `QCompleter`, same
  pattern as the profile combo in `dlg_new.py`) populated from
  `db.get_series_list()`, pre-filled with the book's `dc:title`. Lets a
  volume-2 import select the existing series instead of retyping it.
- **Volume title**: plain `QLineEdit`, also pre-filled with `dc:title`,
  independently editable — this is what distinguishes volume 1 from volume 2
  even when both start from a similar `dc:title` guess.
- **Chapter checklist**: one row per TOC entry —
  `"{order}. {title}  ({char_count} chars)"`. Default-checked when
  `char_count >= 500`. Calibrated against the sample volume: junk pages
  (cover/toc/colophon/front-and-back-matter) measured 0 chars, a disclaimer
  page measured 139, the shortest real chapter measured 865, the shortest
  bonus short story measured 1665.
- **Import**: for each checked chapter, in TOC order —
  1. Skip (and record in the summary as "skipped, already imported") if
     `chapter_title` is already in
     `get_volume_chapter_titles(series_title, volume_title)`.
  2. `extract_chapter_text` → `core.build_new_file()` →
     `core.parse_file_content()` → `core.lines_to_db_rows()`.
  3. `db.create_document(chapter_title, series_title=series_title,
     series_order=next_order, chapter_title=chapter_title,
     volume_title=volume_title, source_url=href)` (`next_order` computed once
     via `get_next_series_order` before the loop, then incremented locally
     per chapter) + `db.save_lines(doc_id, rows)`.
- **Summary page**: imported / skipped / error counts, same shape as
  `BatchImportDialog`'s summary.

### Menu wiring

`main_widget.py`: new `self.action_import_epub = QAction("Import EPUB…", self)`
in `_build_actions`, next to `action_batch_import`. `combined_window.py`:
`file_menu.addAction(ta.action_import_epub)` right after
`action_batch_import`.

## Export

Translation-only (no bilingual/ruby variant, unlike the Markdown export pair —
confirmed as unnecessary for this feature).

### `epub.py` additions

```python
def build_epub(volume_title: str, chapters: list[tuple[str, list[str]]],
               *, language: str = "en") -> bytes:
    """chapters: [(chapter_title, paragraphs), ...] in output order.
    Assembles a minimal valid EPUB3 zip in memory using stdlib zipfile +
    xml.sax.saxutils.escape — no new dependency. mimetype stored uncompressed
    first entry, META-INF/container.xml, content.opf (dc:title=volume_title,
    manifest + spine), nav.xhtml (TOC from chapter titles), one xhtml per
    chapter (paragraphs wrapped in <p>, XML-escaped).

    ponytail: no stylesheet is generated — reader default styling only. Add a
    stylesheet if plain output turns out to look bad in practice.
    """
```

### `core.py` addition

```python
def build_epub_paragraphs(raw_lines: list[str], translated_lines: list[str]) -> list[str]:
    """Same %/$ grouping and empty-group skipping as build_markdown_translation,
    but returns a list of paragraph strings instead of a markdown string."""
```

### `main_widget.py` — `_on_export_epub_series`

New action **"Export Series EPUB…"**, handler mirrors `_export_md_series`:
- Prompt for parent folder, create `folder/<series_title>/`.
- `get_document_ids_by_series(series_title)` → fetch each doc's metadata,
  group by `volume_title` in Python (dict, insertion order).
- Per volume: if any chapter is <100% translated, skip the **whole volume**
  (reported in the summary) — a partial book is not a useful export, unlike
  the per-chapter markdown export where partial files are still usable.
  Otherwise build `(chapter_title, build_epub_paragraphs(...))` per chapter,
  call `epub.build_epub(volume_title, chapters)`, write to
  `folder/<volume_title>.epub` (sanitized filename). Skip (report) if that
  file already exists.
- Summary via `QMessageBox.information`, same shape as `_export_md_series`.

## Repo hygiene

`EPUB/` (currently untracked, `?? EPUB/` in git status) holds purchased
copyrighted book files (14MB/12MB) — add `EPUB/` to `.gitignore` rather than
commit them. They stay on disk for manual testing; automated tests use small
synthetic EPUB fixtures built in `tmp_path`, not these files.

## Testing

- `tests/test_epub.py` — pure unit tests against a synthetic EPUB built via
  `zipfile` in a fixture (container.xml + OPF + nav + 2-3 xhtml chapters,
  including one with ruby, one with a gaiji `<img alt>`, one standalone
  illustration paragraph, and one thin/junk page). Covers `open_book()`
  ordering/titles/char_count, ruby flattening, gaiji alt-text fallback,
  illustration-paragraph skipping, EPUB2 NCX fallback, and `build_epub()`
  round-tripping (write then re-open with `open_book()` to confirm chapter
  titles/order survive).
- `tests/test_dlg_import_epub.py` — Qt dialog test using the same synthetic
  fixture + `qapp`/`tmp_settings`, verifying the default-check threshold,
  correct `volume_title`/`series_order` on created documents, and skip-on-
  duplicate-chapter-title behavior on re-import.
- `_export_md_series`-equivalent coverage for `_on_export_epub_series`
  (partial-volume skip, existing-file skip) added alongside the existing
  `main_widget`/`combined_window` test files.

## Deferred: inline illustration preservation

Not in this spec — see
[2026-07-30-epub-illustrations-design.md](2026-07-30-epub-illustrations-design.md)
for the follow-up spec covering standalone illustration paragraphs and the
cover image, via a sidecar `document_images` table (not a change to
`raw_lines`/`core.py`).

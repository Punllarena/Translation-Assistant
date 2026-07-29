# EPUB Metadata, Chapter Heading, and Bold Formatting

## Goal

Follow-up to [2026-07-30-epub-import-export-design.md](2026-07-30-epub-import-export-design.md)
and [2026-07-30-epub-illustrations-design.md](2026-07-30-epub-illustrations-design.md).
Restores the three items those specs explicitly deferred:

- **Book-level metadata**: author, illustrator, publisher, ISBN/identifier.
- **In-body chapter heading**: the `<h2 class="oo-midashi">` title inside the
  chapter body itself (separate from the TOC/nav title already captured as
  `chapter_title`).
- **Bold span formatting**: `<span class="bold">` runs within a paragraph.

`dc:language` and `tcy` (vertical-writing-mode punctuation rotation) are
explicitly **not** restored — see "Confirmed non-issues" below.

## Recon on sample data

Both `EPUB/` sample volumes were inspected directly to ground this design:

- OPF `<metadata>` has two `dc:creator` entries distinguished by
  `<meta refines="#creatorNN" property="role" scheme="marc:relators">`: `aut`
  (author) and `ill` (illustrator). Plus `dc:publisher` and
  `dc:identifier` (`urn:isbn:...`).
- The in-body `<h2 class="oo-midashi" id="toc-014">` text is byte-identical to
  the corresponding TOC nav `<a href="...#toc-014">` text already captured as
  `chapter_title`. There is no divergence to capture on import.
- `<span class="tcy">!?</span>` and `<span class="tcy dakuten-base">` wrap
  punctuation for vertical-writing-mode rotation. `BeautifulSoup.get_text()`
  already recurses into any `<span>`, so this text is **not currently
  dropped** — only a styling hint irrelevant to horizontal English output is
  lost. Nothing to fix.
- `<span class="bold">『dialogue』</span>` wraps real paragraph substrings
  (emphasized dialogue) that do carry semantic weight in the reader-facing
  output — this is the one genuine "dropped span formatting" case.

## Confirmed non-issues (no work needed)

- **`dc:language`**: `build_epub()` (spec #1) already hardcodes
  `language: str = "en"` — the export is a translation, not a copy of the
  source language. Capturing source `dc:language` would have no consumer.
- **`tcy`**: text already survives extraction untouched (see recon above).

## Data model change

Same idempotent-migration pattern as `volume_title` (spec #1) — four more
denormalized `TEXT NOT NULL DEFAULT ''` columns on `documents`, not a new
table, since volume-level data is already stored this way (redundant across
every chapter row of that volume):

```
volume_author       TEXT NOT NULL DEFAULT ''
volume_illustrator   TEXT NOT NULL DEFAULT ''
volume_publisher     TEXT NOT NULL DEFAULT ''
volume_identifier    TEXT NOT NULL DEFAULT ''
```

`db.py` changes:
- `create_document(..., volume_author="", volume_illustrator="", volume_publisher="", volume_identifier="")`
  — new keyword params, included in the `INSERT`.
- `get_document()` — add all four to the `SELECT` column list.

No new method needed — export reads these four columns off the *first*
document of each volume group, mirroring spec #2's rule that a cover image
attaches to the first document created in an import batch (there is still no
dedicated "volume" entity in the schema to hang volume-level data on
instead).

## Import (`epub.py`)

### Metadata extraction

`open_book()`'s existing OPF parse pass gains: walk `<dc:creator>` elements,
join the ones refined with `role="aut"` into `author` and `role="ill"` into
`illustrator` (comma-separated if more than one of a role; other roles like
translator/editor are ignored — not present in sample data, not worth
generalizing for). Plus `dc:publisher` and `dc:identifier`, read verbatim
(e.g. `urn:isbn:9784867169834`), no parsing or validation.

### Chapter heading

No import-side change. The in-body heading text is identical to
`chapter_title`, already captured by spec #1. Restoring it is purely an
export-time concern (below).

### Bold spans

`extract_chapter_content`'s paragraph walker (already handling ruby-flatten
and gaiji `<img alt>`) gains one more rule: a tag with `class="bold"` has its
inner text extracted recursively (ruby/gaiji rules still apply inside it),
then the result is wrapped in `**...**` — the same "flatten semantic markup
into an inline text convention" approach already used for ruby's
`base(reading)`. The translator sees `**...**` in the source pane and may
(optionally) wrap the matching English substring in their translation if
they want the bold to survive to export; if they don't, the marker is simply
absent from `translated_lines` and no bold appears in the output — same
graceful-degradation shape as spec #2's "no cover found" case.

### Dialog changes (`dlg_import_epub.py`)

Four new prefilled, editable `QLineEdit` fields — Author, Illustrator,
Publisher, ISBN — placed below the existing series-title/volume-title
fields. Applied identically to every document created in the import batch,
the same way `volume_title` already is.

## Export

### Chapter heading

`build_epub()` (spec #1/#2) emits `<h1>{escape(chapter_title)}</h1>` as the
first element of each chapter's xhtml body, before its paragraphs. No new
parameter — `chapter_title` is already present in the
`(chapter_title, paragraphs)` tuples from spec #1's signature.

### Bold spans

New helper in `epub.py` (not `core.py` — this is XML-building, stays out of
the framework-agnostic module):

```python
def _paragraph_to_html(text: str) -> str:
    """Escapes text for XML, converting **bold** markers to <b> tags.
    Splits on \\*\\*(.+?)\\*\\* via re.split (odd-indexed groups are the
    matched bold runs); escapes every segment, wraps the bold ones in <b>."""
```

Used wherever `build_epub()` writes a `<p>` for a chapter paragraph.
`core.py`'s `build_epub_paragraphs`/`build_epub_content` (spec #1/#2) need
**no change** — `**` markers are just literal characters as far as the
`%`/`$` line-grouping logic is concerned.

### Metadata

`build_epub()` gains optional `creator`/`illustrator`/`publisher`/
`identifier` params. Blank string means the corresponding OPF tag is omitted
entirely — same "no regression when data is missing" pattern as spec #2's
optional cover. When both `creator` and `illustrator` are non-blank, two
`dc:creator` entries are emitted with `role` refinement (`aut`/`ill`),
matching the OPF shape the importer read them from.

`main_widget.py`'s `_on_export_epub_series` reads the four new columns off
the first document in each volume group (same grouping-by-`volume_title`
logic already there from spec #1) and passes them through to `build_epub()`.

## Error handling

- Missing/blank metadata fields — corresponding OPF tag omitted, no error.
- Bold markers with no matching `**` in a translated line — plain text, no
  bold in output, no error. Unbalanced `**` (odd count) in a line — treated
  as literal asterisks by `re.split`'s pairing (last unmatched `**` has no
  effect since there's no closing pair to split on); not specifically
  validated, consistent with this app's existing hands-off treatment of
  translator-entered text.

## Testing

Extends the shared synthetic-EPUB fixture (spec #1/#2) with:
- a `<span class="bold">` run, including one inside a paragraph that itself
  splits into multiple sentences (confirms the marker survives sentence
  splitting)
- an OPF with two `dc:creator` entries (`aut` + `ill` roles), a publisher,
  and an identifier

`tests/test_epub.py`: metadata extraction (`author`/`illustrator`/
`publisher`/`identifier` on `open_book()`'s return), bold-span flattening to
`**...**` on import, `_paragraph_to_html` conversion back to `<b>`,
round-trip (`build_epub()` output re-parsed confirms `<h1>` chapter heading
present and `<b>` present when source had `**...**`).

`tests/test_dlg_import_epub.py`: the four new fields prefill from OPF
metadata and are editable before import, and end up on every created
document's `volume_author`/etc. columns.

## Deferred

None — this closes out every item spec #2 flagged as a "spec #3 candidate."
No further EPUB fidelity gaps are currently tracked.

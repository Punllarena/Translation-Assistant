# EPUB Illustration Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore inline illustrations and the volume cover image, which [2026-07-30-epub-import-export.md](2026-07-30-epub-import-export.md) (Plan 1) explicitly dropped, without touching `raw_lines`/`translated_lines` or the ~10 existing functions that assume every line is translatable text.

**Architecture:** A new sidecar `document_images` table stores each image with an `anchor_position` (an insertion index into that document's `raw_lines`) and an `is_cover` flag. Only the two places that reconstruct a full chapter for *display* — `card_list.py`'s card list and EPUB export — merge images back in at render time. Plan 1's code must already exist and be merged before starting this plan.

**Tech Stack:** Same as Plan 1 (stdlib `zipfile`/`xml.sax.saxutils`, `beautifulsoup4`), plus `mimetypes.guess_type` (stdlib, no new dependency) and `QPixmap` (already-imported PySide6 module) for card-list rendering.

## Global Constraints

- Never import `sqlite3` outside `db.py`.
- `core.py` stays framework-agnostic — `build_epub_content` (this plan) belongs there; all zip/XML/image-byte work belongs in `epub.py`.
- Schema migrations are idempotent (`PRAGMA table_info` check) for `ALTER TABLE`; a brand-new table (`document_images`) is added via `CREATE TABLE IF NOT EXISTS` in the shared `_DDL` string, which is already idempotent by construction.
- This plan builds directly on Plan 1's `epub.py`, `core.py`, `dlg_import_epub.py`, and `_on_export_epub_series` — every task below assumes those already exist.
- Activate the venv before running anything: `source .venv/bin/activate`.

---

## Task 1: `document_images` table + `db.py` image helpers

**Files:**
- Modify: `translation_assistant/db.py:16-78` (`_DDL` string — add new table), `translation_assistant/db.py` (add three new methods near the `Documents` section, after `get_volume_chapter_titles` from Plan 1)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `Database.add_document_image(document_id: int, anchor_position: int, is_cover: bool, src_path: str, data: bytes) -> int`, `Database.get_document_images(document_id: int) -> list[dict]`, `Database.volume_has_cover(series_title: str, volume_title: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_add_document_image_returns_id(self, mem_db):
    doc_id = mem_db.create_document("Ch 1")
    img_id = mem_db.add_document_image(doc_id, 0, False, "images/pic.png", b"fakebytes")
    assert isinstance(img_id, int)

def test_get_document_images_empty_when_none(self, mem_db):
    doc_id = mem_db.create_document("Ch 1")
    assert mem_db.get_document_images(doc_id) == []

def test_get_document_images_returns_stored_fields(self, mem_db):
    doc_id = mem_db.create_document("Ch 1")
    mem_db.add_document_image(doc_id, 3, False, "images/pic.png", b"fakebytes")
    images = mem_db.get_document_images(doc_id)
    assert len(images) == 1
    assert images[0]["anchor_position"] == 3
    assert images[0]["is_cover"] == 0
    assert images[0]["src_path"] == "images/pic.png"
    assert images[0]["data"] == b"fakebytes"

def test_get_document_images_ordered_by_anchor_then_id(self, mem_db):
    doc_id = mem_db.create_document("Ch 1")
    mem_db.add_document_image(doc_id, 5, False, "b.png", b"b")
    mem_db.add_document_image(doc_id, 2, False, "a.png", b"a")
    mem_db.add_document_image(doc_id, 5, False, "c.png", b"c")
    images = mem_db.get_document_images(doc_id)
    assert [im["src_path"] for im in images] == ["a.png", "b.png", "c.png"]

def test_get_document_images_scoped_to_document(self, mem_db):
    doc1 = mem_db.create_document("Ch 1")
    doc2 = mem_db.create_document("Ch 2")
    mem_db.add_document_image(doc1, 0, False, "a.png", b"a")
    mem_db.add_document_image(doc2, 0, False, "b.png", b"b")
    assert len(mem_db.get_document_images(doc1)) == 1
    assert mem_db.get_document_images(doc1)[0]["src_path"] == "a.png"

def test_volume_has_cover_false_initially(self, mem_db):
    mem_db.create_document("Ch 1", series_title="S", volume_title="V1")
    assert mem_db.volume_has_cover("S", "V1") is False

def test_volume_has_cover_true_after_cover_added(self, mem_db):
    doc_id = mem_db.create_document("Ch 1", series_title="S", volume_title="V1")
    mem_db.add_document_image(doc_id, 0, True, "cover.jpg", b"cover")
    assert mem_db.volume_has_cover("S", "V1") is True

def test_volume_has_cover_isolated_by_volume(self, mem_db):
    doc1 = mem_db.create_document("Ch 1", series_title="S", volume_title="V1")
    mem_db.create_document("Ch 1", series_title="S", volume_title="V2")
    mem_db.add_document_image(doc1, 0, True, "cover.jpg", b"cover")
    assert mem_db.volume_has_cover("S", "V2") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k "document_image or volume_has_cover" -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: document_images`

- [ ] **Step 3: Add the table and methods**

In `db.py`, add to the `_DDL` string (after the `lines` table block, ~line 66-68):

```python
CREATE TABLE IF NOT EXISTS document_images (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    anchor_position INTEGER NOT NULL DEFAULT 0,
    is_cover        INTEGER NOT NULL DEFAULT 0,
    src_path        TEXT    NOT NULL,
    data            BLOB    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_images_doc ON document_images(document_id, anchor_position);
```

Add methods after `get_volume_chapter_titles` (added in Plan 1 Task 1, near line ~417-422):

```python
    def add_document_image(self, document_id: int, anchor_position: int,
                           is_cover: bool, src_path: str, data: bytes) -> int:
        cur = self._conn.execute(
            "INSERT INTO document_images (document_id, anchor_position, is_cover, src_path, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (document_id, anchor_position, 1 if is_cover else 0, src_path, data),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_document_images(self, document_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, anchor_position, is_cover, src_path, data FROM document_images "
            "WHERE document_id = ? ORDER BY anchor_position, id",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def volume_has_cover(self, series_title: str, volume_title: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM document_images di "
            "JOIN documents d ON d.id = di.document_id "
            "WHERE d.series_title = ? AND d.volume_title = ? AND di.is_cover = 1 LIMIT 1",
            (series_title, volume_title),
        ).fetchone()
        return row is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -k "document_image or volume_has_cover" -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_db.py` suite**

Run: `pytest tests/test_db.py -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add document_images table and image/cover helpers"
```

---

## Task 2: `epub.open_book()` — cover discovery

**Files:**
- Modify: `translation_assistant/epub.py` (`open_book`)
- Test: `tests/test_epub.py`

**Interfaces:**
- Produces: `open_book()`'s return dict gains `"cover_href": str | None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`. Two fixture variants: EPUB3 `properties="cover-image"` and EPUB2 `<meta name="cover">` fallback.

```python
_OPF_EPUB3_COVER = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Test Volume</dc:title>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="cover-img" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
<item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine>
<itemref idref="ch1"/>
</spine>
</package>
"""

_OPF_EPUB2_COVER = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Test Volume</dc:title>
<meta name="cover" content="cover-img"/>
</metadata>
<manifest>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="cover-img" href="images/cover.jpg" media-type="image/jpeg"/>
<item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine toc="ncx">
<itemref idref="ch1"/>
</spine>
</package>
"""


def _make_epub_with_cover(tmp_path: Path, opf: str, *, ncx: bool = False) -> Path:
    path = tmp_path / "cover.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        if ncx:
            zf.writestr("OEBPS/toc.ncx", _TOC_NCX)
        else:
            zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML.replace(
                '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
            ))
        zf.writestr("OEBPS/images/cover.jpg", b"fake-jpeg-bytes")
        zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Hello.</p></body></html>")
    return path


class TestOpenBookCover:
    def test_epub3_cover_href_resolved(self, tmp_path):
        path = _make_epub_with_cover(tmp_path, _OPF_EPUB3_COVER)
        book = open_book(path)
        assert book["cover_href"] == "OEBPS/images/cover.jpg"

    def test_epub2_cover_meta_fallback(self, tmp_path):
        path = _make_epub_with_cover(tmp_path, _OPF_EPUB2_COVER, ncx=True)
        book = open_book(path)
        assert book["cover_href"] == "OEBPS/images/cover.jpg"

    def test_no_cover_returns_none(self, tmp_path):
        book = open_book(_make_epub3(tmp_path))
        assert book["cover_href"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestOpenBookCover -v`
Expected: FAIL with `KeyError: 'cover_href'`

- [ ] **Step 3: Implement cover discovery**

In `translation_assistant/epub.py`, add a helper and wire it into `open_book()`:

```python
def _find_cover_href(opf: BeautifulSoup, opf_dir: str) -> str | None:
    """EPUB3: manifest item with properties="cover-image".
    EPUB2 fallback: <meta name="cover" content="ID"> + manifest item with that id."""
    cover_item = opf.find("item", attrs={"properties": lambda v: v and "cover-image" in v.split()})
    if cover_item is not None:
        return _resolve(opf_dir, cover_item["href"])

    cover_meta = opf.find("meta", attrs={"name": "cover"})
    if cover_meta is not None and cover_meta.get("content"):
        item = opf.find("item", attrs={"id": cover_meta["content"]})
        if item is not None:
            return _resolve(opf_dir, item["href"])

    return None
```

In `open_book()`, add the call and include it in the returned dict:

```python
        toc_entries = _read_toc(zf, opf, opf_dir)
        cover_href = _find_cover_href(opf, opf_dir)

        chapters = []
        for order, (chap_title, href) in enumerate(toc_entries, start=1):
            try:
                xhtml = _read(zf, href)
            except EpubError:
                continue
            char_count = len(BeautifulSoup(xhtml, "html.parser").get_text().strip())
            chapters.append({
                "order": order, "title": chap_title, "href": href, "char_count": char_count,
            })

        return {"title": title, "chapters": chapters, "cover_href": cover_href}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestOpenBookCover -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (Plan 1's `open_book` tests still pass — `cover_href` is additive)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): open_book() cover discovery (EPUB3 + EPUB2 fallback)"
```

---

## Task 3: `epub.extract_chapter_content()` — replaces `extract_chapter_text()`

**Files:**
- Modify: `translation_assistant/epub.py` (add `extract_chapter_content`; `extract_chapter_text` stays for now — removed in Task 6 once its call site moves, see the note in Step 3)
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: `core.build_new_file`, `core.parse_file_content` (used internally for the throwaway anchor-counting pass).
- Produces: `extract_chapter_content(path: Path, href: str) -> tuple[str, list[dict]]` returning `(text, images)` where `images` is `[{"anchor_position": int, "src_path": str, "data": bytes}, ...]` in chapter order.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

```python
from translation_assistant.epub import extract_chapter_content


def _make_illustration_epub(tmp_path: Path, body: str) -> tuple[Path, str]:
    path = tmp_path / "illust.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML)
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{body}</body></html>")
        zf.writestr("OEBPS/text/ch2.xhtml", "<html><body><p>Filler.</p></body></html>")
        zf.writestr("OEBPS/images/pic1.png", b"fake-png-1")
        zf.writestr("OEBPS/images/pic2.png", b"fake-png-2")
    return path, "OEBPS/text/ch1.xhtml"


class TestExtractChapterContent:
    def test_text_matches_extract_chapter_text_equivalent(self, tmp_path):
        path, href = _make_illustration_epub(tmp_path, "<p>First.</p><p>Second.</p>")
        text, images = extract_chapter_content(path, href)
        assert text == "First.\nSecond."
        assert images == []

    def test_illustration_after_single_sentence_paragraph(self, tmp_path):
        body = '<p>Before.</p><p><img class="fit" src="../images/pic1.png"/></p><p>After.</p>'
        path, href = _make_illustration_epub(tmp_path, body)
        text, images = extract_chapter_content(path, href)
        assert text == "Before.\nAfter."
        assert len(images) == 1
        assert images[0]["anchor_position"] == 1  # after "Before." -> 1 raw_line
        assert images[0]["src_path"] == "OEBPS/images/pic1.png"
        assert images[0]["data"] == b"fake-png-1"

    def test_anchor_position_accounts_for_sentence_splitting(self, tmp_path):
        # "First.Second." (one paragraph, two sentences) splits into 2 raw_lines
        # via build_new_file's 。-splitting -- the image after it must anchor at 2, not 1.
        body = '<p>First。Second。</p><p><img class="fit" src="../images/pic1.png"/></p><p>Third.</p>'
        path, href = _make_illustration_epub(tmp_path, body)
        text, images = extract_chapter_content(path, href)
        assert len(images) == 1
        assert images[0]["anchor_position"] == 2

    def test_two_illustrations_no_text_between(self, tmp_path):
        body = (
            '<p>Before.</p>'
            '<p><img class="fit" src="../images/pic1.png"/></p>'
            '<p><img class="fit" src="../images/pic2.png"/></p>'
            '<p>After.</p>'
        )
        path, href = _make_illustration_epub(tmp_path, body)
        text, images = extract_chapter_content(path, href)
        assert text == "Before.\nAfter."
        assert len(images) == 2
        assert images[0]["anchor_position"] == images[1]["anchor_position"] == 1
        assert images[0]["src_path"] == "OEBPS/images/pic1.png"
        assert images[1]["src_path"] == "OEBPS/images/pic2.png"

    def test_illustration_at_start_of_chapter(self, tmp_path):
        body = '<p><img class="fit" src="../images/pic1.png"/></p><p>Only text.</p>'
        path, href = _make_illustration_epub(tmp_path, body)
        text, images = extract_chapter_content(path, href)
        assert text == "Only text."
        assert images[0]["anchor_position"] == 0

    def test_illustration_at_end_of_chapter(self, tmp_path):
        body = '<p>Only text.</p><p><img class="fit" src="../images/pic1.png"/></p>'
        path, href = _make_illustration_epub(tmp_path, body)
        text, images = extract_chapter_content(path, href)
        assert text == "Only text."
        assert images[0]["anchor_position"] == 1

    def test_missing_image_bytes_skipped_not_fatal(self, tmp_path):
        body = '<p>Before.</p><p><img class="fit" src="../images/missing.png"/></p><p>After.</p>'
        path, href = _make_illustration_epub(tmp_path, body)
        text, images = extract_chapter_content(path, href)
        assert text == "Before.\nAfter."
        assert images == []  # broken manifest reference -- caught, chapter import continues
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestExtractChapterContent -v`
Expected: FAIL with `ImportError: cannot import name 'extract_chapter_content'`

- [ ] **Step 3: Implement `extract_chapter_content`**

`extract_chapter_text` (from Plan 1) stays in place unchanged for this task — nothing here requires deleting it yet. Task 6 of this plan switches `dlg_import_epub.py`'s one call site over to `extract_chapter_content`, at which point `extract_chapter_text` has no remaining caller in production code; Task 6 removes it then (see its Step 5), retargeting its still-valuable test coverage onto `extract_chapter_content` rather than losing it. Leave it in `epub.py` for now, still covered by Plan 1's tests as-is.

Add to `translation_assistant/epub.py` (add `from translation_assistant.core import build_new_file, parse_file_content` to the top-of-file imports — this is the one place `epub.py` depends on `core.py`, which is fine since `core.py` has no reverse dependency on `epub.py`):

```python
def extract_chapter_content(path: Path, href: str) -> tuple[str, list[dict]]:
    """
    Returns (text, images).
    text: same joined-paragraph string extract_chapter_text produces, ready
    for core.build_new_file().
    images: [{"anchor_position": int, "src_path": str, "data": bytes}, ...]
    in chapter order. Does not include the cover -- that comes from
    open_book()'s cover_href, read separately.

    anchor_position indexes into the *final* raw_lines array. Since
    build_new_file() splits each paragraph into multiple %/$ sentence lines,
    "between source paragraph 3 and 4" isn't the same offset as "between
    raw_lines[3] and raw_lines[4]" once paragraph 3 has split into two
    sentences. Resolved by running each individual paragraph alone through
    build_new_file()+parse_file_content() as a throwaway counting pass and
    accumulating a running raw-line offset -- this never feeds the actual
    output, only the count, since build_new_file()'s sentence-splitting is
    local per input line.
    """
    with zipfile.ZipFile(path) as zf:
        xhtml = _read(zf, href)
        soup = BeautifulSoup(xhtml, "html.parser")

        text_paragraphs: list[str] = []
        images: list[dict] = []
        offset = 0
        base_dir = posixpath.dirname(href)

        for p in soup.find_all("p"):
            if _is_standalone_illustration(p):
                img = p.find("img")
                src = img.get("src", "") if img is not None else ""
                if not src:
                    continue
                resolved_src = _resolve(base_dir, src)
                try:
                    data = zf.read(resolved_src)
                except KeyError:
                    continue  # broken manifest reference -- skip, not fatal
                images.append({
                    "anchor_position": offset, "src_path": resolved_src, "data": data,
                })
                continue

            para_text = _para_text(p)
            if not para_text:
                continue
            text_paragraphs.append(para_text)
            _, para_raw_lines, _ = parse_file_content(build_new_file(para_text))
            offset += len(para_raw_lines)

    return "\n".join(text_paragraphs), images
```

Note: `parse_file_content` returns `(raw_lines, translated_lines, raw_section)` — the unpacking above uses `_, para_raw_lines, _` which is wrong order; fix to match the real signature `(raw_lines, translated_lines, raw_section)`:

```python
            para_raw_lines, _, _ = parse_file_content(build_new_file(para_text))
            offset += len(para_raw_lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestExtractChapterContent -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (Plan 1's `extract_chapter_text` tests untouched and still pass)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): extract_chapter_content with anchor-position tracking"
```

---

## Task 4: `core.build_epub_content()`

**Files:**
- Modify: `translation_assistant/core.py` (add after `build_epub_paragraphs`)
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_epub_content(raw_lines: list[str], translated_lines: list[str], images: list[dict]) -> list[tuple[str, str]]` returning `[("text", paragraph), ("image", src_path), ...]` in order, merging `build_epub_paragraphs`' grouping with `images` at their `anchor_position`. `images` here is the export-side shape: `[{"anchor_position": int, "src_path": str}, ...]` (no `"data"` key needed — export re-reads bytes from `document_images` by `src_path` at write time).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
def test_build_epub_content_no_images_matches_paragraphs():
    raw = ["%A", "%B"]
    tl = ["Alpha", "Beta"]
    result = build_epub_content(raw, tl, [])
    assert result == [("text", "Alpha"), ("text", "Beta")]

def test_build_epub_content_image_between_paragraphs():
    raw = ["%A", "%B"]
    tl = ["Alpha", "Beta"]
    images = [{"anchor_position": 1, "src_path": "images/pic.png"}]
    result = build_epub_content(raw, tl, images)
    assert result == [("text", "Alpha"), ("image", "images/pic.png"), ("text", "Beta")]

def test_build_epub_content_image_at_start():
    raw = ["%A"]
    tl = ["Alpha"]
    images = [{"anchor_position": 0, "src_path": "images/pic.png"}]
    result = build_epub_content(raw, tl, images)
    assert result == [("image", "images/pic.png"), ("text", "Alpha")]

def test_build_epub_content_image_at_end():
    raw = ["%A"]
    tl = ["Alpha"]
    images = [{"anchor_position": 1, "src_path": "images/pic.png"}]
    result = build_epub_content(raw, tl, images)
    assert result == [("text", "Alpha"), ("image", "images/pic.png")]

def test_build_epub_content_two_images_same_anchor_preserve_order():
    raw = ["%A"]
    tl = ["Alpha"]
    images = [
        {"anchor_position": 1, "src_path": "images/pic1.png"},
        {"anchor_position": 1, "src_path": "images/pic2.png"},
    ]
    result = build_epub_content(raw, tl, images)
    assert result == [
        ("text", "Alpha"), ("image", "images/pic1.png"), ("image", "images/pic2.png"),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core.py -k build_epub_content -v`
Expected: FAIL with `ImportError: cannot import name 'build_epub_content'`

- [ ] **Step 3: Implement**

Add to `core.py` right after `build_epub_paragraphs`:

```python
# ---------------------------------------------------------------------------
# build_epub_content
# ---------------------------------------------------------------------------


def build_epub_content(
    raw_lines: list[str], translated_lines: list[str], images: list[dict],
) -> list[tuple[str, str]]:
    """
    Returns ordered [("text", paragraph), ("image", src_path), ...], merging
    build_epub_paragraphs' output with images at their anchor_position.
    images: [{"anchor_position": int, "src_path": str}, ...]. Callers pass
    them pre-sorted by (anchor_position, id) -- db.get_document_images()
    already returns that order -- so equal anchors here simply preserve
    input order (stable sort is not needed; we just iterate in order).
    """
    result: list[tuple[str, str]] = []
    count = 0
    n = len(raw_lines)
    img_idx = 0

    def _flush_images_up_to(position: int) -> None:
        nonlocal img_idx
        while img_idx < len(images) and images[img_idx]["anchor_position"] <= position:
            result.append(("image", images[img_idx]["src_path"]))
            img_idx += 1

    while count < n:
        line = raw_lines[count]
        if line:
            _flush_images_up_to(count)
            group_size = 1
            while (count + group_size < n
                   and raw_lines[count + group_size].startswith("$")):
                group_size += 1
            translations = [translated_lines[count + x] for x in range(group_size)]
            text = " ".join(t for t in translations if t).strip()
            if text:
                result.append(("text", text))
            count += group_size
        else:
            count += 1

    _flush_images_up_to(n)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py -k build_epub_content -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat(core): add build_epub_content — interleaves paragraphs and images"
```

---

## Task 5: `epub.build_epub()` — images and cover

**Files:**
- Modify: `translation_assistant/epub.py` (`build_epub`, chapter/nav/OPF templates)
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: `build_epub_content`'s output shape (`list[tuple[str, str]]`) as each chapter's content.
- Produces: `build_epub(volume_title, chapters, *, language="en", cover=None) -> bytes` where `chapters` is now `list[tuple[str, list[tuple[str, str]], list[dict]]]` — `(chapter_title, content_items, chapter_images)`. `content_items` is `build_epub_content`'s return value (drives text/image placement in the xhtml body); `chapter_images` is `[{"src_path": str, "data": bytes}, ...]` (the actual bytes to write into the zip, keyed by the same `src_path` strings `content_items` references). `cover` is `{"data": bytes, "media_type": str} | None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

```python
class TestBuildEpubImages:
    def test_chapter_with_image_round_trips(self, tmp_path):
        content = [("text", "Before."), ("image", "images/pic.png"), ("text", "After.")]
        chapter_images = [{"src_path": "images/pic.png", "data": b"fake-png-bytes"}]
        result = build_epub("Vol", [("Ch 1", content, chapter_images)])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            assert zf.read("OEBPS/images/pic.png") == b"fake-png-bytes"
            xhtml = zf.read("OEBPS/text/chap1.xhtml").decode("utf-8")
        assert '<img src="../images/pic.png"' in xhtml
        assert xhtml.index("Before.") < xhtml.index('<img') < xhtml.index("After.")

    def test_no_images_still_works(self, tmp_path):
        content = [("text", "Hello.")]
        result = build_epub("Vol", [("Ch 1", content, [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        assert zipfile.is_zipfile(out)

    def test_cover_manifest_and_meta(self, tmp_path):
        cover = {"data": b"fake-cover-bytes", "media_type": "image/jpeg"}
        result = build_epub("Vol", [("Ch 1", [("text", "Hello.")], [])], cover=cover)
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            assert zf.read("OEBPS/images/cover.jpg") == b"fake-cover-bytes"
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert 'properties="cover-image"' in opf
        assert '<meta name="cover" content="cover-image"/>' in opf

    def test_no_cover_no_cover_metadata(self, tmp_path):
        result = build_epub("Vol", [("Ch 1", [("text", "Hello.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "cover" not in opf
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestBuildEpubImages -v`
Expected: FAIL — `build_epub()`'s current (Plan 1) signature takes `list[str]` paragraphs per chapter, not `(title, content, images)` triples, and has no `cover` param.

- [ ] **Step 3: Update `build_epub`'s signature and body**

Replace the `build_epub` function in `translation_assistant/epub.py` (add `import mimetypes` to the top-of-file imports):

```python
_OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{title}</dc:title>
<dc:language>{lang}</dc:language>
<dc:identifier id="uid">{identifier}</dc:identifier>
{cover_meta}
</metadata>
<manifest>
{manifest}
</manifest>
<spine>
{spine}
</spine>
</package>
"""


def build_epub(
    volume_title: str,
    chapters: list[tuple[str, list[tuple[str, str]], list[dict]]],
    *, language: str = "en",
    cover: dict | None = None,
) -> bytes:
    """
    chapters: [(chapter_title, content_items, chapter_images), ...] in output
    order. content_items is core.build_epub_content()'s return shape
    ([("text", paragraph) | ("image", src_path), ...]); chapter_images is
    [{"src_path": str, "data": bytes}, ...] -- the actual bytes to embed,
    keyed by the same src_path strings content_items references.
    cover: {"data": bytes, "media_type": str} or None. When present, the
    cover image gets a manifest item with properties="cover-image" plus a
    <meta name="cover" content="..."> entry for older-reader compatibility.

    ponytail: no stylesheet is generated -- reader default styling only.
    ponytail: no dedicated cover.xhtml title page -- the manifest/meta cover
    metadata alone is enough for the readers that matter; add a real cover
    page later only if a specific reader needs one.
    """
    import uuid

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML_OUT)

        manifest_items = []
        spine_items = []
        nav_lis = []
        image_id = 0

        for i, (chapter_title, content_items, chapter_images) in enumerate(chapters, start=1):
            chap_id = f"chap{i}"
            href = f"text/chap{i}.xhtml"
            image_bytes_by_src = {img["src_path"]: img["data"] for img in chapter_images}
            written_images: dict[str, str] = {}  # src_path -> zip-relative href written this chapter

            body_parts = []
            for kind, value in content_items:
                if kind == "text":
                    body_parts.append(f"<p>{escape(value)}</p>\n")
                else:
                    src_path = value
                    if src_path not in written_images:
                        image_id += 1
                        ext = src_path.rsplit(".", 1)[-1] if "." in src_path else "img"
                        img_href = f"images/{image_id}.{ext}"
                        data = image_bytes_by_src.get(src_path)
                        if data is None:
                            continue  # referenced image has no bytes -- skip, not fatal
                        zf.writestr(f"OEBPS/{img_href}", data)
                        media_type = mimetypes.guess_type(src_path)[0] or "application/octet-stream"
                        manifest_items.append(
                            f'<item id="img{image_id}" href="{img_href}" media-type="{media_type}"/>'
                        )
                        written_images[src_path] = img_href
                    body_parts.append(f'<p><img src="../{written_images[src_path]}"/></p>\n')

            xhtml = _CHAPTER_TEMPLATE.format(
                title=escape(chapter_title), body="".join(body_parts), lang=language,
            )
            zf.writestr(f"OEBPS/{href}", xhtml)
            manifest_items.append(
                f'<item id="{chap_id}" href="{href}" media-type="application/xhtml+xml"/>'
            )
            spine_items.append(f'<itemref idref="{chap_id}"/>')
            nav_lis.append(f'<li><a href="{href}">{escape(chapter_title)}</a></li>')

        zf.writestr("OEBPS/nav.xhtml", _NAV_TEMPLATE.format(lang=language, items="\n".join(nav_lis)))
        manifest_items.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )

        cover_meta = ""
        if cover is not None:
            ext = mimetypes.guess_extension(cover["media_type"]) or ".img"
            cover_href = f"images/cover{ext}"
            zf.writestr(f"OEBPS/{cover_href}", cover["data"])
            manifest_items.append(
                f'<item id="cover-image" href="{cover_href}" media-type="{cover["media_type"]}" '
                f'properties="cover-image"/>'
            )
            cover_meta = '<meta name="cover" content="cover-image"/>'

        opf = _OPF_TEMPLATE.format(
            title=escape(volume_title),
            lang=language,
            identifier=f"urn:uuid:{uuid.uuid4()}",
            manifest="\n".join(manifest_items),
            spine="\n".join(spine_items),
            cover_meta=cover_meta,
        )
        zf.writestr("OEBPS/content.opf", opf)

    return buf.getvalue()
```

Note: `mimetypes.guess_extension("image/jpeg")` returns `.jpg` in modern Python (verify with `python3 -c "import mimetypes; print(mimetypes.guess_extension('image/jpeg'))"` if the test expects `.jpg` — if it returns `.jpe` on the CI's Python build, change the test's expected path to match rather than hardcoding `.jpg`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestBuildEpubImages -v`
Expected: PASS

- [ ] **Step 5: Update Plan 1's `TestBuildEpub` tests to the new signature**

Plan 1's `build_epub` tests in `tests/test_epub.py::TestBuildEpub` call `build_epub("My Volume", [("Chapter 1", ["Hello."])])` — the old `list[str]` shape. Update every call in that class to the new `(title, content_items, images)` shape, e.g.:

```python
    def test_returns_bytes(self):
        result = build_epub("My Volume", [("Chapter 1", [("text", "Hello.")], [])])
        assert isinstance(result, bytes)
        assert len(result) > 0
```

Apply the same `[("text", p) for p in paragraphs]`-shaped conversion, with `[]` for the third tuple element, to every test in `TestBuildEpub` and to `TestExtractChapterText`'s / `TestOpenBookEpub3`'s round-trip tests that call `build_epub` (search `tests/test_epub.py` for every `build_epub(` call site and update it — there should be exactly the ones in `TestBuildEpub` from Plan 1 Task 6, since this plan's own `TestBuildEpubImages` tests were already written in the new shape in Step 1 above).

- [ ] **Step 6: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS — all tests, old and new, using the updated signature.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): build_epub() gains per-chapter images and volume cover"
```

---

## Task 6: Wire images and cover into `dlg_import_epub.py`

**Files:**
- Modify: `translation_assistant/ui/dlg_import_epub.py` (`_on_import`), `translation_assistant/epub.py` (removes `extract_chapter_text` — see Step 5)
- Test: `tests/test_dlg_import_epub.py`, `tests/test_epub.py` (retargets `extract_chapter_text`'s tests onto `extract_chapter_content`)

**Interfaces:**
- Consumes: `epub.extract_chapter_content` (replaces `extract_chapter_text`), `Database.add_document_image`, `Database.volume_has_cover`.
- Removes: `epub.extract_chapter_text` (Plan 1 Task 5) — its only call site moves to `epub.extract_chapter_content` in this task.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dlg_import_epub.py`:

```python
def _make_epub_with_illustration(tmp_path: Path) -> Path:
    path = tmp_path / "illust_vol.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3_COVER)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML.replace(
            '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
        ))
        zf.writestr("OEBPS/images/cover.jpg", b"fake-cover-bytes")
        body = '<p>' + "A" * 600 + '。</p><p><img class="fit" src="../images/inline.png"/></p>'
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{body}</body></html>")
        zf.writestr("OEBPS/images/inline.png", b"fake-inline-bytes")
    return path


class TestImportEpubImages:
    def test_import_attaches_inline_image(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub_with_illustration(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("S")
        dlg._volume_edit.setText("V1")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("S")[0]
        images = mem_db.get_document_images(doc_id)
        inline = [im for im in images if not im["is_cover"]]
        assert len(inline) == 1
        assert inline[0]["data"] == b"fake-inline-bytes"

    def test_import_attaches_cover_to_first_document(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub_with_illustration(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("S")
        dlg._volume_edit.setText("V1")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("S")[0]
        images = mem_db.get_document_images(doc_id)
        cover = [im for im in images if im["is_cover"]]
        assert len(cover) == 1
        assert cover[0]["data"] == b"fake-cover-bytes"

    def test_reimport_does_not_duplicate_cover(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub_with_illustration(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg1 = ImportEpubDialog(mem_db)
        dlg1._on_browse()
        dlg1._series_edit.setText("S")
        dlg1._volume_edit.setText("V1")
        dlg1._on_import()

        # Second batch against the same volume (e.g. re-running import to
        # pick up a chapter left unchecked the first time).
        dlg2 = ImportEpubDialog(mem_db)
        dlg2._on_browse()
        dlg2._series_edit.setText("S")
        dlg2._volume_edit.setText("V1")
        dlg2._on_import()  # Chapter 1 already imported -> skipped; nothing new to attach a cover to

        assert mem_db.volume_has_cover("S", "V1") is True
        all_covers = [
            im for doc_id in mem_db.get_document_ids_by_series("S")
            for im in mem_db.get_document_images(doc_id) if im["is_cover"]
        ]
        assert len(all_covers) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dlg_import_epub.py::TestImportEpubImages -v`
Expected: FAIL — `dlg_import_epub.py` still calls `extract_chapter_text` (no images) and never touches `add_document_image`/`volume_has_cover`.

- [ ] **Step 3: Update `_on_import`**

In `translation_assistant/ui/dlg_import_epub.py`, change the import line to use `extract_chapter_content`:

```python
from translation_assistant.epub import EpubError, extract_chapter_content, open_book
```

Replace the body of `_on_import`'s per-chapter try block and add cover handling:

```python
    def _on_import(self) -> None:
        if self._book is None or self._book_path is None:
            return
        series_title = self._series_edit.text().strip()
        volume_title = self._volume_edit.text().strip()

        already_imported = self._db.get_volume_chapter_titles(series_title, volume_title)
        next_order = self._db.get_next_series_order(series_title)
        cover_href = self._book.get("cover_href")
        cover_data = None
        if cover_href and not self._db.volume_has_cover(series_title, volume_title):
            try:
                import zipfile
                with zipfile.ZipFile(self._book_path) as zf:
                    cover_data = zf.read(cover_href)
            except Exception:
                cover_data = None

        imported = []
        skipped = []
        errors = []
        first_new_doc_id = None
        for i in range(self._chapter_list.count()):
            item = self._chapter_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            ch = item.data(Qt.ItemDataRole.UserRole)
            if ch["title"] in already_imported:
                skipped.append(ch["title"])
                continue
            try:
                text, images = extract_chapter_content(self._book_path, ch["href"])
                formatted = build_new_file(text)
                raw_lines, translated_lines, _ = parse_file_content(formatted)
                rows = lines_to_db_rows(raw_lines, translated_lines)
                doc_id = self._db.create_document(
                    ch["title"],
                    series_title=series_title,
                    series_order=next_order,
                    chapter_title=ch["title"],
                    volume_title=volume_title,
                    source_url=ch["href"],
                )
                self._db.save_lines(doc_id, rows)
                for img in images:
                    self._db.add_document_image(
                        doc_id, img["anchor_position"], False, img["src_path"], img["data"]
                    )
                if first_new_doc_id is None:
                    first_new_doc_id = doc_id
                next_order += 1
                imported.append(ch["title"])
            except Exception as exc:
                errors.append((ch["title"], str(exc)))

        if cover_data is not None and first_new_doc_id is not None:
            self._db.add_document_image(first_new_doc_id, 0, True, cover_href, cover_data)

        self._show_summary(imported, skipped, errors)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dlg_import_epub.py -v`
Expected: PASS — all tests including Plan 1's original ones (still valid; `extract_chapter_content`'s `text` output matches `extract_chapter_text`'s for chapters with no illustrations).

- [ ] **Step 5: Delete the now-dead `extract_chapter_text`**

This step's Step 3 moved `dlg_import_epub.py`'s only call from `extract_chapter_text` to `extract_chapter_content` — the same situation as `build_epub_paragraphs` in Task 7, and resolved the same way: delete rather than leave an unused function behind. Plan 1 Task 5's `TestExtractChapterText` class in `tests/test_epub.py` still carries real, non-redundant coverage (ruby flattening, gaiji `<img alt>`, standalone-illustration skipping, ruby-nested-in-span) that `TestExtractChapterContent` (this plan's Task 3) doesn't duplicate — its tests focus on anchor-position tracking, not re-asserting every text-flattening rule. Don't delete that coverage; retarget it:

- Remove the `extract_chapter_text` function from `translation_assistant/epub.py` (added in Plan 1 Task 5).
- In `tests/test_epub.py`'s `TestExtractChapterText` class, change every `extract_chapter_text(path, href)` call to `extract_chapter_content(path, href)[0]` (the `text` half of the returned tuple) — the assertions themselves (expected flattened strings) stay exactly the same, since `extract_chapter_content`'s text output is the same joined-paragraph string `extract_chapter_text` produced. Update the class's import line accordingly.

Run: `pytest tests/test_epub.py -v`
Expected: PASS — `TestExtractChapterText`'s assertions unchanged in substance, now exercised through `extract_chapter_content`.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_import_epub.py tests/test_dlg_import_epub.py translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(ui): ImportEpubDialog attaches inline images and guarded cover

Also removes extract_chapter_text (Plan 1), superseded by
extract_chapter_content now that its one call site has moved over."
```

---

## Task 7: `_on_export_epub_series` — read images, pass to export

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (`_on_export_epub_series`, written in Plan 1 Task 9), `translation_assistant/core.py` (removes `build_epub_paragraphs` — see Step 5)
- Test: `tests/test_main_window.py`, `tests/test_core.py` (removes `build_epub_paragraphs`' tests)

**Interfaces:**
- Consumes: `Database.get_document_images`, `core.build_epub_content`, `epub.build_epub`'s new `(title, content_items, images)` chapter shape and `cover` param.
- Removes: `core.build_epub_paragraphs` (Plan 1 Task 2) — its only call site moves to `core.build_epub_content` in this task.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py`, in `TestExportEpubSeries`:

```python
    def test_exported_epub_contains_inline_image(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        db.add_document_image(doc_id, 1, False, "images/pic.png", b"fake-bytes")
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "translation_assistant.ui.main_widget.QMessageBox.information"
        ):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert any(n.endswith("pic.png") for n in names)

    def test_exported_epub_contains_cover(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        db.add_document_image(doc_id, 0, True, "images/cover.jpg", b"fake-cover-bytes")
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "translation_assistant.ui.main_widget.QMessageBox.information"
        ):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "cover-image" in opf
```

(As in Plan 1 Task 9, prefer the file's existing `from unittest.mock import patch` import over the inline `__import__` form if already present.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main_window.py -k "exported_epub_contains" -v`
Expected: FAIL — `_on_export_epub_series` doesn't read `document_images` yet, and calls `build_epub` with Plan 1's old signature (now broken after Task 5 of this plan changed it).

- [ ] **Step 3: Update `_on_export_epub_series`**

Replace the body written in Plan 1 Task 9 with the images/cover-aware version:

```python
    def _on_export_epub_series(self) -> None:
        self._save_current_translation()
        if self._doc_id is None:
            return
        meta = self._db.get_document(self._doc_id)
        series_title = meta.get("series_title", "")
        if not series_title:
            return
        with self._topmost_suspended():
            parent = QFileDialog.getExistingDirectory(
                self, f"Export Series EPUB: {series_title} — select parent folder"
            )
        if not parent:
            return
        folder = Path(parent) / (_sanitize_filename(series_title) or "series")
        folder.mkdir(exist_ok=True)

        import mimetypes
        from translation_assistant.core import build_epub_content, calculate_progress, db_rows_to_arrays
        from translation_assistant.epub import build_epub

        doc_ids = self._db.get_document_ids_by_series(series_title)
        volumes: dict[str, list[int]] = {}
        for doc_id in doc_ids:
            doc_meta = self._db.get_document(doc_id)
            volumes.setdefault(doc_meta.get("volume_title", ""), []).append(doc_id)

        written = 0
        skipped_incomplete = 0
        skipped_exists = 0
        for volume_title, vol_doc_ids in volumes.items():
            chapters = []
            cover = None
            incomplete = False
            for doc_id in vol_doc_ids:
                doc_meta = self._db.get_document(doc_id)
                rows = self._db.get_lines(doc_id)
                raw_lines, translated_lines = db_rows_to_arrays(rows)
                pct, _ = calculate_progress(raw_lines, translated_lines)
                if pct < 100:
                    incomplete = True
                    break
                all_images = self._db.get_document_images(doc_id)
                inline_images = [im for im in all_images if not im["is_cover"]]
                if cover is None:
                    cover_row = next((im for im in all_images if im["is_cover"]), None)
                    if cover_row is not None:
                        media_type = mimetypes.guess_type(cover_row["src_path"])[0] or "application/octet-stream"
                        cover = {"data": cover_row["data"], "media_type": media_type}

                heading = doc_meta.get("chapter_title") or doc_meta.get("title", "")
                content_items = build_epub_content(raw_lines, translated_lines, inline_images)
                chapter_images = [
                    {"src_path": im["src_path"], "data": im["data"]} for im in inline_images
                ]
                chapters.append((heading, content_items, chapter_images))
            if incomplete:
                skipped_incomplete += 1
                continue
            filename = f"{_sanitize_filename(volume_title) or 'volume'}.epub"
            dest = folder / filename
            if dest.exists():
                skipped_exists += 1
                continue
            dest.write_bytes(build_epub(volume_title, chapters, cover=cover))
            written += 1

        lines = [f"Exported {written} volume(s) to:\n{folder}"]
        if skipped_exists:
            lines.append(f"{skipped_exists} volume(s) skipped (file already exists)")
        if skipped_incomplete:
            lines.append(f"{skipped_incomplete} volume(s) skipped (incomplete translation)")
        QMessageBox.information(self, "Export Complete", "\n\n".join(lines))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main_window.py::TestExportEpubSeries -v`
Expected: PASS — including Plan 1's original tests in this class (no images attached in those fixtures, so `inline_images`/`cover` are empty/`None` and behavior matches Plan 1 exactly).

- [ ] **Step 5: Delete the now-dead `build_epub_paragraphs`**

This task's Step 3 replaced `_on_export_epub_series`'s call to `core.build_epub_paragraphs` with `core.build_epub_content`. That was `build_epub_paragraphs`' only production call site (added in Plan 1 Task 2 for exactly that call site) — after this change it has no caller left except its own unit tests. `build_epub_content` (this plan's Task 4) is a strict superset: calling it with `images=[]` reproduces `build_epub_paragraphs`' output shape wrapped in `("text", paragraph)` tuples, so there is no remaining use case for keeping both. Delete it rather than leave unused code behind:

- Remove the `build_epub_paragraphs` function from `translation_assistant/core.py` (added in Plan 1 Task 2, right after `build_markdown_translation`).
- Remove its five tests from `tests/test_core.py` (`test_build_epub_paragraphs_basic`, `_merges_continuations`, `_skips_untranslated`, `_skips_blank_raw_lines`, `_empty_input`) and drop it from that file's `from translation_assistant.core import ...` block.

Run: `pytest tests/test_core.py -v`
Expected: PASS (no leftover references to the deleted function anywhere in the test file)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py translation_assistant/core.py tests/test_core.py
git commit -m "feat(ui): Export Series EPUB… includes inline images and cover

Also removes build_epub_paragraphs (Plan 1), superseded by
build_epub_content now that its one call site has moved over."
```

---

## Task 8: `card_list.py` — render images in the card list

**Files:**
- Modify: `translation_assistant/ui/card_list.py` (`CardListView.load`, `CardListView._build_batch`, add `_make_image_widget`)
- Test: `tests/test_card_list.py`

**Interfaces:**
- Consumes: nothing new from other tasks (images are passed in directly as plain dicts by the caller — see Task 9).
- Produces: `CardListView.load(raw_lines, translated_lines, glossary, images=None)` — `images: list[dict] | None`, each `{"anchor_position": int, "data": bytes}` (`src_path`/`id` not needed for rendering, so the caller may pass a leaner dict — see Task 9's exact shape).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_card_list.py`, a new class near `TestCardListView`. Uses a minimal valid 1x1 PNG so `QPixmap.loadFromData` produces a real (non-null) pixmap:

```python
# A valid 1x1 red-pixel PNG, used wherever tests need real image bytes.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestCardListViewImages:
    def test_image_appears_between_cards(self, view):
        images = [{"anchor_position": 1, "data": _TINY_PNG}]
        view.load(["%A", "%B"], ["", ""], [], images)
        # index 0: card A, index 1: image widget, index 2: card B, then placeholder+stretch
        assert view._vbox.itemAt(0).widget() is view.card(0)
        assert view._vbox.itemAt(1).widget() in view._image_widgets
        assert view._vbox.itemAt(2).widget() is view.card(1)

    def test_image_at_start(self, view):
        images = [{"anchor_position": 0, "data": _TINY_PNG}]
        view.load(["%A"], [""], [], images)
        assert view._vbox.itemAt(0).widget() in view._image_widgets
        assert view._vbox.itemAt(1).widget() is view.card(0)

    def test_image_at_end(self, view):
        images = [{"anchor_position": 1, "data": _TINY_PNG}]
        view.load(["%A"], [""], [], images)
        assert view._vbox.itemAt(0).widget() is view.card(0)
        assert view._vbox.itemAt(1).widget() in view._image_widgets

    def test_no_images_backward_compatible(self, view):
        view.load(["%A", "%B"], ["", ""], [])  # 3-arg call, as every existing test uses
        assert view.card_count() == 2
        assert view._image_widgets == []

    def test_reload_clears_previous_images(self, view):
        images = [{"anchor_position": 0, "data": _TINY_PNG}]
        view.load(["%A"], [""], [], images)
        view.load(["%B"], [""], [])
        assert view._image_widgets == []

    def test_image_does_not_get_a_card_index(self, view):
        images = [{"anchor_position": 1, "data": _TINY_PNG}]
        view.load(["%A", "%B"], ["", ""], [], images)
        assert view.card_count() == 2  # only the two text lines, image is not a card
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_card_list.py::TestCardListViewImages -v`
Expected: FAIL — `load()` doesn't accept a 4th positional arg, `_image_widgets` doesn't exist.

- [ ] **Step 3: Implement image rendering in `CardListView`**

Add `from PySide6.QtGui import QPixmap` to the top-of-file imports.

In `__init__` (near `self._ordered = []` at line ~305), add:

```python
        self._image_widgets: list[QLabel] = []
```

Replace `load()` (lines 337-361):

```python
    def load(self, raw_lines: list[str], translated_lines: list[str],
             glossary: list[tuple[str, str]], images: list[dict] | None = None) -> None:
        from translation_assistant.core import line_has_content
        self._detach_active()
        for card in self._cards.values():
            self._vbox.removeWidget(card)
            card.deleteLater()
        for img_widget in self._image_widgets:
            self._vbox.removeWidget(img_widget)
            img_widget.deleteLater()
        self._cards = {}
        self._ordered = []
        self._image_widgets = []

        images = sorted(images or [], key=lambda im: im["anchor_position"])
        pending: list[tuple] = []
        img_idx = 0
        for i, raw in enumerate(raw_lines):
            while img_idx < len(images) and images[img_idx]["anchor_position"] <= i:
                pending.append(("image", images[img_idx]))
                img_idx += 1
            if line_has_content(raw):
                pending.append(("card", i, raw))
        while img_idx < len(images):
            pending.append(("image", images[img_idx]))
            img_idx += 1

        # ponytail: chunked build (100 entries/tick) — 1000 sync cards took 3.6s;
        # virtualize only if even this proves too slow on real chapters.
        self._pending = pending
        self._built_count = 0
        self._load_translations = translated_lines
        self._load_glossary = glossary
        self._build_batch()
        if self._pending:
            QTimer.singleShot(0, self._build_batch)

        self._placeholder.setVisible(not (self._cards or self._image_widgets or self._pending))
        self._update_edge_padding()
        self.verticalScrollBar().setValue(0)
```

Replace `_build_batch()` (lines 363-389):

```python
    def _build_batch(self) -> None:
        if not self._pending:
            return
        insert_at = self._vbox.indexOf(self._placeholder)
        batch, self._pending = self._pending[:100], self._pending[100:]
        for entry in batch:
            if entry[0] == "card":
                _, i, raw = entry
                self._built_count += 1
                card = LineCard(i, self._built_count,
                                glossary_html(raw, self._load_glossary),
                                self._load_translations[i])
                if self._font_pt is not None:
                    card.set_font_size(self._font_pt)
                card.clicked.connect(self.card_clicked)
                self._vbox.insertWidget(insert_at, card)
                insert_at += 1
                self._cards[i] = card
                self._ordered.append(card)
            else:
                _, image = entry
                widget = self._make_image_widget(image)
                self._vbox.insertWidget(insert_at, widget)
                insert_at += 1
                self._image_widgets.append(widget)
        if self._pending:
            QTimer.singleShot(0, self._build_batch)
        elif self.active_index is not None:
            card = self._cards.get(self.active_index)
            if card is not None:
                self._scroll_to(card)
        QTimer.singleShot(0, self._apply_wheel)

    def _make_image_widget(self, image: dict) -> QLabel:
        """Plain, non-editable illustration widget — not a LineCard, no index,
        not part of navigation/spellcheck/progress."""
        label = QLabel()
        label.setObjectName("CardImage")
        pixmap = QPixmap()
        pixmap.loadFromData(image["data"])
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(400, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_card_list.py::TestCardListViewImages -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_card_list.py` file**

Run: `pytest tests/test_card_list.py -v`
Expected: PASS — every existing 3-arg `.load(...)` call site still works (`images` defaults to `None`), `_apply_wheel`'s `self._ordered` (cards only, unchanged) still drives the fade effect correctly since image widgets are intentionally excluded from `_ordered`.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "feat(ui): CardListView renders inline illustrations at their anchor position"
```

---

## Task 9: Wire `get_document_images` into `main_widget.py`'s card-list load call

**Files:**
- Modify: `translation_assistant/ui/main_widget.py:586` (inside `_finish_load`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `Database.get_document_images`, `CardListView.load(..., images=...)` (Task 8).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py` (a suitable existing class covering `_finish_load`/`open_document`, or a new small class):

```python
class TestCardListImagesWiring:
    def test_open_document_passes_images_to_card_view(self, win):
        doc_id = win._db.create_document("Ch 1", chapter_title="Ch 1")
        win._db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": ""},
        ])
        win._db.add_document_image(doc_id, 0, False, "images/pic.png", b"fake-bytes")
        win.open_document(doc_id)
        assert len(win._card_view._image_widgets) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_window.py::TestCardListImagesWiring -v`
Expected: FAIL — `_card_view._image_widgets` is empty because `_finish_load` never passes images.

- [ ] **Step 3: Update the call site**

In `main_widget.py`, `_finish_load` (line ~586), replace:

```python
        self._card_view.load(raw_lines, translated_lines, self._glossary)
```

with:

```python
        images = self._db.get_document_images(self._doc_id) if self._doc_id is not None else []
        inline_images = [im for im in images if not im["is_cover"]]
        self._card_view.load(raw_lines, translated_lines, self._glossary, inline_images)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_window.py::TestCardListImagesWiring -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): wire document images into the card list on document open"
```

---

## Task 10: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: PASS — all tests green, including everything added in Tasks 1-9 of this plan and all of Plan 1.

- [ ] **Step 2: Manual smoke test against a real sample volume with illustrations**

Run the app, use **File → Import EPUB…** against one of the two files in `EPUB/` (both are known from the design spec's recon to contain inline illustrations and a cover), confirm the cover doesn't appear inline in the card list (per design, it's export-only) but inline illustrations appear at the right position between cards, translate a full volume, then **File → Export Series EPUB…** and open the resulting `.epub` in any EPUB reader (or re-`open_book()`/`extract_chapter_content()` it) to confirm the cover and inline images survived. This step is exploratory — its purpose is to catch anything the synthetic fixtures couldn't (image format variety, degenerate `anchor_position` cases at real scale).

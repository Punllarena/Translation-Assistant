# EPUB Metadata, Chapter Heading, and Bold Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore book-level metadata (author/illustrator/publisher/ISBN), the in-body chapter heading, and bold span formatting — the three items [2026-07-30-epub-illustrations-design.md](../specs/2026-07-30-epub-illustrations-design.md) deferred as "spec #3."

**Architecture:** Four new denormalized columns on `documents` (same pattern as `volume_title`). `epub.py` gains OPF metadata extraction and a bold-span-to-`**marker**` flattening rule alongside the existing ruby/gaiji rules. Export emits an `<h1>` per chapter and converts `**marker**` text back to `<b>` via a small new HTML-building helper — `core.py` stays untouched for both of these since markers are just literal characters to its line-grouping logic. Plans 1 and 2 must already be merged before starting this plan (every task here modifies functions those plans created).

**Tech Stack:** Same as Plans 1 and 2 — stdlib `zipfile`/`xml.sax.saxutils`/`re`, `beautifulsoup4` (`html.parser`) — no new dependencies.

## Global Constraints

- Never import `sqlite3` outside `db.py`.
- `core.py` stays framework-agnostic. `build_epub_paragraphs`/`build_epub_content` need **no changes** in this plan — bold markers and chapter headings are handled entirely in `epub.py`.
- Schema migrations are idempotent (`PRAGMA table_info` check before `ALTER TABLE`).
- **`BeautifulSoup` + `html.parser` treats `<meta>` as an HTML void element**, even when the source XML gives it a closing tag with inline text (e.g. `<meta ...>aut</meta>`). The text ends up as a *sibling* of the `<meta>` tag, not a child — `meta.get_text()` returns `""`. Any code reading such inline text must use `meta.next_sibling`, not `.get_text()`. This was verified against the real `bs4` version installed in this project's venv before writing this plan (see Task 2, Step 3) — do not "fix" it back to `.get_text()`.
- **`NavigableString` objects have a `.name` attribute equal to `None`** — `hasattr(node, "name")` is `True` for both tags *and* text nodes in `bs4`. Any "is this a tag or a text node" check must test `getattr(node, "name", None) is None`, never bare `hasattr(node, "name")`. (The existing `_extract_inline` helper from Plan 1 already gets this right — `if not hasattr(child, "name") or child.name is None:` — this plan's new code must match that pattern.)
- Activate the venv before running anything: `source .venv/bin/activate`.

---

## Task 1: `documents` schema — `volume_author`/`volume_illustrator`/`volume_publisher`/`volume_identifier`

**Files:**
- Modify: `translation_assistant/db.py` (idempotent migration loop — the same one Plan 1 Task 1 already extended with `volume_title`; `create_document`; `get_document`)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `Database.create_document(..., volume_author="", volume_illustrator="", volume_publisher="", volume_identifier="")`; `Database.get_document(doc_id)` now also includes these four keys.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_create_document_stores_volume_metadata(self, mem_db):
    doc_id = mem_db.create_document(
        "Ch 1",
        volume_author="Author Name",
        volume_illustrator="Illustrator Name",
        volume_publisher="Test Publisher",
        volume_identifier="urn:isbn:1234567890123",
    )
    meta = mem_db.get_document(doc_id)
    assert meta["volume_author"] == "Author Name"
    assert meta["volume_illustrator"] == "Illustrator Name"
    assert meta["volume_publisher"] == "Test Publisher"
    assert meta["volume_identifier"] == "urn:isbn:1234567890123"

def test_create_document_volume_metadata_defaults_empty(self, mem_db):
    doc_id = mem_db.create_document("Ch 1")
    meta = mem_db.get_document(doc_id)
    assert meta["volume_author"] == ""
    assert meta["volume_illustrator"] == ""
    assert meta["volume_publisher"] == ""
    assert meta["volume_identifier"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k volume_metadata -v`
Expected: FAIL with `TypeError: create_document() got an unexpected keyword argument 'volume_author'`

- [ ] **Step 3: Extend the migration, `create_document`, and `get_document`**

In `db.py`, extend the idempotent migration loop (the same list Plan 1 Task 1 added `volume_title` to):

```python
        for col, defn in [
            ("series_title",       "TEXT    NOT NULL DEFAULT ''"),
            ("series_order",       "INTEGER NOT NULL DEFAULT 0"),
            ("chapter_title",      "TEXT    NOT NULL DEFAULT ''"),
            ("volume_title",       "TEXT    NOT NULL DEFAULT ''"),
            ("volume_author",      "TEXT    NOT NULL DEFAULT ''"),
            ("volume_illustrator", "TEXT    NOT NULL DEFAULT ''"),
            ("volume_publisher",   "TEXT    NOT NULL DEFAULT ''"),
            ("volume_identifier",  "TEXT    NOT NULL DEFAULT ''"),
        ]:
```

Update `create_document`:

```python
    def create_document(self, title: str, *,
                        series_title: str = "",
                        series_order: int = 0,
                        chapter_title: str = "",
                        source_url: str = "",
                        volume_title: str = "",
                        volume_author: str = "",
                        volume_illustrator: str = "",
                        volume_publisher: str = "",
                        volume_identifier: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO documents (title, series_title, series_order, chapter_title, source_url, "
            "volume_title, volume_author, volume_illustrator, volume_publisher, volume_identifier) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, series_title, series_order, chapter_title, source_url,
             volume_title, volume_author, volume_illustrator, volume_publisher, volume_identifier),
        )
        self._conn.commit()
        return cur.lastrowid
```

Update `get_document`:

```python
    def get_document(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT id, title, series_title, series_order, chapter_title, "
            "source_language, created_at, updated_at, last_position, source_url, "
            "volume_title, volume_author, volume_illustrator, volume_publisher, volume_identifier "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Document {doc_id} not found")
        return dict(row)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -k volume_metadata -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_db.py` suite**

Run: `pytest tests/test_db.py -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add volume_author/illustrator/publisher/identifier columns"
```

---

## Task 2: `epub.open_book()` — book metadata extraction

**Files:**
- Modify: `translation_assistant/epub.py` (`open_book`)
- Test: `tests/test_epub.py`

**Interfaces:**
- Produces: `open_book()`'s return dict gains `"author"`, `"illustrator"`, `"publisher"`, `"identifier"` (all `str`, `""` when absent).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`. Note: this fixture's `<meta property="role">` tags carry their role as **inline text content** (`>aut<`), matching the real BookWalker sample files this whole feature was designed against — `bs4`+`html.parser` treats `<meta>` as a void element, so that text lands as the tag's *next sibling*, not as its content. This is exercised directly by `test_metadata_role_extraction_survives_void_meta_parsing` below; see the Global Constraints note on why `.get_text()` would silently return `""` here.

```python
_OPF_EPUB3_METADATA = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Test Volume</dc:title>
<dc:creator id="creator01">Author Name</dc:creator>
<meta refines="#creator01" property="role" scheme="marc:relators">aut</meta>
<dc:creator id="creator02">Illustrator Name</dc:creator>
<meta refines="#creator02" property="role" scheme="marc:relators">ill</meta>
<dc:publisher>Test Publisher</dc:publisher>
<dc:identifier id="uid">urn:isbn:1234567890123</dc:identifier>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine>
<itemref idref="ch1"/>
</spine>
</package>
"""


def _make_epub_with_metadata(tmp_path: Path) -> Path:
    path = tmp_path / "metadata.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3_METADATA)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML.replace(
            '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
        ))
        zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Hello.</p></body></html>")
    return path


class TestOpenBookMetadata:
    def test_metadata_role_extraction_survives_void_meta_parsing(self, tmp_path):
        book = open_book(_make_epub_with_metadata(tmp_path))
        assert book["author"] == "Author Name"
        assert book["illustrator"] == "Illustrator Name"

    def test_publisher_and_identifier(self, tmp_path):
        book = open_book(_make_epub_with_metadata(tmp_path))
        assert book["publisher"] == "Test Publisher"
        assert book["identifier"] == "urn:isbn:1234567890123"

    def test_missing_metadata_defaults_empty(self, tmp_path):
        book = open_book(_make_epub3(tmp_path))
        assert book["author"] == ""
        assert book["illustrator"] == ""
        assert book["publisher"] == ""
        assert book["identifier"] == ""

    def test_creator_without_role_meta_defaults_to_author(self, tmp_path):
        opf = _OPF_EPUB3_METADATA.replace(
            '<meta refines="#creator01" property="role" scheme="marc:relators">aut</meta>\n', ""
        )
        path = tmp_path / "no_role.epub"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", _CONTAINER_XML)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML.replace(
                '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
            ))
            zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Hello.</p></body></html>")
        book = open_book(path)
        assert book["author"] == "Author Name"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestOpenBookMetadata -v`
Expected: FAIL with `KeyError: 'author'`

- [ ] **Step 3: Implement metadata extraction**

Add to `translation_assistant/epub.py`:

```python
def _find_metadata(opf: BeautifulSoup) -> dict:
    """
    Extracts author/illustrator (from dc:creator + role-refining <meta>),
    publisher, and identifier from the OPF's <metadata> block.

    bs4's html.parser treats <meta> as an HTML void element, so
    <meta refines="#creator01" property="role" ...>aut</meta> parses with
    "aut" as the meta tag's *next sibling text node*, not its content --
    meta.get_text() would return "". Read the role via next_sibling instead.
    NavigableString objects have a .name attribute equal to None, so the
    "is this a tag" check must be `getattr(node, "name", None) is None`,
    not a bare hasattr check (which is True for text nodes too).
    """
    role_by_id: dict[str, str] = {}
    for meta in opf.find_all("meta", attrs={"property": "role"}):
        refines = meta.get("refines", "")
        if not refines.startswith("#"):
            continue
        sib = meta.next_sibling
        if sib is not None and getattr(sib, "name", None) is None:
            role_by_id[refines[1:]] = str(sib).strip()

    authors = []
    illustrators = []
    for creator in opf.find_all("dc:creator"):
        role = role_by_id.get(creator.get("id", ""), "aut")
        name = creator.get_text(strip=True)
        (illustrators if role == "ill" else authors).append(name)

    publisher_el = opf.find("dc:publisher")
    identifier_el = opf.find("dc:identifier")
    return {
        "author": ", ".join(authors),
        "illustrator": ", ".join(illustrators),
        "publisher": publisher_el.get_text(strip=True) if publisher_el else "",
        "identifier": identifier_el.get_text(strip=True) if identifier_el else "",
    }
```

In `open_book()`, call it and merge into the returned dict:

```python
        toc_entries = _read_toc(zf, opf, opf_dir)
        cover_href = _find_cover_href(opf, opf_dir)
        metadata = _find_metadata(opf)

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

        return {"title": title, "chapters": chapters, "cover_href": cover_href, **metadata}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestOpenBookMetadata -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (Plans 1 and 2's `open_book()` tests still pass — the new keys are additive)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): open_book() extracts author/illustrator/publisher/identifier"
```

---

## Task 3: Bold-span flattening on import (`**marker**`)

**Files:**
- Modify: `translation_assistant/epub.py` (`_extract_inline`)
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_extract_inline` (used by `extract_chapter_content` — `extract_chapter_text` was removed in Plan 2 Task 6) gains a `class="bold"` rule.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

Note: `extract_chapter_text` was removed in Plan 2 Task 6 — use `extract_chapter_content(path, href)[0]` (the `text` half of the returned tuple) instead, same as the retargeted `TestExtractChapterText` tests from that task.

```python
class TestBoldFlattening:
    def test_bold_span_wrapped_in_markers(self, tmp_path):
        body = '<p><span class="bold">emphasized text</span></p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_content(path, href)[0] == "**emphasized text**"

    def test_bold_span_mixed_with_plain_text(self, tmp_path):
        body = '<p>Before <span class="bold">bold part</span> after.</p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_content(path, href)[0] == "Before **bold part** after."

    def test_ruby_inside_bold_span(self, tmp_path):
        body = '<p><span class="bold"><ruby>漢字<rt>かんじ</rt></ruby></span></p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_content(path, href)[0] == "**漢字(かんじ)**"

    def test_tcy_span_unaffected_by_bold_handling(self, tmp_path):
        body = '<p>A<span class="tcy">!?</span>B</p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_content(path, href)[0] == "A!?B"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestBoldFlattening -v`
Expected: FAIL — `test_bold_span_wrapped_in_markers` and the mixed/ruby-nested variants get plain unwrapped text back (no `**`); `test_tcy_span_unaffected_by_bold_handling` should already pass (included to lock in the "no regression" behavior).

- [ ] **Step 3: Add the bold rule to `_extract_inline`**

In `translation_assistant/epub.py`, add one branch to `_extract_inline` (written in Plan 1 Task 5), between the `img` branch and the final `else`:

```python
def _extract_inline(node) -> str:
    """
    Recursively render a tag's text content:
      - <ruby>base<rt>reading</rt></ruby> -> "base(reading)"
      - <img alt="..."> -> alt text
      - class="bold" -> "**...**" (inline text convention, same approach as
        ruby -- the translator sees the markers and may wrap the matching
        English substring the same way if they want bold to survive export)
      - everything else recurses into children (so ruby/gaiji/bold still
        resolve when nested inside further tags).
    """
    parts = []
    for child in node.children:
        if not hasattr(child, "name") or child.name is None:
            parts.append(str(child))
            continue
        if child.name == "ruby":
            rb = child.find("rb")
            if rb is not None:
                base = rb.get_text()
            else:
                base = "".join(
                    str(c) for c in child.children
                    if not (hasattr(c, "name") and c.name in ("rt", "rp"))
                )
            rt = child.find("rt")
            reading = rt.get_text() if rt else ""
            parts.append(f"{base}({reading})" if reading else base)
        elif child.name == "img":
            alt = child.get("alt", "")
            if alt:
                parts.append(alt)
        elif "bold" in (child.get("class") or []):
            parts.append(f"**{_extract_inline(child)}**")
        else:
            parts.append(_extract_inline(child))
    return "".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestBoldFlattening -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (no regressions in ruby/gaiji/illustration/anchor-position tests from Plans 1-2 — `bold` is a new, independent branch)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): flatten bold spans to **marker** text on import"
```

---

## Task 4: Chapter heading + bold-to-`<b>` conversion on export

**Files:**
- Modify: `translation_assistant/epub.py` (`build_epub`, `_CHAPTER_TEMPLATE` usage)
- Test: `tests/test_epub.py`

**Interfaces:**
- Produces: `_paragraph_to_html(text: str) -> str` (new); `build_epub()` emits `<h1>{chapter_title}</h1>` per chapter and runs every `"text"` content item through `_paragraph_to_html` instead of bare `escape()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

```python
class TestChapterHeadingAndBold:
    def test_chapter_heading_emitted(self, tmp_path):
        result = build_epub("Vol", [("Chapter One", [("text", "Hello.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            xhtml = zf.read("OEBPS/text/chap1.xhtml").decode("utf-8")
        assert "<h1>Chapter One</h1>" in xhtml
        assert xhtml.index("<h1>") < xhtml.index("<p>Hello.</p>")

    def test_bold_marker_converted_to_b_tag(self, tmp_path):
        result = build_epub("Vol", [("Ch 1", [("text", "Before **bold** after.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            xhtml = zf.read("OEBPS/text/chap1.xhtml").decode("utf-8")
        assert "Before <b>bold</b> after." in xhtml

    def test_bold_marker_with_special_chars_escaped(self, tmp_path):
        result = build_epub("Vol", [("Ch 1", [("text", "**A & B**")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            xhtml = zf.read("OEBPS/text/chap1.xhtml").decode("utf-8")
        assert "<b>A &amp; B</b>" in xhtml

    def test_no_bold_marker_unaffected(self, tmp_path):
        result = build_epub("Vol", [("Ch 1", [("text", "Plain text.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            xhtml = zf.read("OEBPS/text/chap1.xhtml").decode("utf-8")
        assert "<p>Plain text.</p>" in xhtml
        assert "<b>" not in xhtml
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestChapterHeadingAndBold -v`
Expected: FAIL — no `<h1>` emitted; `**bold**` markers pass through `escape()` unconverted (literal `**bold**` appears in output instead of `<b>bold</b>`).

- [ ] **Step 3: Implement `_paragraph_to_html` and wire both changes into `build_epub`**

Add `import re` to the top-of-file imports. Add near the other module-level constants in `epub.py`:

```python
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _paragraph_to_html(text: str) -> str:
    """
    Escapes text for XML, converting **bold** markers to <b> tags.
    re.split with a capturing group returns alternating
    [plain, bold, plain, bold, ..., plain] -- odd indices are the matched
    bold runs.
    """
    parts = _BOLD_RE.split(text)
    escaped = []
    for i, part in enumerate(parts):
        piece = escape(part)
        escaped.append(f"<b>{piece}</b>" if i % 2 == 1 else piece)
    return "".join(escaped)
```

In `build_epub`'s per-chapter loop (written in Plan 2 Task 5), change the `"text"` branch and add the heading:

```python
        for i, (chapter_title, content_items, chapter_images) in enumerate(chapters, start=1):
            chap_id = f"chap{i}"
            href = f"text/chap{i}.xhtml"
            image_bytes_by_src = {img["src_path"]: img["data"] for img in chapter_images}
            written_images: dict[str, str] = {}

            body_parts = [f"<h1>{escape(chapter_title)}</h1>\n"]
            for kind, value in content_items:
                if kind == "text":
                    body_parts.append(f"<p>{_paragraph_to_html(value)}</p>\n")
                else:
                    src_path = value
                    if src_path not in written_images:
                        image_id += 1
                        ext = src_path.rsplit(".", 1)[-1] if "." in src_path else "img"
                        img_href = f"images/{image_id}.{ext}"
                        data = image_bytes_by_src.get(src_path)
                        if data is None:
                            continue
                        zf.writestr(f"OEBPS/{img_href}", data)
                        media_type = mimetypes.guess_type(src_path)[0] or "application/octet-stream"
                        manifest_items.append(
                            f'<item id="img{image_id}" href="{img_href}" media-type="{media_type}"/>'
                        )
                        written_images[src_path] = img_href
                    body_parts.append(f'<p><img src="../{written_images[src_path]}"/></p>\n')
```

(Only the `body_parts = [...]` initialization and the `"text"` branch's `escape(value)` -> `_paragraph_to_html(value)` change — everything else in the loop is unchanged from Plan 2 Task 5.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestChapterHeadingAndBold -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS — check `TestBuildEpub`/`TestBuildEpubImages`'s existing paragraph-content assertions still hold: they assert `"<p>{text}</p>"` substrings where `text` had no `**` markers, and `_paragraph_to_html` on a marker-free string is identical to plain `escape()`, so no change needed there.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): emit chapter heading and convert bold markers to <b> on export"
```

---

## Task 5: Book metadata in the exported OPF

**Files:**
- Modify: `translation_assistant/epub.py` (`build_epub`, `_OPF_TEMPLATE`)
- Test: `tests/test_epub.py`

**Interfaces:**
- Produces: `build_epub(..., creator: str = "", illustrator: str = "", publisher: str = "", identifier: str = "")`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

```python
class TestBuildEpubMetadata:
    def test_creator_and_illustrator_emitted_with_roles(self, tmp_path):
        result = build_epub(
            "Vol", [("Ch 1", [("text", "Hello.")], [])],
            creator="Author Name", illustrator="Illustrator Name",
        )
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:creator" in opf and "Author Name" in opf
        assert "Illustrator Name" in opf
        assert 'property="role"' in opf

    def test_publisher_emitted(self, tmp_path):
        result = build_epub("Vol", [("Ch 1", [("text", "Hello.")], [])], publisher="Test Publisher")
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:publisher>Test Publisher</dc:publisher>" in opf

    def test_identifier_used_when_given(self, tmp_path):
        result = build_epub(
            "Vol", [("Ch 1", [("text", "Hello.")], [])], identifier="urn:isbn:1234567890123",
        )
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "urn:isbn:1234567890123" in opf

    def test_blank_metadata_omits_tags(self, tmp_path):
        result = build_epub("Vol", [("Ch 1", [("text", "Hello.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:creator" not in opf
        assert "<dc:publisher" not in opf
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestBuildEpubMetadata -v`
Expected: FAIL — `build_epub()` raises `TypeError: unexpected keyword argument 'creator'`.

- [ ] **Step 3: Implement**

Update `_OPF_TEMPLATE` in `epub.py` to add two new placeholders:

```python
_OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{title}</dc:title>
<dc:language>{lang}</dc:language>
<dc:identifier id="uid">{identifier}</dc:identifier>
{creator_entries}
{publisher_entry}
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
```

Update `build_epub`'s signature and the OPF-assembly block at the end of the function:

```python
def build_epub(
    volume_title: str,
    chapters: list[tuple[str, list[tuple[str, str]], list[dict]]],
    *, language: str = "en",
    cover: dict | None = None,
    creator: str = "",
    illustrator: str = "",
    publisher: str = "",
    identifier: str = "",
) -> bytes:
    """
    ... (docstring from Plan 2 Task 5, plus:)
    creator/illustrator: author/illustrator names. When either is given, a
    dc:creator entry is emitted with a role-refining <meta> (aut/ill),
    matching the shape open_book() reads them from. Blank means omitted.
    publisher: dc:publisher text, omitted when blank.
    identifier: dc:identifier text (e.g. an ISBN urn). When blank, a
    generated urn:uuid is used instead -- unlike creator/publisher, the OPF
    always needs *some* unique identifier, so this one is never omitted,
    only ever substituted.
    """
    import uuid
    ...
```

Inside the function, right before assembling `opf` (after the cover-handling block from Plan 2 Task 5):

```python
        creator_entries = []
        if creator:
            creator_entries.append(f'<dc:creator id="creator-aut">{escape(creator)}</dc:creator>')
            creator_entries.append(
                '<meta refines="#creator-aut" property="role" scheme="marc:relators">aut</meta>'
            )
        if illustrator:
            creator_entries.append(f'<dc:creator id="creator-ill">{escape(illustrator)}</dc:creator>')
            creator_entries.append(
                '<meta refines="#creator-ill" property="role" scheme="marc:relators">ill</meta>'
            )
        publisher_entry = f"<dc:publisher>{escape(publisher)}</dc:publisher>" if publisher else ""

        opf = _OPF_TEMPLATE.format(
            title=escape(volume_title),
            lang=language,
            identifier=escape(identifier) if identifier else f"urn:uuid:{uuid.uuid4()}",
            manifest="\n".join(manifest_items),
            spine="\n".join(spine_items),
            cover_meta=cover_meta,
            creator_entries="\n".join(creator_entries),
            publisher_entry=publisher_entry,
        )
        zf.writestr("OEBPS/content.opf", opf)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestBuildEpubMetadata -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS — every prior test that calls `build_epub()` without `creator`/`illustrator`/`publisher`/`identifier` gets the same output as before (all four default to omitted/generated, matching Plans 1-2's behavior exactly).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): build_epub() emits creator/illustrator/publisher/identifier"
```

---

## Task 6: Wire metadata fields into `dlg_import_epub.py`

**Files:**
- Modify: `translation_assistant/ui/dlg_import_epub.py`
- Test: `tests/test_dlg_import_epub.py`

**Interfaces:**
- Consumes: `open_book()`'s new `author`/`illustrator`/`publisher`/`identifier` keys.
- Produces: four new `QLineEdit`s (`_author_edit`, `_illustrator_edit`, `_publisher_edit`, `_identifier_edit`), prefilled on browse, passed through to every `create_document()` call in the batch.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dlg_import_epub.py`:

```python
class TestImportEpubMetadataFields:
    def test_fields_prefilled_from_opf(self, qapp, mem_db, tmp_path, monkeypatch):
        from .test_epub import _OPF_EPUB3_METADATA, _NAV_XHTML as nav_xhtml
        path = tmp_path / "meta_vol.epub"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", _CONTAINER_XML)
            zf.writestr("OEBPS/content.opf", _OPF_EPUB3_METADATA)
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml.replace(
                '<li><a href="text/ch2.xhtml">Chapter 2</a></li>', ""
            ))
            zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Hello.</p></body></html>")
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._author_edit.text() == "Author Name"
        assert dlg._illustrator_edit.text() == "Illustrator Name"
        assert dlg._publisher_edit.text() == "Test Publisher"
        assert dlg._identifier_edit.text() == "urn:isbn:1234567890123"

    def test_fields_editable_and_applied_to_created_documents(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("S")
        dlg._volume_edit.setText("V1")
        dlg._author_edit.setText("Custom Author")
        dlg._illustrator_edit.setText("Custom Illustrator")
        dlg._publisher_edit.setText("Custom Publisher")
        dlg._identifier_edit.setText("urn:isbn:0000000000000")
        dlg._on_import()
        doc_id = mem_db.get_document_ids_by_series("S")[0]
        meta = mem_db.get_document(doc_id)
        assert meta["volume_author"] == "Custom Author"
        assert meta["volume_illustrator"] == "Custom Illustrator"
        assert meta["volume_publisher"] == "Custom Publisher"
        assert meta["volume_identifier"] == "urn:isbn:0000000000000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dlg_import_epub.py::TestImportEpubMetadataFields -v`
Expected: FAIL with `AttributeError: 'ImportEpubDialog' object has no attribute '_author_edit'`

- [ ] **Step 3: Add the fields and wire them through**

In `dlg_import_epub.py`'s `_build_input_page`, add after the `volume_row` block (before `layout.addWidget(QLabel("Chapters:"))`):

```python
        author_row = QHBoxLayout()
        author_row.addWidget(QLabel("Author:"))
        self._author_edit = QLineEdit()
        author_row.addWidget(self._author_edit, 1)
        layout.addLayout(author_row)

        illustrator_row = QHBoxLayout()
        illustrator_row.addWidget(QLabel("Illustrator:"))
        self._illustrator_edit = QLineEdit()
        illustrator_row.addWidget(self._illustrator_edit, 1)
        layout.addLayout(illustrator_row)

        publisher_row = QHBoxLayout()
        publisher_row.addWidget(QLabel("Publisher:"))
        self._publisher_edit = QLineEdit()
        publisher_row.addWidget(self._publisher_edit, 1)
        layout.addLayout(publisher_row)

        identifier_row = QHBoxLayout()
        identifier_row.addWidget(QLabel("ISBN:"))
        self._identifier_edit = QLineEdit()
        identifier_row.addWidget(self._identifier_edit, 1)
        layout.addLayout(identifier_row)
```

In `_on_browse`, after `self._volume_edit.setText(book["title"])`:

```python
        self._author_edit.setText(book.get("author", ""))
        self._illustrator_edit.setText(book.get("illustrator", ""))
        self._publisher_edit.setText(book.get("publisher", ""))
        self._identifier_edit.setText(book.get("identifier", ""))
```

In `_on_import`, pass the four fields into every `create_document()` call:

```python
        volume_author = self._author_edit.text().strip()
        volume_illustrator = self._illustrator_edit.text().strip()
        volume_publisher = self._publisher_edit.text().strip()
        volume_identifier = self._identifier_edit.text().strip()
```

(add this alongside the existing `series_title`/`volume_title` reads at the top of `_on_import`), then add the four kwargs to the `create_document(...)` call already inside the per-chapter loop:

```python
                doc_id = self._db.create_document(
                    ch["title"],
                    series_title=series_title,
                    series_order=next_order,
                    chapter_title=ch["title"],
                    volume_title=volume_title,
                    source_url=ch["href"],
                    volume_author=volume_author,
                    volume_illustrator=volume_illustrator,
                    volume_publisher=volume_publisher,
                    volume_identifier=volume_identifier,
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dlg_import_epub.py -v`
Expected: PASS — all tests, including Plans 1-2's original ones (the new fields default to `""` when a fixture's OPF has no metadata, matching `open_book()`'s defaults from Task 2).

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_import_epub.py tests/test_dlg_import_epub.py
git commit -m "feat(ui): ImportEpubDialog captures editable book metadata fields"
```

---

## Task 7: Book metadata in `_on_export_epub_series`

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (`_on_export_epub_series`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: the four new `documents` columns (Task 1), read off the first document of each volume group; `build_epub`'s new `creator`/`illustrator`/`publisher`/`identifier` params (Task 5).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py`, in `TestExportEpubSeries`:

```python
    def test_exported_epub_contains_metadata(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1",
            volume_author="Author Name", volume_illustrator="Illustrator Name",
            volume_publisher="Test Publisher", volume_identifier="urn:isbn:1234567890123",
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
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
        assert "Author Name" in opf
        assert "Illustrator Name" in opf
        assert "Test Publisher" in opf
        assert "urn:isbn:1234567890123" in opf
```

(Prefer the file's existing `from unittest.mock import patch` import over the inline `__import__` form, as noted in Plans 1-2.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_window.py -k exported_epub_contains_metadata -v`
Expected: FAIL — `build_epub()` is called without the metadata kwargs, so the OPF has none of these strings.

- [ ] **Step 3: Update `_on_export_epub_series`**

In the per-volume loop (written across Plans 1-2), read the four columns off the first document's metadata and pass them through to `build_epub()`. Add right after `cover = None` initialization inside the `for volume_title, vol_doc_ids in volumes.items():` loop:

```python
            cover = None
            volume_meta = None
            incomplete = False
            for doc_id in vol_doc_ids:
                doc_meta = self._db.get_document(doc_id)
                if volume_meta is None:
                    volume_meta = doc_meta
                ...
```

(`volume_meta` captures the first chapter's metadata row — same "first document in the volume group" rule already used for `cover` in Plan 2, kept consistent since these columns are denormalized onto every row and simply reading the first one is sufficient.)

Then update the `build_epub(...)` call at the end of the per-volume block:

```python
            dest.write_bytes(build_epub(
                volume_title, chapters, cover=cover,
                creator=volume_meta.get("volume_author", ""),
                illustrator=volume_meta.get("volume_illustrator", ""),
                publisher=volume_meta.get("volume_publisher", ""),
                identifier=volume_meta.get("volume_identifier", ""),
            ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main_window.py::TestExportEpubSeries -v`
Expected: PASS — including every test from Plans 1-2 in this class (fixtures without metadata columns set simply get `""` for all four, which `build_epub()` treats as "omit", matching prior behavior exactly).

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): Export Series EPUB… includes book metadata in the OPF"
```

---

## Task 8: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: PASS — all tests green, across Plans 1, 2, and 3.

- [ ] **Step 2: Manual smoke test against a real sample volume**

Run the app, import one of the two real files in `EPUB/` via **File → Import EPUB…**, confirm the Author/Illustrator/Publisher/ISBN fields prefill correctly from the real BookWalker metadata (both sample volumes have `dc:creator` entries with `aut`/`ill` roles per the design spec's recon — this is the real-world case the void-`<meta>`-parsing fix in Task 2 exists for). Translate a chapter with a `**bold**` marker showing in the source pane, mirror it in the translation, export, and open the resulting `.epub` to confirm the chapter starts with a heading and the bold text rendered as `<b>`. This step is exploratory — its purpose is to catch anything the synthetic fixtures couldn't (e.g. more `dc:creator` roles than `aut`/`ill` appearing in the wild, or reader-specific quirks in how `<h1>`/`<b>` render).

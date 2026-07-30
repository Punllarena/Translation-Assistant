# EPUB Import/Export (Text Only, Volume-Tracked) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import chapters from a purchased EPUB (one volume per import) into the existing document/series model, and export a translated series back out as one `.epub` file per volume.

**Architecture:** A new framework-agnostic `translation_assistant/epub.py` module (mirrors `scraper.py`'s parsing style) does all zip/XML work with stdlib `zipfile` + `xml.sax.saxutils.escape` plus the already-installed `beautifulsoup4` (`html.parser`). A new `dlg_import_epub.py` dialog (browse → configure → import → summary, same shape as `dlg_batch_import.py`) drives import. Export reuses the existing `_export_md_series`-style grouping in `main_widget.py`.

**Tech Stack:** Python 3, PySide6, sqlite3 (via `db.py`), `zipfile`, `beautifulsoup4` (`html.parser`) — no new dependencies.

## Global Constraints

- Never import `sqlite3` outside `db.py` (project-wide rule; `epub.py` and the dialog must go through `Database`).
- `core.py` stays framework-agnostic — no Qt imports, no zip/XML imports. `build_epub_paragraphs` belongs there; all zip/XML work belongs in `epub.py`.
- Schema migrations are idempotent — `PRAGMA table_info` check before every `ALTER TABLE`, exactly like every existing column in `_apply_schema()`.
- `series_order` is a global, monotonically increasing counter per series — never reset per volume.
- The two sample EPUBs in `EPUB/` (already gitignored) are for manual testing only; automated tests use synthetic EPUB fixtures built with `zipfile` in `tmp_path`.
- Activate the venv before running anything: `source .venv/bin/activate`.

---

## Task 1: `documents.volume_title` schema + `db.py` volume-scoped helpers

**Files:**
- Modify: `translation_assistant/db.py:99-107` (idempotent migration loop), `translation_assistant/db.py:286-297` (`create_document`), `translation_assistant/db.py:458-467` (`get_document`)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `Database.create_document(..., volume_title: str = "")`, `Database.get_document(doc_id) -> dict` (now includes `"volume_title"` key), `Database.get_volume_chapter_titles(series_title: str, volume_title: str) -> set[str]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py` (find the existing `create_document`/`get_document` test class and add alongside it):

```python
def test_create_document_stores_volume_title(self, mem_db):
    doc_id = mem_db.create_document(
        "Ch 1", series_title="My Series", volume_title="Volume 1", chapter_title="Ch 1"
    )
    meta = mem_db.get_document(doc_id)
    assert meta["volume_title"] == "Volume 1"

def test_create_document_volume_title_defaults_empty(self, mem_db):
    doc_id = mem_db.create_document("Ch 1")
    meta = mem_db.get_document(doc_id)
    assert meta["volume_title"] == ""

def test_get_volume_chapter_titles_empty_when_none(self, mem_db):
    assert mem_db.get_volume_chapter_titles("My Series", "Volume 1") == set()

def test_get_volume_chapter_titles_returns_titles_for_volume(self, mem_db):
    mem_db.create_document("d1", series_title="S", volume_title="V1", chapter_title="Ch 1")
    mem_db.create_document("d2", series_title="S", volume_title="V1", chapter_title="Ch 2")
    mem_db.create_document("d3", series_title="S", volume_title="V2", chapter_title="Ch 1")
    assert mem_db.get_volume_chapter_titles("S", "V1") == {"Ch 1", "Ch 2"}

def test_get_volume_chapter_titles_isolated_by_series(self, mem_db):
    mem_db.create_document("d1", series_title="S1", volume_title="V1", chapter_title="Ch 1")
    mem_db.create_document("d2", series_title="S2", volume_title="V1", chapter_title="Ch 1")
    assert mem_db.get_volume_chapter_titles("S1", "V1") == {"Ch 1"}
```

(Use the file's existing `mem_db` fixture — if `tests/test_db.py` doesn't already have one, check the top of the file for the standard in-memory `Database(":memory:", _conn=conn)` fixture pattern used elsewhere in the suite, e.g. `tests/test_dlg_new_series.py:15-20`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k volume_title or volume_chapter_titles -v`
Expected: FAIL — `create_document() got an unexpected keyword argument 'volume_title'` / `AttributeError: 'Database' object has no attribute 'get_volume_chapter_titles'`

- [ ] **Step 3: Add the migration, update `create_document`/`get_document`, add `get_volume_chapter_titles`**

In `db.py`, add to the idempotent migration loop at line ~100-104 (the existing `for col, defn in [...]` block that adds `series_title`/`series_order`/`chapter_title`):

```python
        for col, defn in [
            ("series_title",  "TEXT    NOT NULL DEFAULT ''"),
            ("series_order",  "INTEGER NOT NULL DEFAULT 0"),
            ("chapter_title", "TEXT    NOT NULL DEFAULT ''"),
            ("volume_title",  "TEXT    NOT NULL DEFAULT ''"),
        ]:
```

Update `create_document` (line ~286-297):

```python
    def create_document(self, title: str, *,
                        series_title: str = "",
                        series_order: int = 0,
                        chapter_title: str = "",
                        source_url: str = "",
                        volume_title: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO documents (title, series_title, series_order, chapter_title, source_url, volume_title) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, series_title, series_order, chapter_title, source_url, volume_title),
        )
        self._conn.commit()
        return cur.lastrowid
```

Update `get_document` (line ~458-467):

```python
    def get_document(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT id, title, series_title, series_order, chapter_title, "
            "source_language, created_at, updated_at, last_position, source_url, volume_title "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Document {doc_id} not found")
        return dict(row)
```

Add a new method near `get_series_chapters` (line ~417-422):

```python
    def get_volume_chapter_titles(self, series_title: str, volume_title: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT chapter_title FROM documents WHERE series_title = ? AND volume_title = ?",
            (series_title, volume_title),
        ).fetchall()
        return {r[0] for r in rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -k "volume_title or volume_chapter_titles" -v`
Expected: PASS

- [ ] **Step 5: Run the full test_db.py suite to check for regressions**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all existing tests still green — the new column is additive/idempotent)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add volume_title column and get_volume_chapter_titles"
```

---

## Task 2: `core.build_epub_paragraphs`

**Files:**
- Modify: `translation_assistant/core.py` (add after `build_markdown_translation`, ~line 484)
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: nothing new — same `raw_lines`/`translated_lines` shape as `build_markdown_translation`.
- Produces: `build_epub_paragraphs(raw_lines: list[str], translated_lines: list[str]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_core.py` (near the existing `build_markdown_translation` tests):

```python
def test_build_epub_paragraphs_basic():
    raw = ["%A", "%B"]
    tl = ["Alpha", "Beta"]
    assert build_epub_paragraphs(raw, tl) == ["Alpha", "Beta"]

def test_build_epub_paragraphs_merges_continuations():
    raw = ["%A", "$B"]
    tl = ["Alpha", "Beta"]
    assert build_epub_paragraphs(raw, tl) == ["Alpha Beta"]

def test_build_epub_paragraphs_skips_untranslated():
    raw = ["%A", "%B"]
    tl = ["", "Beta"]
    assert build_epub_paragraphs(raw, tl) == ["Beta"]

def test_build_epub_paragraphs_skips_blank_raw_lines():
    raw = ["%A", "", "%B"]
    tl = ["Alpha", "", "Beta"]
    assert build_epub_paragraphs(raw, tl) == ["Alpha", "Beta"]

def test_build_epub_paragraphs_empty_input():
    assert build_epub_paragraphs([], []) == []
```

Add `build_epub_paragraphs` to the existing `from translation_assistant.core import ...` block at the top of `tests/test_core.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core.py -k build_epub_paragraphs -v`
Expected: FAIL with `ImportError: cannot import name 'build_epub_paragraphs'`

- [ ] **Step 3: Implement**

Add to `core.py` right after `build_markdown_translation` (~line 484):

```python
# ---------------------------------------------------------------------------
# build_epub_paragraphs
# ---------------------------------------------------------------------------


def build_epub_paragraphs(raw_lines: list[str], translated_lines: list[str]) -> list[str]:
    """
    Same %/$ grouping and empty-group skipping as build_markdown_translation,
    but returns a list of paragraph strings instead of a Markdown document.
    """
    paragraphs: list[str] = []
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
                paragraphs.append(text)
            count += group_size
        else:
            count += 1
    return paragraphs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core.py -k build_epub_paragraphs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/core.py tests/test_core.py
git commit -m "feat(core): add build_epub_paragraphs"
```

---

## Task 3: `epub.open_book()` — EPUB3 nav parsing

**Files:**
- Create: `translation_assistant/epub.py`
- Test: `tests/test_epub.py`

**Interfaces:**
- Produces: `open_book(path: Path) -> dict` returning `{"title": str, "chapters": [{"order": int, "title": str, "href": str, "char_count": int}, ...]}`; `EpubError(ValueError)` for malformed input.

- [ ] **Step 1: Write the failing test with a synthetic EPUB3 fixture**

Create `tests/test_epub.py`:

```python
"""
Tests for translation_assistant.epub — pure unit tests against synthetic
EPUB fixtures built with zipfile. No dependency on the real sample files
in EPUB/ (gitignored, purchased content, manual-testing only).
"""
import zipfile
from pathlib import Path

import pytest

from translation_assistant.epub import EpubError, open_book


_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_OPF_EPUB3 = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Test Volume</dc:title>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
<item id="ch2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine>
<itemref idref="ch1"/>
<itemref idref="ch2"/>
</spine>
</package>
"""

_NAV_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body>
<nav epub:type="toc">
<ol>
<li><a href="text/ch1.xhtml">Chapter 1</a></li>
<li><a href="text/ch2.xhtml">Chapter 2</a></li>
</ol>
</nav>
</body>
</html>
"""


def _make_epub3(tmp_path: Path, *, ch1_body="<p>Hello world.</p>", ch2_body="<p>More text here.</p>") -> Path:
    path = tmp_path / "test.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML)
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{ch1_body}</body></html>")
        zf.writestr("OEBPS/text/ch2.xhtml", f"<html><body>{ch2_body}</body></html>")
    return path


class TestOpenBookEpub3:
    def test_title(self, tmp_path):
        book = open_book(_make_epub3(tmp_path))
        assert book["title"] == "Test Volume"

    def test_chapter_order_and_titles(self, tmp_path):
        book = open_book(_make_epub3(tmp_path))
        assert [c["title"] for c in book["chapters"]] == ["Chapter 1", "Chapter 2"]
        assert [c["order"] for c in book["chapters"]] == [1, 2]

    def test_chapter_href_resolved(self, tmp_path):
        book = open_book(_make_epub3(tmp_path))
        assert book["chapters"][0]["href"] == "OEBPS/text/ch1.xhtml"

    def test_char_count(self, tmp_path):
        book = open_book(_make_epub3(tmp_path, ch1_body="<p>Hello world.</p>"))
        assert book["chapters"][0]["char_count"] == len("Hello world.")

    def test_not_a_zip_raises(self, tmp_path):
        path = tmp_path / "bad.epub"
        path.write_text("not a zip")
        with pytest.raises(EpubError):
            open_book(path)

    def test_missing_container_xml_raises(self, tmp_path):
        path = tmp_path / "bad.epub"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
        with pytest.raises(EpubError):
            open_book(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'translation_assistant.epub'`

- [ ] **Step 3: Implement `epub.py` with `open_book()` (EPUB3 path only for now)**

Create `translation_assistant/epub.py`:

```python
"""
EPUB import/export — framework-agnostic (no Qt, no db import), mirrors the
parsing style of scraper.py. Zip/XML handling only via stdlib zipfile +
xml.sax.saxutils.escape and the already-installed beautifulsoup4.
"""
import posixpath
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup


class EpubError(ValueError):
    """Raised when an EPUB file can't be parsed."""


def _read(zf: zipfile.ZipFile, path: str) -> str:
    try:
        return zf.read(path).decode("utf-8")
    except KeyError as exc:
        raise EpubError(f"Missing file in EPUB: {path}") from exc


def _resolve(base_dir: str, href: str) -> str:
    """Resolve an href (may carry a #fragment) against base_dir, inside the zip."""
    href = href.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(base_dir, href))


def open_book(path: Path) -> dict:
    """
    Returns {"title": str, "chapters": [{"order": int, "title": str,
    "href": str, "char_count": int}, ...]} in TOC order. hrefs are resolved
    to full zip-internal paths.

    Raises EpubError if the file isn't a zip / has no OPF / has neither an
    EPUB3 nav doc nor an EPUB2 toc.ncx.
    """
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise EpubError(f"Not a valid EPUB (bad zip): {path}") from exc

    with zf:
        container = BeautifulSoup(_read(zf, "META-INF/container.xml"), "html.parser")
        rootfile = container.find("rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise EpubError("container.xml has no rootfile")
        opf_path = rootfile["full-path"]
        opf_dir = posixpath.dirname(opf_path)

        opf = BeautifulSoup(_read(zf, opf_path), "html.parser")
        title_el = opf.find("dc:title")
        title = title_el.get_text(strip=True) if title_el else ""

        toc_entries = _read_toc(zf, opf, opf_dir)

        chapters = []
        for order, (chap_title, href) in enumerate(toc_entries, start=1):
            try:
                xhtml = _read(zf, href)
            except EpubError:
                continue  # broken TOC entry — skip rather than fail the whole import
            char_count = len(BeautifulSoup(xhtml, "html.parser").get_text().strip())
            chapters.append({
                "order": order, "title": chap_title, "href": href, "char_count": char_count,
            })

        return {"title": title, "chapters": chapters}


def _read_toc(zf: zipfile.ZipFile, opf: BeautifulSoup, opf_dir: str) -> list[tuple[str, str]]:
    """Returns [(chapter_title, resolved_href), ...] in TOC order."""
    nav_item = opf.find("item", attrs={"properties": lambda v: v and "nav" in v.split()})
    if nav_item is not None:
        nav_href = _resolve(opf_dir, nav_item["href"])
        nav_soup = BeautifulSoup(_read(zf, nav_href), "html.parser")
        nav_dir = posixpath.dirname(nav_href)
        toc_nav = nav_soup.find("nav")
        if toc_nav is None:
            raise EpubError("EPUB3 nav document has no <nav> element")
        return [
            (a.get_text(strip=True), _resolve(nav_dir, a["href"]))
            for a in toc_nav.find_all("a") if a.get("href")
        ]

    ncx_item = next(
        (item for item in opf.find_all("item")
         if item.get("media-type") == "application/x-dtbncx+xml"),
        None,
    )
    if ncx_item is None:
        raise EpubError("No EPUB3 nav doc and no EPUB2 toc.ncx found")
    ncx_href = _resolve(opf_dir, ncx_item["href"])
    ncx_soup = BeautifulSoup(_read(zf, ncx_href), "html.parser")
    ncx_dir = posixpath.dirname(ncx_href)
    entries = []
    for navpoint in ncx_soup.find_all("navpoint"):
        content_el = navpoint.find("content")
        if content_el is None or not content_el.get("src"):
            continue
        label_el = navpoint.find("text")
        title = label_el.get_text(strip=True) if label_el else ""
        entries.append((title, _resolve(ncx_dir, content_el["src"])))
    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (all `TestOpenBookEpub3` tests)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): open_book() EPUB3 nav parsing"
```

---

## Task 4: `epub.open_book()` — EPUB2 `toc.ncx` fallback

**Files:**
- Modify: `translation_assistant/epub.py` (`_read_toc` already written in Task 3 — this task only adds test coverage confirming the fallback branch)
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: `_read_toc` from Task 3 (already handles both branches — this task verifies the EPUB2 branch with a dedicated fixture).

- [ ] **Step 1: Write the failing test with a synthetic EPUB2 fixture**

Add to `tests/test_epub.py`:

```python
_OPF_EPUB2 = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Test Volume EPUB2</dc:title>
</metadata>
<manifest>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine toc="ncx">
<itemref idref="ch1"/>
</spine>
</package>
"""

_TOC_NCX = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<navMap>
<navPoint id="np1"><navLabel><text>Chapter 1</text></navLabel><content src="text/ch1.xhtml"/></navPoint>
</navMap>
</ncx>
"""


def _make_epub2(tmp_path: Path) -> Path:
    path = tmp_path / "test2.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB2)
        zf.writestr("OEBPS/toc.ncx", _TOC_NCX)
        zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Hello.</p></body></html>")
    return path


class TestOpenBookEpub2:
    def test_title(self, tmp_path):
        book = open_book(_make_epub2(tmp_path))
        assert book["title"] == "Test Volume EPUB2"

    def test_chapter_from_ncx(self, tmp_path):
        book = open_book(_make_epub2(tmp_path))
        assert [c["title"] for c in book["chapters"]] == ["Chapter 1"]
        assert book["chapters"][0]["href"] == "OEBPS/text/ch1.xhtml"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestOpenBookEpub2 -v`
Expected: These should actually already PASS if Task 3's `_read_toc` fallback branch is correct — this step is a verification, not a red step, because the implementation was written in Task 3 to handle both branches at once. If it fails, the `ncx` branch in `_read_toc` has a bug; fix it now.

- [ ] **Step 3: Run full `test_epub.py` to confirm no regressions**

Run: `pytest tests/test_epub.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_epub.py
git commit -m "test(epub): cover EPUB2 toc.ncx fallback in open_book()"
```

---

## Task 5: `epub.extract_chapter_text()` — ruby, gaiji, standalone illustration

**Files:**
- Modify: `translation_assistant/epub.py`
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `extract_chapter_text(path: Path, href: str) -> str`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

```python
from translation_assistant.epub import extract_chapter_text


def _make_chapter_epub(tmp_path: Path, body: str) -> tuple[Path, str]:
    """Single-chapter EPUB3 fixture; returns (path, resolved chapter href)."""
    path = tmp_path / "chapter_test.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML)
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{body}</body></html>")
        zf.writestr("OEBPS/text/ch2.xhtml", "<html><body><p>Filler.</p></body></html>")
    return path, "OEBPS/text/ch1.xhtml"


class TestExtractChapterText:
    def test_plain_paragraphs_joined_by_newline(self, tmp_path):
        path, href = _make_chapter_epub(tmp_path, "<p>First.</p><p>Second.</p>")
        assert extract_chapter_text(path, href) == "First.\nSecond."

    def test_ruby_flattened_to_base_reading(self, tmp_path):
        body = "<p><ruby>漢字<rt>かんじ</rt></ruby>です。</p>"
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_text(path, href) == "漢字(かんじ)です。"

    def test_gaiji_img_alt_folded_into_text(self, tmp_path):
        body = '<p>あ<img class="gaiji-line" src="g.png" alt="〜"/>い</p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_text(path, href) == "あ〜い"

    def test_standalone_illustration_paragraph_skipped(self, tmp_path):
        body = '<p>Before.</p><p><img class="fit" src="pic.png"/></p><p>After.</p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_text(path, href) == "Before.\nAfter."

    def test_ruby_nested_inside_span(self, tmp_path):
        body = '<p><span class="bold"><ruby>漢字<rt>かんじ</rt></ruby></span></p>'
        path, href = _make_chapter_epub(tmp_path, body)
        assert extract_chapter_text(path, href) == "漢字(かんじ)"

    def test_no_paragraphs_returns_empty_string(self, tmp_path):
        path, href = _make_chapter_epub(tmp_path, "<div>No p tags here</div>")
        assert extract_chapter_text(path, href) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestExtractChapterText -v`
Expected: FAIL with `ImportError: cannot import name 'extract_chapter_text'`

- [ ] **Step 3: Implement `extract_chapter_text` and its inline-text helpers**

Add to `translation_assistant/epub.py`:

```python
def extract_chapter_text(path: Path, href: str) -> str:
    """
    Reads the given xhtml from the zip, walks <p> tags, and returns
    paragraphs joined by "\\n" — ready for core.build_new_file().

    Per <p>, text is built by:
      - <ruby>base<rt>reading</rt></ruby>  -> "base(reading)"
      - inline <img alt="..."> (non-empty alt) -> alt text (gaiji glyph
        substitution — some publishers render a character like the wave
        dash as an image; skipping this would silently drop it).
      - a <p> whose only meaningful child is a single <img> (a standalone
        illustration paragraph) is skipped entirely — no placeholder
        emitted. Illustration preservation is a follow-up feature; for
        this module, dropping them matches today's behavior for every
        other plain-text source in the app.
    """
    with zipfile.ZipFile(path) as zf:
        xhtml = _read(zf, href)
    soup = BeautifulSoup(xhtml, "html.parser")
    paragraphs = [text for p in soup.find_all("p") if (text := _para_text(p))]
    return "\n".join(paragraphs)


def _is_standalone_illustration(p) -> bool:
    """True if a <p>'s only meaningful child is a single <img>."""
    children = [c for c in p.children if not (isinstance(c, str) and not c.strip())]
    return len(children) == 1 and getattr(children[0], "name", None) == "img"


def _para_text(p) -> str:
    if _is_standalone_illustration(p):
        return ""
    return _extract_inline(p).strip()


def _extract_inline(node) -> str:
    """
    Recursively render a tag's text content:
      - <ruby>base<rt>reading</rt></ruby> -> "base(reading)"
      - <img alt="..."> -> alt text
      - everything else recurses into children (so ruby/gaiji still resolve
        when nested inside e.g. a <span>).
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
        else:
            parts.append(_extract_inline(child))
    return "".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestExtractChapterText -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (no regressions in `open_book` tests)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): extract_chapter_text with ruby/gaiji/illustration handling"
```

---

## Task 6: `epub.build_epub()` — export + round-trip

**Files:**
- Modify: `translation_assistant/epub.py`
- Test: `tests/test_epub.py`

**Interfaces:**
- Consumes: `open_book`, `extract_chapter_text` (this task's round-trip test re-parses `build_epub()`'s own output with them).
- Produces: `build_epub(volume_title: str, chapters: list[tuple[str, list[str]]], *, language: str = "en") -> bytes`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_epub.py`:

```python
from translation_assistant.epub import build_epub


class TestBuildEpub:
    def test_returns_bytes(self):
        result = build_epub("My Volume", [("Chapter 1", ["Hello.", "World."])])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_is_valid_zip(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", ["Hello."])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        assert zipfile.is_zipfile(out)

    def test_mimetype_is_first_entry_uncompressed(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", ["Hello."])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            info = zf.infolist()[0]
            assert info.filename == "mimetype"
            assert info.compress_type == zipfile.ZIP_STORED

    def test_round_trip_title_and_chapters(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", ["Hello world."]), ("Chapter 2", ["Second chapter."])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        book = open_book(out)
        assert book["title"] == "My Volume"
        assert [c["title"] for c in book["chapters"]] == ["Chapter 1", "Chapter 2"]

    def test_round_trip_paragraph_text_survives(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", ["Hello world.", "Second paragraph."])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        book = open_book(out)
        href = book["chapters"][0]["href"]
        text = extract_chapter_text(out, href)
        assert text == "Hello world.\nSecond paragraph."

    def test_xml_special_characters_escaped(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", ["A & B < C > D"])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        book = open_book(out)
        href = book["chapters"][0]["href"]
        assert extract_chapter_text(out, href) == "A & B < C > D"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_epub.py::TestBuildEpub -v`
Expected: FAIL with `ImportError: cannot import name 'build_epub'`

- [ ] **Step 3: Implement `build_epub`**

Add to `translation_assistant/epub.py` (add `import io` and `from xml.sax.saxutils import escape` to the top-of-file imports):

```python
_CONTAINER_XML_OUT = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{title}</dc:title>
<dc:language>{lang}</dc:language>
<dc:identifier id="uid">{identifier}</dc:identifier>
</metadata>
<manifest>
{manifest}
</manifest>
<spine>
{spine}
</spine>
</package>
"""

_NAV_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}">
<head><title>Table of Contents</title></head>
<body>
<nav epub:type="toc">
<ol>
{items}
</ol>
</nav>
</body>
</html>
"""

_CHAPTER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head><title>{title}</title></head>
<body>
{body}</body>
</html>
"""


def build_epub(volume_title: str, chapters: list[tuple[str, list[str]]],
               *, language: str = "en") -> bytes:
    """
    chapters: [(chapter_title, paragraphs), ...] in output order.
    Assembles a minimal valid EPUB3 zip in memory using stdlib zipfile +
    xml.sax.saxutils.escape — no new dependency. mimetype is stored
    uncompressed as the first entry (required by the EPUB spec so readers
    can identify the format without inflating the zip).

    ponytail: no stylesheet is generated — reader default styling only.
    """
    import uuid

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML_OUT)

        manifest_items = []
        spine_items = []
        nav_lis = []
        for i, (chapter_title, paragraphs) in enumerate(chapters, start=1):
            chap_id = f"chap{i}"
            href = f"text/chap{i}.xhtml"
            body = "".join(f"<p>{escape(p)}</p>\n" for p in paragraphs)
            xhtml = _CHAPTER_TEMPLATE.format(title=escape(chapter_title), body=body, lang=language)
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

        opf = _OPF_TEMPLATE.format(
            title=escape(volume_title),
            lang=language,
            identifier=f"urn:uuid:{uuid.uuid4()}",
            manifest="\n".join(manifest_items),
            spine="\n".join(spine_items),
        )
        zf.writestr("OEBPS/content.opf", opf)

    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub.py::TestBuildEpub -v`
Expected: PASS

- [ ] **Step 5: Run the full `test_epub.py` file**

Run: `pytest tests/test_epub.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/epub.py tests/test_epub.py
git commit -m "feat(epub): build_epub() EPUB3 export with round-trip verified"
```

---

## Task 7: `dlg_import_epub.ImportEpubDialog`

**Files:**
- Create: `translation_assistant/ui/dlg_import_epub.py`
- Test: `tests/test_dlg_import_epub.py`

**Interfaces:**
- Consumes: `epub.open_book`, `epub.extract_chapter_text`, `core.build_new_file`, `core.parse_file_content`, `core.lines_to_db_rows`, `Database.get_series_list`, `Database.get_next_series_order`, `Database.get_volume_chapter_titles`, `Database.create_document(..., volume_title=...)`, `Database.save_lines`.
- Produces: `ImportEpubDialog(db, parent=None)` — a `QDialog` with `_book: dict | None`, `_book_path: Path | None`, `_series_edit: QLineEdit`, `_volume_edit: QLineEdit`, `_chapter_list: QListWidget`, `_on_browse()`, `_on_import()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dlg_import_epub.py`. This follows the same "bypass `exec()`, call internal methods directly" pattern as `tests/test_dlg_new_series.py:1-4`, and reuses the `TestOpenBookEpub3`-style synthetic-EPUB builder from `tests/test_epub.py`.

```python
"""
Tests for ImportEpubDialog.
All tests bypass exec() — call internal methods directly and inspect state.
Synthetic EPUB fixtures only (EPUB/ sample files are gitignored, manual-test only).
"""
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from translation_assistant.db import Database
from translation_assistant.ui.dlg_import_epub import ImportEpubDialog

from .test_epub import _CONTAINER_XML, _OPF_EPUB3, _NAV_XHTML


@pytest.fixture
def mem_db(qapp):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    return db


def _make_epub(tmp_path: Path, *, ch1="<p>" + "A" * 600 + "。</p>", ch2="<p>Short.</p>") -> Path:
    """ch1 defaults to >=500 chars (default-checked); ch2 defaults short (unchecked)."""
    path = tmp_path / "vol.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", _NAV_XHTML)
        zf.writestr("OEBPS/text/ch1.xhtml", f"<html><body>{ch1}</body></html>")
        zf.writestr("OEBPS/text/ch2.xhtml", f"<html><body>{ch2}</body></html>")
    return path


class TestImportEpubDialog:
    def test_instantiates(self, qapp, mem_db):
        dlg = ImportEpubDialog(mem_db)
        assert dlg is not None

    def test_browse_populates_series_and_volume_fields(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._series_edit.text() == "Test Volume"
        assert dlg._volume_edit.text() == "Test Volume"

    def test_long_chapter_default_checked(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._chapter_list.item(0).checkState() == Qt.CheckState.Checked

    def test_short_chapter_default_unchecked(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        assert dlg._chapter_list.item(1).checkState() == Qt.CheckState.Unchecked

    def test_import_creates_documents_with_volume_title(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("My Series")
        dlg._volume_edit.setText("Volume 1")
        dlg._chapter_list.item(1).setCheckState(Qt.CheckState.Checked)  # include the short one too
        dlg._on_import()
        titles = mem_db.get_volume_chapter_titles("My Series", "Volume 1")
        assert titles == {"Chapter 1", "Chapter 2"}

    def test_import_series_order_increments_from_next(self, qapp, mem_db, tmp_path, monkeypatch):
        mem_db.create_document("existing", series_title="My Series", series_order=5)
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg = ImportEpubDialog(mem_db)
        dlg._on_browse()
        dlg._series_edit.setText("My Series")
        dlg._volume_edit.setText("Volume 1")
        dlg._on_import()
        doc_ids = mem_db.get_document_ids_by_series("My Series")
        orders = [mem_db.get_document(d)["series_order"] for d in doc_ids]
        assert orders == [5, 6]  # existing doc keeps 5; new chapter (ch1 only — ch2 unchecked) gets 6

    def test_reimport_skips_already_imported_chapter(self, qapp, mem_db, tmp_path, monkeypatch):
        path = _make_epub(tmp_path)
        monkeypatch.setattr(
            "translation_assistant.ui.dlg_import_epub.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(path), ""),
        )
        dlg1 = ImportEpubDialog(mem_db)
        dlg1._on_browse()
        dlg1._series_edit.setText("My Series")
        dlg1._volume_edit.setText("Volume 1")
        dlg1._on_import()

        dlg2 = ImportEpubDialog(mem_db)
        dlg2._on_browse()
        dlg2._series_edit.setText("My Series")
        dlg2._volume_edit.setText("Volume 1")
        dlg2._chapter_list.item(1).setCheckState(Qt.CheckState.Checked)
        dlg2._on_import()

        doc_ids = mem_db.get_document_ids_by_series("My Series")
        assert len(doc_ids) == 2  # Chapter 1 not duplicated; Chapter 2 added once
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dlg_import_epub.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'translation_assistant.ui.dlg_import_epub'`

- [ ] **Step 3: Implement `dlg_import_epub.py`**

Create `translation_assistant/ui/dlg_import_epub.py`:

```python
"""
Import EPUB Dialog — parses a purchased EPUB volume and imports its
chapters into the existing document/series model.
Same browse -> configure -> import -> summary shape as dlg_batch_import.py.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCompleter, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from translation_assistant.core import build_new_file, lines_to_db_rows, parse_file_content
from translation_assistant.db import Database
from translation_assistant.epub import EpubError, extract_chapter_text, open_book

_DEFAULT_CHECK_THRESHOLD = 500


class ImportEpubDialog(QDialog):

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._book_path: Path | None = None
        self._book: dict | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Import EPUB")
        self.setMinimumSize(480, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_input_page())
        self._stack.addWidget(self._build_summary_page())

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        file_row = QHBoxLayout()
        self._file_label = QLabel("No file selected.")
        self._file_label.setWordWrap(True)
        file_row.addWidget(self._file_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Series title:"))
        self._series_edit = QLineEdit()
        series_names = self._db.get_series_list()
        if series_names:
            completer = QCompleter(series_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self._series_edit.setCompleter(completer)
        series_row.addWidget(self._series_edit, 1)
        layout.addLayout(series_row)

        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Volume title:"))
        self._volume_edit = QLineEdit()
        volume_row.addWidget(self._volume_edit, 1)
        layout.addLayout(volume_row)

        layout.addWidget(QLabel("Chapters:"))
        self._chapter_list = QListWidget()
        layout.addWidget(self._chapter_list, 1)

        self._import_btn = QPushButton("Import")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)
        layout.addWidget(self._import_btn)

        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._summary_header = QLabel()
        layout.addWidget(self._summary_header)

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._summary_label)
        scroll.setMinimumHeight(120)
        layout.addWidget(scroll, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        return page

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select EPUB File", "", "EPUB files (*.epub)")
        if not path:
            return
        try:
            book = open_book(Path(path))
        except EpubError as exc:
            QMessageBox.critical(self, "Import Error", f"Could not read this EPUB:\n{exc}")
            return

        self._book_path = Path(path)
        self._book = book
        self._file_label.setText(str(self._book_path))
        self._series_edit.setText(book["title"])
        self._volume_edit.setText(book["title"])

        self._chapter_list.clear()
        for ch in book["chapters"]:
            item = QListWidgetItem(f"{ch['order']}. {ch['title']}  ({ch['char_count']} chars)")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            item.setCheckState(
                Qt.CheckState.Checked if ch["char_count"] >= _DEFAULT_CHECK_THRESHOLD
                else Qt.CheckState.Unchecked
            )
            self._chapter_list.addItem(item)
        self._import_btn.setEnabled(bool(book["chapters"]))

    def _on_import(self) -> None:
        if self._book is None or self._book_path is None:
            return
        series_title = self._series_edit.text().strip()
        volume_title = self._volume_edit.text().strip()

        already_imported = self._db.get_volume_chapter_titles(series_title, volume_title)
        next_order = self._db.get_next_series_order(series_title)

        imported = []
        skipped = []
        errors = []
        for i in range(self._chapter_list.count()):
            item = self._chapter_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            ch = item.data(Qt.ItemDataRole.UserRole)
            if ch["title"] in already_imported:
                skipped.append(ch["title"])
                continue
            try:
                text = extract_chapter_text(self._book_path, ch["href"])
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
                next_order += 1
                imported.append(ch["title"])
            except Exception as exc:
                errors.append((ch["title"], str(exc)))

        self._show_summary(imported, skipped, errors)

    def _show_summary(self, imported: list[str], skipped: list[str], errors: list[tuple[str, str]]) -> None:
        if imported:
            self._summary_header.setText("<b>Import complete.</b>")
        else:
            self._summary_header.setText("<b>Import finished — nothing new imported.</b>")

        lines = [
            f"Imported: {len(imported)}",
            f"Skipped:  {len(skipped)}  (already imported)",
            f"Errors:   {len(errors)}",
        ]
        if skipped:
            lines.append("")
            lines.append("Skipped: " + ", ".join(skipped))
        if errors:
            lines.append("")
            for title, msg in errors:
                lines.append(f"Error: {title} — {msg}")

        self._summary_label.setText("\n".join(lines))
        self._stack.setCurrentIndex(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dlg_import_epub.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_import_epub.py tests/test_dlg_import_epub.py
git commit -m "feat(ui): ImportEpubDialog — browse/configure/import/summary"
```

---

## Task 8: Wire "Import EPUB…" into the menu

**Files:**
- Modify: `translation_assistant/ui/main_widget.py:189-190` (`_build_actions`, next to `action_batch_import`), `translation_assistant/ui/main_widget.py:1101-1105` (`_on_batch_import`, add `_on_import_epub` alongside)
- Modify: `translation_assistant/ui/combined_window.py:104-105` (menu wiring)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces: `TranslationAssistantWidget.action_import_epub`, `TranslationAssistantWidget._on_import_epub()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py`, in the `TestInstantiation` class (next to `test_has_import_action`, line ~63-64):

```python
    def test_has_import_epub_action(self, win):
        assert hasattr(win, "action_import_epub")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_window.py -k has_import_epub_action -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add the action and handler**

In `main_widget.py`, add after `action_batch_import` (line ~189-190):

```python
        self.action_import_epub = QAction("Import EPUB…", self)
        self.action_import_epub.triggered.connect(self._on_import_epub)
```

Add the handler after `_on_batch_import` (line ~1101-1105):

```python
    def _on_import_epub(self) -> None:
        from translation_assistant.ui.dlg_import_epub import ImportEpubDialog
        with self._topmost_suspended():
            dlg = ImportEpubDialog(self._db, parent=self)
            dlg.exec()
```

In `combined_window.py`, add after `file_menu.addAction(ta.action_batch_import)` (line 105):

```python
        file_menu.addAction(ta.action_batch_import)
        file_menu.addAction(ta.action_import_epub)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_window.py -k has_import_epub_action -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/test_main_window.py
git commit -m "feat(ui): wire Import EPUB… into the File menu"
```

---

## Task 9: Export series to EPUB — `_on_export_epub_series`

**Files:**
- Modify: `translation_assistant/ui/main_widget.py:189-190` or near the md export actions at line ~250-264 (`_build_actions`), near `_export_md_series` at line ~1148-1208 (new handler)
- Modify: `translation_assistant/ui/combined_window.py:107-113` (menu wiring)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `epub.build_epub`, `core.build_epub_paragraphs`, `core.db_rows_to_arrays`, `core.calculate_progress`, `Database.get_document_ids_by_series`, `Database.get_document`, `Database.get_lines`, `_sanitize_filename` (`main_widget.py:24-25`).
- Produces: `TranslationAssistantWidget.action_export_epub_series`, `_on_export_epub_series()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_window.py`, in `TestImportExport` (or a new class right after it):

```python
class TestExportEpubSeries:
    def _load_translated_doc(self, win, mem_db=None):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        return doc_id

    def test_writes_one_epub_per_volume(self, win, tmp_path, monkeypatch):
        self._load_translated_doc(win)
        win._doc_id = win._db.get_document_ids_by_series("S")[0]
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "translation_assistant.ui.main_widget.QMessageBox.information"
        ):
            win._on_export_epub_series()
        assert (tmp_path / "S" / "Vol 1.epub").exists()

    def test_skips_whole_volume_if_any_chapter_incomplete(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": ""},  # untranslated
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
        assert not (tmp_path / "S" / "Vol 1.epub").exists()

    def test_skips_existing_file(self, win, tmp_path, monkeypatch):
        self._load_translated_doc(win)
        win._doc_id = win._db.get_document_ids_by_series("S")[0]
        series_dir = tmp_path / "S"
        series_dir.mkdir()
        (series_dir / "Vol 1.epub").write_bytes(b"existing content")
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "translation_assistant.ui.main_widget.QMessageBox.information"
        ):
            win._on_export_epub_series()
        assert (series_dir / "Vol 1.epub").read_bytes() == b"existing content"
```

(Use a real top-of-file `from unittest.mock import patch` import instead of the inline `__import__` if `test_main_window.py` doesn't already import it — check the existing `from unittest.mock import patch` at line 10 and use that directly: `with patch("translation_assistant.ui.main_widget.QMessageBox.information"):`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main_window.py::TestExportEpubSeries -v`
Expected: FAIL with `AttributeError: 'TranslationAssistantWidget' object has no attribute '_on_export_epub_series'`

- [ ] **Step 3: Add the action and handler**

In `main_widget.py`, add after `action_export_md_ruby_series` (line ~262-264):

```python
        self.action_export_epub_series = QAction("Export Series EPUB…", self)
        self.action_export_epub_series.triggered.connect(self._on_export_epub_series)
        self.action_export_epub_series.setEnabled(False)
```

Enable it alongside the markdown series actions in `_finish_load` (line ~614-616):

```python
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
        self.action_export_epub_series.setEnabled(_has_series)
```

Add the handler after `_export_md_series` (line ~1148-1192), before `_on_export_md_tl_doc`:

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

        from translation_assistant.core import build_epub_paragraphs, calculate_progress, db_rows_to_arrays
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
            incomplete = False
            for doc_id in vol_doc_ids:
                doc_meta = self._db.get_document(doc_id)
                rows = self._db.get_lines(doc_id)
                raw_lines, translated_lines = db_rows_to_arrays(rows)
                pct, _ = calculate_progress(raw_lines, translated_lines)
                if pct < 100:
                    incomplete = True
                    break
                heading = doc_meta.get("chapter_title") or doc_meta.get("title", "")
                chapters.append((heading, build_epub_paragraphs(raw_lines, translated_lines)))
            if incomplete:
                skipped_incomplete += 1
                continue
            filename = f"{_sanitize_filename(volume_title) or 'volume'}.epub"
            dest = folder / filename
            if dest.exists():
                skipped_exists += 1
                continue
            dest.write_bytes(build_epub(volume_title, chapters))
            written += 1

        lines = [f"Exported {written} volume(s) to:\n{folder}"]
        if skipped_exists:
            lines.append(f"{skipped_exists} volume(s) skipped (file already exists)")
        if skipped_incomplete:
            lines.append(f"{skipped_incomplete} volume(s) skipped (incomplete translation)")
        QMessageBox.information(self, "Export Complete", "\n\n".join(lines))
```

In `combined_window.py`, add to `md_menu` block (line 107-113) or as its own entry right after it:

```python
        file_menu.addMenu(md_menu)
        file_menu.addAction(ta.action_export_epub_series)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main_window.py::TestExportEpubSeries -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS (all tests, no regressions)

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/test_main_window.py
git commit -m "feat(ui): Export Series EPUB… — one .epub per volume"
```

---

## Task 10: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: PASS — all tests green, including everything added in Tasks 1-9.

- [ ] **Step 2: Confirm `EPUB/` stays untracked**

Run: `git status --short EPUB/`
Expected: no output (already gitignored per `.gitignore:43`, done in an earlier session — this step just confirms no regression).

- [ ] **Step 3: Manual smoke test against a real sample volume**

Run the app (`python -m translation_assistant.main`), use **File → Import EPUB…** against one of the two files in `EPUB/`, confirm the chapter checklist and char-counts look sane, import a couple of chapters, translate one fully, then use **File → Export Series EPUB…** and confirm the incomplete volume is skipped (expected — only one chapter translated) with a clear summary message. This step is exploratory, not pass/fail — its purpose is to catch anything the synthetic fixtures couldn't (encoding quirks, large-file performance, real-world ruby/gaiji density).

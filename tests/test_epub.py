"""
Tests for translation_assistant.epub — pure unit tests against synthetic
EPUB fixtures built with zipfile. No dependency on the real sample files
in EPUB/ (gitignored, purchased content, manual-testing only).
"""
import zipfile
from pathlib import Path

import pytest

from translation_assistant.epub import EpubError, open_book, extract_chapter_text


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

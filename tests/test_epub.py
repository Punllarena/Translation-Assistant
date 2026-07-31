"""
Tests for translation_assistant.epub — pure unit tests against synthetic
EPUB fixtures built with zipfile. No dependency on the real sample files
in EPUB/ (gitignored, purchased content, manual-testing only).
"""
import zipfile
from pathlib import Path

import pytest

from translation_assistant.epub import (
    EpubError, open_book, extract_chapter_text, extract_chapter_content, build_epub,
)


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


_NAV_NESTED = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body>
<nav epub:type="toc">
<ol>
<li><a href="text/ch1.xhtml">Part 1</a>
  <ol>
    <li><a href="text/ch1.xhtml#s1">Section 1</a></li>
    <li><a href="text/ch1.xhtml#s2">Section 2</a></li>
  </ol>
</li>
<li><a href="text/ch2.xhtml">Part 2</a></li>
</ol>
</nav>
</body>
</html>
"""

_NAV_LANDMARKS_FIRST = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body>
<nav epub:type="landmarks">
<ol>
<li><a epub:type="cover" href="text/ch2.xhtml">Cover</a></li>
</ol>
</nav>
<nav epub:type="toc">
<ol>
<li><a href="text/ch1.xhtml">Chapter 1</a></li>
<li><a href="text/ch2.xhtml">Chapter 2</a></li>
</ol>
</nav>
</body>
</html>
"""


def _make_epub3_with_nav(tmp_path: Path, nav_xhtml: str, name: str = "navtest.epub") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_EPUB3)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>One.</p></body></html>")
        zf.writestr("OEBPS/text/ch2.xhtml", "<html><body><p>Two.</p></body></html>")
    return path


class TestNavQuirks:
    def test_nested_toc_entries_deduped_to_one_chapter_per_file(self, tmp_path):
        """Part -> Section#fragment must not yield 3 chapters all pointing at ch1."""
        book = open_book(_make_epub3_with_nav(tmp_path, _NAV_NESTED))
        hrefs = [c["href"] for c in book["chapters"]]
        assert hrefs.count("OEBPS/text/ch1.xhtml") == 1
        assert hrefs == ["OEBPS/text/ch1.xhtml", "OEBPS/text/ch2.xhtml"]
        assert [c["title"] for c in book["chapters"]] == ["Part 1", "Part 2"]

    def test_dedupe_renumbers_order_contiguously(self, tmp_path):
        book = open_book(_make_epub3_with_nav(tmp_path, _NAV_NESTED))
        assert [c["order"] for c in book["chapters"]] == [1, 2]

    def test_toc_nav_preferred_over_earlier_landmarks_nav(self, tmp_path):
        """A landmarks <nav> listed first must not shadow the real toc."""
        book = open_book(_make_epub3_with_nav(tmp_path, _NAV_LANDMARKS_FIRST))
        assert [c["title"] for c in book["chapters"]] == ["Chapter 1", "Chapter 2"]

    def test_untyped_nav_still_used_as_fallback(self, tmp_path):
        """EPUB2-ish nav docs omitting epub:type must still work."""
        nav = _NAV_XHTML.replace('<nav epub:type="toc">', "<nav>")
        book = open_book(_make_epub3_with_nav(tmp_path, nav))
        assert [c["title"] for c in book["chapters"]] == ["Chapter 1", "Chapter 2"]


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


class TestBuildEpub:
    def test_returns_bytes(self):
        result = build_epub("My Volume", [("Chapter 1", [("text", "Hello."), ("text", "World.")], [])])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_is_valid_zip(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", [("text", "Hello.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        assert zipfile.is_zipfile(out)

    def test_mimetype_is_first_entry_uncompressed(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", [("text", "Hello.")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        with zipfile.ZipFile(out) as zf:
            info = zf.infolist()[0]
            assert info.filename == "mimetype"
            assert info.compress_type == zipfile.ZIP_STORED

    def test_round_trip_title_and_chapters(self, tmp_path):
        result = build_epub("My Volume", [
            ("Chapter 1", [("text", "Hello world.")], []),
            ("Chapter 2", [("text", "Second chapter.")], []),
        ])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        book = open_book(out)
        assert book["title"] == "My Volume"
        assert [c["title"] for c in book["chapters"]] == ["Chapter 1", "Chapter 2"]

    def test_round_trip_paragraph_text_survives(self, tmp_path):
        result = build_epub("My Volume", [
            ("Chapter 1", [("text", "Hello world."), ("text", "Second paragraph.")], []),
        ])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        book = open_book(out)
        href = book["chapters"][0]["href"]
        text = extract_chapter_text(out, href)
        assert text == "Hello world.\nSecond paragraph."

    def test_xml_special_characters_escaped(self, tmp_path):
        result = build_epub("My Volume", [("Chapter 1", [("text", "A & B < C > D")], [])])
        out = tmp_path / "out.epub"
        out.write_bytes(result)
        book = open_book(out)
        href = book["chapters"][0]["href"]
        assert extract_chapter_text(out, href) == "A & B < C > D"


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

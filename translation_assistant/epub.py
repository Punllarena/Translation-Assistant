"""
EPUB import/export — framework-agnostic (no Qt, no db import), mirrors the
parsing style of scraper.py. Zip/XML handling only via stdlib zipfile +
xml.sax.saxutils.escape and the already-installed beautifulsoup4.
"""
import io
import posixpath
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

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


def _dedupe_by_href(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Keep the first entry per resolved href.

    A nested TOC (Part -> Section#fragment) flattens to several entries that
    all resolve to the same file once the #fragment is stripped. Since
    extract_chapter_text() extracts the WHOLE file, keeping all of them would
    create N documents each holding the entire file's text. One document per
    unique file is the correct degradation for a whole-file text extractor.
    """
    seen = set()
    result = []
    for title, href in entries:
        if href in seen:
            continue
        seen.add(href)
        result.append((title, href))
    return result


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

        toc_entries = _dedupe_by_href(_read_toc(zf, opf, opf_dir))
        cover_href = _find_cover_href(opf, opf_dir)

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

        return {"title": title, "chapters": chapters, "cover_href": cover_href}


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


def _read_toc(zf: zipfile.ZipFile, opf: BeautifulSoup, opf_dir: str) -> list[tuple[str, str]]:
    """Returns [(chapter_title, resolved_href), ...] in TOC order."""
    nav_item = opf.find("item", attrs={"properties": lambda v: v and "nav" in v.split()})
    if nav_item is not None:
        nav_href = _resolve(opf_dir, nav_item["href"])
        nav_soup = BeautifulSoup(_read(zf, nav_href), "html.parser")
        nav_dir = posixpath.dirname(nav_href)
        # An EPUB3 nav doc may hold several <nav>s (toc / landmarks / page-list)
        # in any order, so prefer the toc-typed one. html.parser keeps the
        # colon in "epub:type" verbatim (same reason dc:title works above).
        # Fall back to the first <nav> for EPUB2-ish files that omit the attr.
        toc_nav = (
            nav_soup.find("nav", attrs={"epub:type": lambda v: v and "toc" in v.split()})
            or nav_soup.find("nav")
        )
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

"""
EPUB import/export — framework-agnostic (no Qt, no db import), mirrors the
parsing style of scraper.py. Zip/XML handling only via stdlib zipfile +
xml.sax.saxutils.escape and the already-installed beautifulsoup4.
"""
import io
import mimetypes
import posixpath
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup

from translation_assistant.core import build_new_file, parse_file_content


def _escape_attr(s: str) -> str:
    """Escape a string for safe use inside a double-quoted XML attribute.

    xml.sax.saxutils.escape() only escapes &, <, > -- not " -- so it is
    insufficient on its own for attribute values (as opposed to text nodes).
    """
    return escape(s, {'"': "&quot;"})


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
    extract_chapter_content() extracts the WHOLE file, keeping all of them would
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
        metadata = _find_metadata(opf)

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

        return {"title": title, "chapters": chapters, "cover_href": cover_href, **metadata}


def extract_chapter_content(path: Path, href: str) -> tuple[str, list[dict]]:
    """
    Returns (text, images).
    text: joined-paragraph string, ready
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
            para_raw_lines, _, _ = parse_file_content(build_new_file(para_text))
            offset += len(para_raw_lines)

    return "\n".join(text_paragraphs), images


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

    Assembles a minimal valid EPUB3 zip in memory using stdlib zipfile +
    xml.sax.saxutils.escape — no new dependency. mimetype is stored
    uncompressed as the first entry (required by the EPUB spec so readers
    can identify the format without inflating the zip).

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
        used_image_hrefs: set[str] = set()  # zip-relative hrefs already claimed, across all chapters

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
                        data = image_bytes_by_src.get(src_path)
                        if data is None:
                            continue  # referenced image has no bytes -- skip, not fatal
                        # Preserve the original basename where possible (readable,
                        # round-trips predictably); fall back to a numbered prefix
                        # only on a collision (two different src_paths sharing a
                        # basename, e.g. two chapters each with an "images/pic.png").
                        basename = posixpath.basename(src_path) or f"{image_id}.img"
                        img_href = f"images/{basename}"
                        if img_href in used_image_hrefs:
                            img_href = f"images/{image_id}_{basename}"
                        used_image_hrefs.add(img_href)
                        zf.writestr(f"OEBPS/{img_href}", data)
                        media_type = mimetypes.guess_type(src_path)[0] or "application/octet-stream"
                        manifest_items.append(
                            f'<item id="img{image_id}" href="{_escape_attr(img_href)}" '
                            f'media-type="{_escape_attr(media_type)}"/>'
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
            if cover_href in used_image_hrefs:
                n = 1
                while f"images/cover_{n}{ext}" in used_image_hrefs:
                    n += 1
                cover_href = f"images/cover_{n}{ext}"
            used_image_hrefs.add(cover_href)
            zf.writestr(f"OEBPS/{cover_href}", cover["data"])
            manifest_items.append(
                f'<item id="cover-image" href="{_escape_attr(cover_href)}" '
                f'media-type="{_escape_attr(cover["media_type"])}" properties="cover-image"/>'
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

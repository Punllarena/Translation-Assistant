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

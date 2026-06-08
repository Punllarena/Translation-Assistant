"""
Syosetu chapter scraper — URL validation, HTML fetch, and QThread worker.
"""
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from PySide6.QtCore import QThread, Signal

_ALLOWED_SUFFIX = ".syosetu.com"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def validate_url(url: str) -> None:
    netloc = urlparse(url).netloc.lower()
    if not netloc.endswith(_ALLOWED_SUFFIX):
        raise ValueError("Only syosetu.com URLs are supported")


def fetch_syosetu(url: str) -> tuple[str, str]:
    validate_url(url)
    resp = requests.get(url, timeout=10, headers={"User-Agent": _UA}, cookies={"over18": "yes"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find(class_=lambda c: c and "p-novel__title--rensai" in c.split())
    title = title_el.get_text(strip=True) if title_el else ""

    content_el = soup.find(
        class_=lambda c: c and "js-novel-text" in c.split() and "p-novel__text" in c.split()
    )
    if not content_el:
        raise ValueError("Could not find novel text on page")
    content = "\n".join(p.get_text(strip=True) for p in content_el.find_all("p"))

    return title, content


class FetchWorker(QThread):
    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            title, content = fetch_syosetu(self._url)
            self.finished.emit(title, content)
        except Exception as exc:
            self.error.emit(str(exc))


def _validate_series_url(url: str) -> None:
    validate_url(url)
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) != 1:
        raise ValueError(
            "URL must be a series root (e.g. https://novel18.syosetu.com/n7696mg/), "
            "not a chapter URL"
        )


def fetch_series_index(url: str) -> list[dict]:
    _validate_series_url(url)
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    resp = requests.get(url, timeout=10, headers={"User-Agent": _UA}, cookies={"over18": "yes"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    chapters = []
    for dd in soup.select("dl.novel_sublist2 dd.subtitle"):
        a = dd.find("a")
        if not a:
            continue
        href = a.get("href", "")
        href_parts = [p for p in href.split("/") if p]
        try:
            num = int(href_parts[-1])
        except (ValueError, IndexError):
            continue
        title = a.get_text(strip=True)
        chapter_url = urljoin(base, href)
        chapters.append({"num": num, "title": title, "url": chapter_url})
    chapters.sort(key=lambda c: c["num"])
    return chapters


def fetch_chapter(url: str) -> tuple[str, str]:
    return fetch_syosetu(url)


class IndexFetchWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            chapters = fetch_series_index(self._url)
            self.finished.emit(chapters)
        except Exception as exc:
            self.error.emit(str(exc))


class SeriesFetchWorker(QThread):
    chapter_done = Signal(int, str, str)   # num, title, content
    progress = Signal(int, int)             # current, total
    error = Signal(int, str)               # chapter_num, message
    finished = Signal()

    def __init__(self, chapters_to_fetch: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._chapters_to_fetch = chapters_to_fetch

    def run(self) -> None:
        total = len(self._chapters_to_fetch)
        for i, ch in enumerate(self._chapters_to_fetch):
            if self.isInterruptionRequested():
                break
            try:
                title, content = fetch_syosetu(ch["url"])
                self.chapter_done.emit(ch["num"], title, content)
            except Exception as exc:
                self.error.emit(ch["num"], str(exc))
            self.progress.emit(i + 1, total)
            if i < total - 1:
                QThread.sleep(5)
        self.finished.emit()

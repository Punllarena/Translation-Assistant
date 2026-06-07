"""
Syosetu chapter scraper — URL validation, HTML fetch, and QThread worker.
"""
from urllib.parse import urlparse

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
    resp = requests.get(url, timeout=10, headers={"User-Agent": _UA})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find(class_=lambda c: c and "p-novel__title--rensai" in c.split())
    title = title_el.get_text(strip=True) if title_el else ""

    content_el = soup.find(
        class_=lambda c: c and "js-novel-text" in c.split() and "p-novel__text" in c.split()
    )
    if not content_el:
        raise ValueError("Could not find novel text on page")
    content = content_el.get_text(separator="\n", strip=True)

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

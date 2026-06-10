from __future__ import annotations

import httpx

from ta.config.languages import Language, to_google_code
from ta.translators.base import BaseTranslator


class LibreTranslator(BaseTranslator):
    def __init__(self, url: str = "http://localhost:5000", api_key: str = "", parent=None):
        super().__init__("LibreTranslate", parent)
        self._url = url.rstrip("/")
        self._api_key = api_key

    def can_translate(self, src: Language, dst: Language) -> bool:
        src_code = "auto" if src == Language.AUTO else to_google_code(src)
        dst_code = to_google_code(dst)
        return bool(dst_code)

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        src_code = "auto" if src == Language.AUTO else to_google_code(src)
        dst_code = to_google_code(dst)
        payload: dict = {"q": text, "source": src_code, "target": dst_code, "format": "text"}
        if self._api_key:
            payload["api_key"] = self._api_key
        resp = httpx.post(f"{self._url}/translate", json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()["translatedText"]

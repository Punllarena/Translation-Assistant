from __future__ import annotations

import httpx

from ta.config.languages import Language, to_google_code
from ta.translators.base import BaseTranslator

_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"
_API_VERSION = "3.0"


class BingTranslator(BaseTranslator):
    def __init__(self, api_key: str, parent=None):
        super().__init__("Bing Translator", parent)
        self._api_key = api_key

    def can_translate(self, src: Language, dst: Language) -> bool:
        return bool(self._api_key) and bool(to_google_code(dst))

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        to_code = to_google_code(dst)
        params: dict = {"api-version": _API_VERSION, "to": to_code}
        if src not in (Language.AUTO, Language.NONE):
            params["from"] = to_google_code(src)
        headers = {
            "Ocp-Apim-Subscription-Key": self._api_key,
            "Content-Type": "application/json",
        }
        resp = httpx.post(
            _ENDPOINT,
            params=params,
            json=[{"Text": text}],
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()[0]["translations"][0]["text"]

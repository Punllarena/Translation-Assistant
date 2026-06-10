from __future__ import annotations

from ta.config.languages import Language, to_google_code
from ta.translators.base import BaseTranslator


class GoogleTranslator(BaseTranslator):
    def __init__(self, api_key: str, parent=None):
        super().__init__("Google Translate", parent)
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import translate_v2 as gt
            import os
            # SDK reads GOOGLE_APPLICATION_CREDENTIALS; api_key path via requests
            self._client = gt.Client(client_options={"api_key": self._api_key} if self._api_key else {})
        return self._client

    def can_translate(self, src: Language, dst: Language) -> bool:
        return bool(self._api_key) and bool(to_google_code(dst))

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        target = to_google_code(dst)
        source = to_google_code(src) if src not in (Language.AUTO, Language.NONE) else None
        result = self._get_client().translate(text, target_language=target, source_language=source)
        return result["translatedText"]

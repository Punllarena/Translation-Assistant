from __future__ import annotations

from ta.config.languages import Language, to_deepl_code
from ta.translators.base import BaseTranslator


class DeepLTranslator(BaseTranslator):
    def __init__(self, api_key: str, parent=None):
        super().__init__("DeepL", parent)
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            import deepl
            self._client = deepl.Translator(self._api_key)
        return self._client

    def can_translate(self, src: Language, dst: Language) -> bool:
        return bool(self._api_key) and bool(to_deepl_code(dst))

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        target = to_deepl_code(dst)
        src_code = to_deepl_code(src) if src not in (Language.AUTO, Language.NONE) else None
        result = self._get_client().translate_text(text, target_lang=target, source_lang=src_code)
        return result.text

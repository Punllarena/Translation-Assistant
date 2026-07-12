from __future__ import annotations

import json

import httpx

from ta.config.languages import Language, to_google_code
from ta.translators.base import BaseTranslator


def _lang_display(lang: Language) -> str:
    code = to_google_code(lang)
    name = lang.name.replace("_", " ")
    return f"{name} ({code})" if code else name


class OllamaTranslator(BaseTranslator):
    def __init__(self, url: str, model: str, system_prompt: str, parent=None):
        super().__init__("Ollama", parent)
        self._url = url.rstrip("/")
        self._model = model
        self._system_prompt = system_prompt
        self._active_response: "httpx.Response | None" = None

    def halt(self) -> None:
        super().halt()
        resp = self._active_response
        if resp is not None:
            resp.close()

    def _worker(self) -> None:
        while True:
            with self._lock:
                if self._cancel or self._pending is None:
                    self._running = False
                    return
                text, src, dst = self._pending
                self._pending = None

            self.translation_started.emit()
            try:
                self._stream_translate(text, src, dst)
            except Exception as exc:
                if not self._cancel:
                    self.translation_error.emit(str(exc))

            with self._lock:
                if self._pending is None:
                    self._running = False
                    return

    def _stream_translate(self, text: str, src: Language, dst: Language) -> None:
        src_display = _lang_display(src)
        dst_display = _lang_display(dst)
        system = (
            self._system_prompt
            .replace("{src}", src_display)
            .replace("{dst}", dst_display)
        )
        payload = {
            "model": self._model,
            "stream": True,
            "think": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        }
        with httpx.stream("POST", f"{self._url}/api/chat", json=payload, timeout=60) as resp:
            self._active_response = resp
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                resp.read()
                try:
                    detail = resp.json().get("error", "")
                except Exception:
                    detail = ""
                if detail:
                    raise RuntimeError(f"HTTP {resp.status_code}: {detail}") from exc
                raise
            thinking_open = False
            for line in resp.iter_lines():
                if self._cancel:
                    break
                if not line.strip():
                    continue
                obj = json.loads(line)
                if obj.get("done"):
                    break
                message = obj.get("message", {})
                thinking = message.get("thinking", "")
                if thinking:
                    if not thinking_open:
                        self.translation_chunk.emit("[thinking] ")
                        thinking_open = True
                    self.translation_chunk.emit(thinking)
                token = message.get("content", "")
                if token:
                    if thinking_open:
                        self.translation_chunk.emit("\n[answer] ")
                        thinking_open = False
                    self.translation_chunk.emit(token)
            self._active_response = None

        if not self._cancel:
            self.translation_ready.emit("")

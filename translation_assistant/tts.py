"""
Text-to-speech abstraction over pyttsx3.
Stub — full implementation in Stage 7.
"""


class TTSEngine:
    """Wraps pyttsx3 for async TTS without blocking the UI thread."""

    def available_voices(self) -> list[str]:
        raise NotImplementedError

    def set_voice(self, name: str) -> None:
        raise NotImplementedError

    def speak_async(self, text: str) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

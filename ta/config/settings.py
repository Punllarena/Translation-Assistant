from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ta.config.languages import Language, from_string


DEFAULT_OLLAMA_SYSTEM_PROMPT = (
    "You are a professional {src} to {dst} translator.\n\n"
    "Translate the following {src} text to {dst}.\n\n"
    "Requirements:\n"
    "* Preserve the original meaning, tone, nuance, and intent.\n"
    "* Produce natural, grammatically correct {dst}.\n"
    "* Return only the translation — no explanations, notes, or commentary."
)


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ta-python"


DEFAULT_CONFIG_PATH = _config_dir() / "settings.toml"


@dataclass
class TranslatorConfig:
    enabled: bool = False
    api_key: str = ""
    url: str = ""
    model: str = ""
    system_prompt: str = ""
    # Ollama only: background prefetch of upcoming lines (0 = off)
    prefetch_count: int = 0
    prefetch_idle_ms: int = 3000


@dataclass
class FilterConfig:
    # Char repeat modes: none, auto_constant, infinite, auto_advanced, custom
    char_repeat_mode: str = "auto_constant"
    # Line break modes: remove_all, remove_some, keep
    line_break_mode: str = "remove_all"
    line_breaks_first: int = 0
    line_breaks_last: int = 0
    phrase_repeat: bool = True
    phrase_min: int = 4
    phrase_max: int = 100


@dataclass
class FontConfig:
    face: str = "Noto Sans"
    size: int = 10
    bold: bool = False
    italic: bool = False


@dataclass
class Settings:
    src_language: Language = Language.Japanese
    dst_language: Language = Language.English
    auto_clipboard: bool = True
    max_clipboard_chars: int = 500
    enable_substitutions: bool = True
    history_max_bytes: int = 20_971_520  # 20 MB

    filter: FilterConfig = field(default_factory=FilterConfig)
    font: FontConfig = field(default_factory=FontConfig)

    translators: dict[str, TranslatorConfig] = field(default_factory=lambda: {
        "deepl": TranslatorConfig(enabled=False),
        "google": TranslatorConfig(enabled=False),
        "bing": TranslatorConfig(enabled=False),
        "libretranslate": TranslatorConfig(enabled=False, url="http://localhost:5000"),
        "ollama": TranslatorConfig(
            enabled=False,
            url="http://localhost:11434",
            system_prompt=DEFAULT_OLLAMA_SYSTEM_PROMPT,
        ),
        "mecab": TranslatorConfig(enabled=True),
        "jparser": TranslatorConfig(enabled=True),
    })

    # Ordered list of panels to display
    layout_panels: list[str] = field(default_factory=lambda: [
        "deepl", "google", "bing", "libretranslate", "ollama", "mecab", "jparser"
    ])

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "Settings":
        if not path.exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Settings":
        s = cls()
        general = data.get("general", {})
        s.src_language = from_string(general.get("src_language", "Japanese"))
        s.dst_language = from_string(general.get("dst_language", "English"))
        s.auto_clipboard = general.get("auto_clipboard", True)
        s.max_clipboard_chars = general.get("max_clipboard_chars", 500)
        s.enable_substitutions = general.get("enable_substitutions", True)
        s.history_max_bytes = general.get("history_max_bytes", 20_971_520)

        if "filter" in data:
            f = data["filter"]
            s.filter = FilterConfig(
                char_repeat_mode=f.get("char_repeat_mode", "auto_constant"),
                line_break_mode=f.get("line_break_mode", "remove_all"),
                line_breaks_first=f.get("line_breaks_first", 0),
                line_breaks_last=f.get("line_breaks_last", 0),
                phrase_repeat=f.get("phrase_repeat", True),
                phrase_min=f.get("phrase_min", 4),
                phrase_max=f.get("phrase_max", 100),
            )

        if "fonts" in data:
            fn = data["fonts"]
            s.font = FontConfig(
                face=fn.get("face", "Noto Sans"),
                size=fn.get("size", 10),
                bold=fn.get("bold", False),
                italic=fn.get("italic", False),
            )

        if "translators" in data:
            for name, cfg in data["translators"].items():
                api_key = cfg.get("api_key", "")
                # Resolve env var fallbacks
                env_map = {
                    "deepl": "DEEPL_API_KEY",
                    "google": "GOOGLE_TRANSLATE_KEY",
                    "bing": "AZURE_TRANSLATOR_KEY",
                }
                if not api_key and name in env_map:
                    api_key = os.environ.get(env_map[name], "")
                s.translators[name] = TranslatorConfig(
                    enabled=cfg.get("enabled", False),
                    api_key=api_key,
                    url=cfg.get("url", ""),
                    model=cfg.get("model", ""),
                    system_prompt=cfg.get("system_prompt", ""),
                    prefetch_count=cfg.get("prefetch_count", 0),
                    prefetch_idle_ms=cfg.get("prefetch_idle_ms", 3000),
                )

        if "layout" in data:
            s.layout_panels = data["layout"].get("panels", s.layout_panels)

        return s

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "[general]",
            f'src_language = "{self.src_language.name}"',
            f'dst_language = "{self.dst_language.name}"',
            f"auto_clipboard = {str(self.auto_clipboard).lower()}",
            f"max_clipboard_chars = {self.max_clipboard_chars}",
            f"enable_substitutions = {str(self.enable_substitutions).lower()}",
            f"history_max_bytes = {self.history_max_bytes}",
            "",
            "[filter]",
            f'char_repeat_mode = "{self.filter.char_repeat_mode}"',
            f'line_break_mode = "{self.filter.line_break_mode}"',
            f"line_breaks_first = {self.filter.line_breaks_first}",
            f"line_breaks_last = {self.filter.line_breaks_last}",
            f"phrase_repeat = {str(self.filter.phrase_repeat).lower()}",
            f"phrase_min = {self.filter.phrase_min}",
            f"phrase_max = {self.filter.phrase_max}",
            "",
            "[fonts]",
            f'face = "{self.font.face}"',
            f"size = {self.font.size}",
            f"bold = {str(self.font.bold).lower()}",
            f"italic = {str(self.font.italic).lower()}",
            "",
        ]
        for name, cfg in self.translators.items():
            lines += [
                f"[translators.{name}]",
                f"enabled = {str(cfg.enabled).lower()}",
                f'api_key = "{cfg.api_key}"',
            ]
            if cfg.url:
                lines.append(f'url = "{cfg.url}"')
            if cfg.model:
                lines.append(f'model = "{cfg.model}"')
            if cfg.prefetch_count:
                lines.append(f"prefetch_count = {cfg.prefetch_count}")
            if cfg.prefetch_idle_ms != 3000:
                lines.append(f"prefetch_idle_ms = {cfg.prefetch_idle_ms}")
            if cfg.system_prompt:
                escaped = cfg.system_prompt.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
                lines.append(f'system_prompt = """\n{escaped}"""')
            lines.append("")

        panels_str = ", ".join(f'"{p}"' for p in self.layout_panels)
        lines += [
            "[layout]",
            f"panels = [{panels_str}]",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")

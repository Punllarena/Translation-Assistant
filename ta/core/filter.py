"""Port of exe/Filter.cpp — text dedup and cleanup filters."""
from __future__ import annotations

import re

from ta.config.settings import FilterConfig


def auto_filter(text: str, cfg: FilterConfig) -> str:
    """Apply all configured filters in sequence."""
    if cfg.char_repeat_mode == "none":
        pass
    elif cfg.char_repeat_mode == "auto_constant":
        text = char_repeat_filter(text, max_run=3)
    elif cfg.char_repeat_mode == "infinite":
        text = char_repeat_filter(text, max_run=None)
    elif cfg.char_repeat_mode == "auto_advanced":
        text = char_repeat_filter(text, max_run=2)

    if cfg.phrase_repeat:
        text = phrase_repeat_filter(text, cfg.phrase_min, cfg.phrase_max)

    if cfg.line_break_mode == "remove_all":
        text = line_break_filter_remove_all(text)
    elif cfg.line_break_mode == "remove_some":
        text = line_break_filter_remove_some(text, cfg.line_breaks_first, cfg.line_breaks_last)

    return text


def char_repeat_filter(text: str, max_run: int | None = 3) -> str:
    """Collapse runs of the same character.

    max_run=None collapses to exactly 1 (infinite repeat mode).
    max_run=N allows up to N consecutive identical chars.
    """
    if not text:
        return text
    limit = 1 if max_run is None else max_run
    result = []
    run = 1
    for i, ch in enumerate(text):
        if i == 0:
            result.append(ch)
            continue
        if ch == text[i - 1]:
            run += 1
            if run <= limit:
                result.append(ch)
        else:
            run = 1
            result.append(ch)
    return "".join(result)


def phrase_repeat_filter(text: str, min_dist: int = 4, max_dist: int = 100) -> str:
    """Remove adjacent repeated phrases.

    Scans for a substring of length [min_dist..max_dist] that immediately
    repeats, then removes the duplicate.
    """
    if len(text) < min_dist * 2:
        return text

    changed = True
    while changed:
        changed = False
        n = len(text)
        for length in range(min(max_dist, n // 2), min_dist - 1, -1):
            i = 0
            while i <= n - length * 2:
                phrase = text[i:i + length]
                if text[i + length:i + length * 2] == phrase:
                    text = text[:i + length] + text[i + length * 2:]
                    n = len(text)
                    changed = True
                    break
                i += 1
            if changed:
                break
    return text


def line_break_filter_remove_all(text: str) -> str:
    """Replace all newlines with a single space."""
    return re.sub(r"[\r\n]+", " ", text).strip()


def line_break_filter_remove_some(text: str, first_n: int, last_n: int) -> str:
    """Remove first_n and last_n line breaks, keep the rest."""
    lines = text.splitlines()
    if not lines:
        return text
    # Rejoin: strip leading/trailing empty lines up to first_n/last_n
    start = min(first_n, len(lines))
    end = max(0, len(lines) - last_n)
    kept = lines[start:end]
    return "\n".join(kept)

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

from ta.config.languages import Language
from ta.translators.base import BaseTranslator

_PKG_DICT_DIR = Path(__file__).parent.parent.parent / "dictionaries"
_DICT_DIRS = [
    _PKG_DICT_DIR,
    Path("dictionaries"),
    Path.home() / ".local" / "share" / "ta-python" / "dictionaries",
]
_CONJ_DIRS = _DICT_DIRS

# edict2: word1;word2(P) [reading] /(pos,...) gloss1/gloss2/EntLXXX/
_EDICT_PAT = re.compile(r"^([^\[/]+?)\s*(?:\[([^\]]+)\])?\s*/(.+)/$")
_WORD_ANNOTATION = re.compile(r"\([^)]+\)")
_POS_PAT = re.compile(r"^\(([^)]+)\)")
_ENTL_PAT = re.compile(r"/EntL\S+/?$")


class DictEntry(NamedTuple):
    headwords: tuple[str, ...]
    reading: str
    pos_tags: frozenset[str]
    gloss: str
    common: bool = False  # True if any headword has (P) marker


class DeconjRule(NamedTuple):
    conj_type: str
    pos: str
    suffix: str
    base_suffix: str
    tense: str
    negative: bool
    formal: bool


class DeconjMatch(NamedTuple):
    base_form: str
    entry: DictEntry
    tense: str
    negative: bool
    formal: bool
    conj_type: str


def _find_dict() -> Path | None:
    for d in _DICT_DIRS:
        for name in ("edict2", "edict", "edict2.utf8"):
            p = d / name
            if p.exists():
                return p
    return None


def _find_conj() -> Path | None:
    for d in _CONJ_DIRS:
        p = d / "Conjugations.txt"
        if p.exists():
            return p
    return None


def _clean_gloss(gloss: str) -> str:
    gloss = _ENTL_PAT.sub("", gloss).rstrip("/")
    parts = [p.strip() for p in gloss.split("/") if p.strip()]
    defs: list[str] = []
    for p in parts:
        pm = _POS_PAT.match(p)
        if pm:
            after = _POS_PAT.sub("", p).strip()
            # strip leading numbered sense marker like "(1)"
            after = re.sub(r"^\(\d+\)\s*", "", after)
            if after:
                defs.append(after)
        elif not p.startswith("("):
            defs.append(p)
        elif ")" in p:
            after = p[p.index(")") + 1:].strip()
            after = re.sub(r"^\(\d+\)\s*", "", after)
            if after:
                defs.append(after)
        if len(defs) >= 2:
            break
    return "; ".join(defs) if defs else gloss[:60]


def _parse_edict_line(line: str) -> DictEntry | None:
    if not line or line.startswith("#"):
        return None
    m = _EDICT_PAT.match(line)
    if not m:
        return None
    words_raw, reading, gloss_raw = m.group(1), m.group(2) or "", m.group(3)

    headwords: list[str] = []
    common = False
    for w in words_raw.split(";"):
        w = w.strip()
        if "(P)" in w:
            common = True
        w_clean = _WORD_ANNOTATION.sub("", w).strip()
        if w_clean:
            headwords.append(w_clean)
    if not headwords:
        return None

    pos_tags: set[str] = set()
    pm = _POS_PAT.match(gloss_raw)
    if pm:
        for tag in pm.group(1).split(","):
            pos_tags.add(tag.strip())

    gloss = _clean_gloss(gloss_raw)
    return DictEntry(
        headwords=tuple(headwords),
        reading=reading.strip(),
        pos_tags=frozenset(pos_tags),
        gloss=gloss,
        common=common,
    )


def _load_conj_rules(path: Path) -> list[DeconjRule]:
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-16")
    except UnicodeDecodeError:
        text = raw.decode("utf-8")
    data = json.loads(text)

    # Build a map of stem type → its tenses (for chained conjugation)
    stem_tenses: dict[str, list[dict]] = {}
    for entry in data:
        stem_tenses[entry["Name"]] = entry["Tenses"]

    def _base_suffix_for(tenses: list[dict]) -> str:
        for t in tenses:
            if t["Tense"] == "Remove" and not t["Negative"] and not t["Formal"]:
                return t["Suffix"]
        for t in tenses:
            if t["Tense"] == "Non-past" and not t["Negative"] and not t["Formal"]:
                return t["Suffix"]
        return ""

    rules: list[DeconjRule] = []
    seen: set[tuple] = set()

    def _add(conj_type, pos, suffix, base_suffix, tense, negative, formal):
        if not suffix:
            return
        key = (conj_type, suffix, base_suffix, tense, negative, formal)
        if key in seen:
            return
        seen.add(key)
        rules.append(DeconjRule(
            conj_type=conj_type,
            pos=pos,
            suffix=suffix,
            base_suffix=base_suffix,
            tense=tense,
            negative=negative,
            formal=formal,
        ))

    for entry in data:
        name = entry["Name"]
        pos = entry["Part of Speech"]
        tenses = entry["Tenses"]
        base_sfx = _base_suffix_for(tenses)

        for t in tenses:
            tense = t["Tense"]
            suffix = t["Suffix"]
            negative = t["Negative"]
            formal = t["Formal"]

            if tense == "Remove":
                continue

            if tense == "Stem" and "Next Type" in t:
                # Chained: word = stem + stem_suffix + stem_type_tense_suffix
                # → dict form = stem_rawstem + parent_base_suffix
                next_type = t["Next Type"]
                next_tenses = stem_tenses.get(next_type, [])
                # The stem itself is a valid form (e.g. ta-stem = past)
                # Add compound rules: suffix + next_tense_suffix → base
                for nt in next_tenses:
                    if nt["Tense"] == "Remove":
                        continue
                    ns = nt["Suffix"]
                    compound = suffix + ns
                    if not compound:
                        # stem with no additional suffix = the stem tense itself
                        # e.g. v-ta-stem Past suffix="" → just the suffix from parent stem
                        compound = suffix  # use parent stem suffix
                        _add(name, pos, compound, base_sfx, nt["Tense"],
                             nt["Negative"], nt["Formal"])
                    else:
                        _add(name, pos, compound, base_sfx, nt["Tense"],
                             nt["Negative"], nt["Formal"])
                # Also add the stem suffix alone for stem-only lookup
                # (e.g. 食べた is v1 past → suffix=た, base_suffix=る)
                for nt in next_tenses:
                    if nt["Tense"] in ("Remove",) and not nt["Negative"] and not nt["Formal"]:
                        if suffix:
                            _add(name, pos, suffix, base_sfx, "Past",
                                 negative, formal)
                        break
                # also add plain stem suffix for the case where stem = past (v-ta-stem suffix="")
                for nt in next_tenses:
                    if nt["Tense"] == "Past" and not nt["Negative"] and not nt["Formal"] and not nt["Suffix"]:
                        if suffix:
                            _add(name, pos, suffix, base_sfx, "Past",
                                 False, False)
                        break
                continue

            if "Next Type" in t:
                continue  # skip other chained forms

            _add(name, pos, suffix, base_sfx, tense, negative, formal)

    rules.sort(key=lambda r: -len(r.suffix))
    return rules


def deconjugate(
    word: str,
    rules: list[DeconjRule],
    index: dict[str, DictEntry],
) -> list[DeconjMatch]:
    results: list[DeconjMatch] = []
    seen: set[str] = set()

    for rule in rules:
        if not word.endswith(rule.suffix):
            continue
        stem = word[: len(word) - len(rule.suffix)]
        base = stem + rule.base_suffix
        if not base or base in seen:
            continue
        entry = index.get(base)
        if entry is None:
            continue
        # POS filter: skip if entry POS is known and doesn't match conj_type prefix
        if entry.pos_tags:
            # conj_type like "v5k" should match edict2 "v5k", "v5" etc.
            # adj-i should match adj-i; adj-na should match adj-na
            ct = rule.conj_type
            tag_match = any(
                t == ct or t.startswith(ct) or ct.startswith(t)
                for t in entry.pos_tags
            )
            if not tag_match:
                continue
        seen.add(base)
        results.append(DeconjMatch(
            base_form=base,
            entry=entry,
            tense=rule.tense,
            negative=rule.negative,
            formal=rule.formal,
            conj_type=rule.conj_type,
        ))

    return results


def _h(text: str) -> str:
    """HTML-escape."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_entry(
    surface: str,
    entry: DictEntry,
    *,
    tense: str | None = None,
    base_form: str | None = None,
) -> str:
    pos_str = ",".join(sorted(entry.pos_tags)) if entry.pos_tags else ""

    parts: list[str] = []

    # Surface / copied text
    if base_form and base_form != surface:
        parts.append(f'<span style="color:#f8f8f2;font-weight:bold">{_h(surface)}</span>')
        parts.append(f'<span style="color:#ff79c6"> → </span>')
        parts.append(f'<span style="color:#ffb86c;font-weight:bold">{_h(base_form)}</span>')
    else:
        parts.append(f'<span style="color:#f8f8f2;font-weight:bold">{_h(surface)}</span>')

    # Reading
    if entry.reading:
        parts.append(f'<span style="color:#8be9fd"> [{_h(entry.reading)}]</span>')

    # POS
    if pos_str:
        parts.append(f'<span style="color:#6272a4"> ({_h(pos_str)})</span>')

    # Tense
    if tense:
        parts.append(f'<span style="color:#f1fa8c"> [{_h(tense)}]</span>')

    header = "".join(parts)
    gloss = f'<br>&nbsp;&nbsp;<span style="color:#50fa7b">{_h(entry.gloss)}</span>' if entry.gloss else ""

    return f'<div style="margin-bottom:4px">{header}{gloss}</div>'


import threading as _threading
_shared_index: dict[str, DictEntry] | None = None
_shared_loaded = False
_load_lock = _threading.Lock()


def load_edict_index() -> dict[str, DictEntry] | None:
    """Load (and cache) the edict2 index. Thread-safe; blocks until loaded."""
    global _shared_index, _shared_loaded
    with _load_lock:
        if _shared_loaded:
            return _shared_index
        # Load inside the lock so concurrent callers block until done.
        dict_path = _find_dict()
        if dict_path is None:
            _shared_loaded = True
            return None
        idx: dict[str, DictEntry] = {}
        enc = "euc-jp"
        try:
            with open(dict_path, encoding="euc-jp", errors="strict") as f:
                f.read(200)
        except UnicodeDecodeError:
            enc = "utf-8"
        with open(dict_path, encoding=enc, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                entry = _parse_edict_line(line)
                if entry is None:
                    continue
                for hw in entry.headwords:
                    existing = idx.get(hw)
                    if existing is None or (entry.common and not existing.common):
                        idx[hw] = entry
                if entry.reading:
                    existing = idx.get(entry.reading)
                    if existing is None or (entry.common and not existing.common):
                        idx[entry.reading] = entry
        _shared_index = idx
        _shared_loaded = True
        return idx


class JParserTranslator(BaseTranslator):
    """edict2-based Japanese word lookup with conjugation handling."""

    def __init__(self, parent=None):
        super().__init__("JParser", parent)
        self._index: dict[str, DictEntry] | None = None
        self._rules: list[DeconjRule] = []
        self._loaded = False

    @staticmethod
    def is_available() -> bool:
        return _find_dict() is not None

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        conj_path = _find_conj()
        if conj_path:
            try:
                self._rules = _load_conj_rules(conj_path)
            except Exception:
                self._rules = []

        self._index = load_edict_index()

    def can_translate(self, src: Language, dst: Language) -> bool:
        return _find_dict() is not None

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        self._load()
        if self._index is None:
            return "(No dictionary loaded — place edict2 in dictionaries/)"

        output: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch.isspace():
                i += 1
                continue

            # Greedy longest direct match (up to 12 chars)
            best_direct: tuple[int, DictEntry] | None = None
            for length in range(min(12, len(text) - i), 0, -1):
                token = text[i : i + length]
                if token in self._index:
                    best_direct = (length, self._index[token])
                    break

            # Greedy longest deconjugated match
            best_deconj: tuple[int, DeconjMatch] | None = None
            for length in range(min(12, len(text) - i), 1, -1):
                token = text[i : i + length]
                matches = deconjugate(token, self._rules, self._index)
                if matches:
                    best_deconj = (length, matches[0])
                    break

            if best_direct and best_deconj:
                dl, de = best_direct
                cl, cm = best_deconj
                # prefer longer match; on tie prefer deconj if it adds tense info
                if cl > dl:
                    length, m = best_deconj
                    output.append(format_entry(
                        text[i : i + cl], m.entry,
                        tense=m.tense, base_form=m.base_form,
                    ))
                    i += cl
                else:
                    length, entry = best_direct
                    token = text[i : i + dl]
                    # check if deconj at same length gives more info
                    if cl == dl and cm.tense != "Non-past":
                        output.append(format_entry(
                            token, cm.entry,
                            tense=cm.tense, base_form=cm.base_form,
                        ))
                    else:
                        output.append(format_entry(token, entry))
                    i += dl
            elif best_direct:
                dl, de = best_direct
                output.append(format_entry(text[i : i + dl], de))
                i += dl
            elif best_deconj:
                cl, cm = best_deconj
                output.append(format_entry(
                    text[i : i + cl], cm.entry,
                    tense=cm.tense, base_form=cm.base_form,
                ))
                i += cl
            else:
                if not ch.isspace() and ch not in "。、！？…・":
                    output.append(
                        f'<span style="color:#bd93f9">{_h(ch)}</span>'
                    )
                i += 1

        body = "\n".join(output)
        return (
            '<html><body style="background:#282a36;color:#f8f8f2;'
            'font-family:monospace;font-size:11pt;margin:4px">'
            f'{body}</body></html>'
        )

"""
Framework-agnostic text processing logic.
Ported from MainWindow.xaml.vb and frmNew.xaml.vb.
"""
import re
from pathlib import Path

SEPARATOR = "---SEPERATOR---"


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def parse_file_content(text: str) -> tuple[list[str], list[str], str]:
    """
    Split a SEPERATOR-format file into (raw_lines, translated_lines, raw_section).

    raw_section is the verbatim text before the separator — passed unchanged to
    save_file so the source text is never touched on a save round-trip.

    Raises ValueError if the separator is absent.
    """
    parts = text.split(SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError(f"File is missing the '{SEPARATOR}' marker.")

    raw_section = parts[0]
    translated_half = parts[1]

    # Normalise line endings and split raw section into lines
    raw_lines = [line.rstrip("\r") for line in raw_section.split("\n")]

    # The translated half opens with the newline immediately after the separator
    # (VB: Mid(str, 3, ...) skips the leading \r\n).  Drop only that first blank.
    t_lines = [line.rstrip("\r") for line in translated_half.split("\n")]
    if t_lines and t_lines[0] == "":
        t_lines.pop(0)

    # Drop trailing empty lines from raw; keep both arrays the same length
    while raw_lines and not raw_lines[-1]:
        raw_lines.pop()

    # Pad / truncate translated array to match raw
    if len(t_lines) < len(raw_lines):
        t_lines.extend("" for _ in range(len(raw_lines) - len(t_lines)))
    translated_lines = t_lines[: len(raw_lines)]

    return raw_lines, translated_lines, raw_section


def build_new_file(raw_input: str) -> str:
    """
    Convert a block of raw Japanese/Chinese text into the ---SEPERATOR--- format.

    Multi-sentence lines (split on 。) produce:
        %first_sentence。
        $continuation。
        ...
    Single-sentence lines produce a single %line entry.

    Equivalent to frmNew.btnCreate_Click.
    """
    # VB: Split(text, vbCr) then strip vbLf from each piece.
    # splitlines() handles \r\n, \n, and \r equivalently.
    lines = raw_input.splitlines()

    raw_parts: list[str] = []
    blank_count = 0  # one blank translated line per output line

    for line in lines:
        pieces = line.split("。")
        # VB: senCount = Split(line, "。").GetUpperBound(0) = len(pieces) - 1
        sen_count = len(pieces) - 1

        if sen_count < 1:
            # No 。 — single entry prefixed with %
            raw_parts.append(f"%{line}")
            blank_count += 1
            continue

        # Remove empty pieces produced by trailing 。 (VB: RemoveAll IsNullOrEmpty)
        non_empty = [p for p in pieces if p]
        if not non_empty:
            raw_parts.append(f"%{line}")
            blank_count += 1
            continue

        # First piece always prefixed with % and given its 。 back
        raw_parts.append(f"%{non_empty[0]}。")
        blank_count += 1

        for x, piece in enumerate(non_empty[1:], start=1):
            is_last = x == len(non_empty) - 1
            # Add 。 back unless this is the last piece of a line that didn't end with 。
            if not is_last or (is_last and line.endswith("。")):
                ender = "。"
            else:
                ender = ""
            raw_parts.append(f"${piece}{ender}")
            blank_count += 1

    raw_section = "\n".join(raw_parts) + "\n"
    blank_section = "\n" * blank_count
    return raw_section + "\n" + SEPARATOR + "\n" + blank_section


def save_file(filepath: Path, raw_section: str, translated_lines: list[str]) -> None:
    """
    Write translated lines back into the ---SEPERATOR--- file.

    raw_section must be the verbatim value returned by parse_file_content —
    written unchanged so the source text is never modified.
    """
    content = raw_section + SEPARATOR + "\n"
    for line in translated_lines:
        content += line + "\n"
    filepath.write_text(content, encoding="utf-8")


def lines_to_db_rows(
    raw_lines: list[str], translated_lines: list[str]
) -> list[dict]:
    """Convert in-memory arrays to the shape expected by db.save_lines()."""
    rows = []
    for i, ln in enumerate(raw_lines):
        if not ln:
            prefix, raw_text = "", ""
        elif ln[0] in ("%", "$"):
            prefix, raw_text = ln[0], ln[1:]
        else:
            prefix, raw_text = "%", ln
        rows.append({
            "line_number": i,
            "prefix": prefix,
            "raw_text": raw_text,
            "translated_text": translated_lines[i] if i < len(translated_lines) else "",
        })
    return rows


def db_rows_to_arrays(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Convert db.get_lines() output back to (raw_lines, translated_lines).

    Rows are sorted by line_number. Prefixes are prepended to raw_text for
    compatibility with the existing parse/display functions.
    """
    sorted_rows = sorted(rows, key=lambda r: r["line_number"])
    raw_lines = [r["prefix"] + r["raw_text"] for r in sorted_rows]
    translated_lines = [r["translated_text"] for r in sorted_rows]
    return raw_lines, translated_lines


def import_txt(path: Path, db, title: str | None = None, *,
               series_title: str = "", series_order: int = 0) -> int:
    """Read a ---SEPERATOR--- file and create a new document in the DB.

    Returns the new document id.
    Raises ValueError if the separator is missing.
    """
    text = path.read_text(encoding="utf-8")
    raw_lines, translated_lines, _ = parse_file_content(text)
    doc_title = title if title is not None else path.stem
    doc_id = db.create_document(
        doc_title, series_title=series_title, series_order=series_order
    )
    db.save_lines(doc_id, lines_to_db_rows(raw_lines, translated_lines))
    return doc_id


def export_txt(doc_id: int, path: Path, db) -> None:
    """Write a document from the DB back to the ---SEPERATOR--- file format."""
    rows = db.get_lines(doc_id)
    raw_lines, translated_lines = db_rows_to_arrays(rows)
    raw_section = "\n".join(raw_lines) + "\n"
    content = raw_section + SEPARATOR + "\n"
    for line in translated_lines:
        content += line + "\n"
    path.write_text(content, encoding="utf-8")


def load_glossary(path: Path) -> list[tuple[str, str]]:
    """
    Read a profile CSV and return (phrase, translation) pairs.

    Lines are "phrase,translation"; missing translation is treated as "".
    Blank lines are ignored.
    """
    if not path.exists():
        return []

    result: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 1)
        phrase = parts[0]
        translation = parts[1] if len(parts) > 1 else ""
        result.append((phrase, translation))
    return result


def batch_import_folder(
    folder: Path,
    db,
    *,
    series_title: str = "",
    csv_path: Path | None = None,
) -> dict:
    """Import all ---SEPERATOR--- TXT files from folder into the DB.

    Returns {"imported": [str], "skipped": [str], "errors": [(str, str)], "warnings": [str]}.
    Skips files whose title already exists. Alphabetical order = series_order.
    If csv_path is given, uses it as the glossary profile; otherwise auto-detects a single CSV in folder.
    """
    imported: list[str] = []
    skipped: list[str] = []
    errors: list[tuple[str, str]] = []
    warnings: list[str] = []

    txt_files = sorted(folder.glob("*.txt"))

    if csv_path is not None:
        profile_name = csv_path.stem
        pairs = load_glossary(csv_path)
        if db.get_profile_id(profile_name) is None:
            db.create_profile(profile_name)
        db.set_glossary(profile_name, pairs)
        if series_title:
            db.set_series_profile(series_title, profile_name)
    else:
        csv_files = list(folder.glob("*.csv"))
        if len(csv_files) > 1:
            warnings.append(
                f"Multiple CSV files found ({len(csv_files)}); glossary import skipped."
            )
        elif len(csv_files) == 1:
            csv_path = csv_files[0]
            profile_name = csv_path.stem
            pairs = load_glossary(csv_path)
            if db.get_profile_id(profile_name) is None:
                db.create_profile(profile_name)
            db.set_glossary(profile_name, pairs)
            if series_title:
                db.set_series_profile(series_title, profile_name)

    existing = {d["title"] for d in db.list_documents()}

    for i, path in enumerate(txt_files):
        stem = path.stem
        if stem in existing:
            skipped.append(stem)
            continue
        try:
            import_txt(path, db, title=stem, series_title=series_title, series_order=i)
            imported.append(stem)
        except Exception as exc:
            errors.append((stem, str(exc)))

    return {"imported": imported, "skipped": skipped, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Text processing
# ---------------------------------------------------------------------------

def replace_and_parse(
    text: str,
    glossary: list[tuple[str, str]],
    parse_chars: list[str],
) -> tuple[str, list[str], bool]:
    """
    Strip markers, apply glossary substitutions, and split into sentences.

    Returns (display_text, sentences, replaced) where:
    - display_text : the line with $ / % stripped and glossary applied
    - sentences    : sub-phrases split on the configured parse characters
    - replaced     : True if at least one glossary substitution was made
                     (the Ctrl+Left nav uses this to know whether a pre-
                     replacement state exists to revert to)
    """
    buf = text.replace("$", "").replace("%", "")

    replaced = False
    for phrase, translation in glossary:
        if phrase and phrase in buf:
            buf = buf.replace(phrase, translation)
            replaced = True

    # Split by each parse character; drop empty results (VB: RemoveEmptyEntries)
    sentences: list[str] = []
    if parse_chars:
        pattern = "|".join(re.escape(c) for c in parse_chars if c)
        if pattern:
            sentences = [s for s in re.split(pattern, buf) if s]
    if not sentences and buf:
        sentences = [buf]

    return buf, sentences, replaced


def build_review_text(
    raw_lines: list[str],
    translated_lines: list[str],
    start: int,
    end: int,
) -> tuple[str, dict[int, tuple[int, int]]]:
    """
    Build the display string for reviewTop or reviewBottom.

    Consecutive lines starting with '$' are concatenated onto the same visual
    row as their preceding '%' line.  Their translations are appended below,
    space-separated.  Empty raw lines produce blank lines.

    Returns (display_text, offset_map) where
    offset_map[i] = (char_start, char_end) for line index i.
    The double-click handler uses strict `char_start < cursor_pos < char_end`
    to navigate — matching the VB linenumber comparison exactly.

    NOTE: does not mutate raw_lines (the VB original stripped % in-place).
    """
    parts: list[str] = []
    offset_map: dict[int, tuple[int, int]] = {}
    char_pos = 0
    count = start

    while count <= end:
        line = raw_lines[count]
        if line:
            # Group this line with any consecutive $-continuation lines
            group_size = 0
            while True:
                idx = count + group_size
                stripped = raw_lines[idx].replace("%", "").replace("$", "")
                start_off = char_pos
                parts.append(stripped)
                char_pos += len(stripped)
                offset_map[idx] = (start_off, char_pos)

                group_size += 1
                next_idx = count + group_size
                if (next_idx > len(raw_lines) - 1
                        or next_idx > end
                        or not raw_lines[next_idx].startswith("$")):
                    break

            # Newline after the raw block
            parts.append("\n")
            char_pos += 1

            # Translations for every line in the group, space-separated
            for x in range(group_size):
                t = translated_lines[count + x]
                parts.append(t + " ")
                char_pos += len(t) + 1

            parts.append("\n\n")
            char_pos += 2
            count += group_size
        else:
            parts.append("\n")
            char_pos += 1
            count += 1

    return "".join(parts), offset_map


def line_has_content(raw: str) -> bool:
    """True if a raw line has translatable text (not a blank/marker-only line)."""
    return bool(raw.lstrip("%$").strip())


def calculate_progress(
    raw_lines: list[str], translated_lines: list[str]
) -> tuple[int, int]:
    """
    Return (completion_percent, word_count).

    completion_percent: lines with both raw and translated non-empty, expressed
    as a percentage of total non-empty raw lines.

    word_count: sum of token counts across all translated lines where tokens are
    split by a single space — matching VB's Split(str, " ").Count behaviour
    (empty tokens from leading / trailing spaces are included).
    """
    total_raw = sum(1 for r in raw_lines if line_has_content(r))
    if total_raw == 0:
        return 0, 0

    done = sum(1 for r, t in zip(raw_lines, translated_lines) if line_has_content(r) and t)
    word_count = sum(len(t.split(" ")) for t in translated_lines)
    percent = int((done / total_raw) * 100)
    return percent, word_count


def build_clipboard_output(
    raw_lines: list[str], translated_lines: list[str]
) -> str:
    """
    Assemble the final translated text for clipboard export.

    Continuation lines ($-prefixed) are merged with their paragraph head and
    their translations are space-joined.  Empty raw lines become blank lines.
    Equivalent to the assembly loop in menuClipboard_Click.
    """
    parts: list[str] = []
    count = 0
    n = len(raw_lines)

    while count < n:
        line = raw_lines[count]
        if line:
            # Count how many lines belong to this group (1 + any continuations)
            group_size = 1
            while (count + group_size < n
                   and raw_lines[count + group_size].startswith("$")):
                group_size += 1

            for x in range(group_size):
                parts.append(translated_lines[count + x] + " ")
            parts.append("\n")
            count += group_size
        else:
            parts.append("\n")
            count += 1

    return "".join(parts)


# ---------------------------------------------------------------------------
# build_markdown_translation
# ---------------------------------------------------------------------------


def build_markdown_translation(
    raw_lines: list[str],
    translated_lines: list[str],
    title: str = "",
) -> str:
    """
    Render translated lines as a plain Markdown document.

    Follows the same %/$ grouping as build_clipboard_output:
    consecutive $-prefixed lines merge with their % head.
    Untranslated groups are omitted. Empty raw lines become blank lines.
    """
    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n\n")
    count = 0
    n = len(raw_lines)
    while count < n:
        line = raw_lines[count]
        if line:
            group_size = 1
            while (count + group_size < n
                   and raw_lines[count + group_size].startswith("$")):
                group_size += 1
            translations = [translated_lines[count + x] for x in range(group_size)]
            text = " ".join(t for t in translations if t).strip()
            if text:
                parts.append(text + "\n\n")
            count += group_size
        else:
            parts.append("\n")
            count += 1
    return "".join(parts)


# ---------------------------------------------------------------------------
# build_markdown_ruby
# ---------------------------------------------------------------------------


def build_markdown_ruby(
    raw_lines: list[str],
    translated_lines: list[str],
    title: str = "",
) -> str:
    """
    Render an HTML ruby-annotated Markdown document.

    Each %/$ group becomes <ruby>translation<rt>original</rt></ruby>.
    Groups with no translation emit the raw text without a ruby wrapper.
    """
    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n\n")
    count = 0
    n = len(raw_lines)
    while count < n:
        line = raw_lines[count]
        if line:
            group_size = 1
            while (count + group_size < n
                   and raw_lines[count + group_size].startswith("$")):
                group_size += 1
            raw_text = "".join(
                raw_lines[count + x].lstrip("%$") for x in range(group_size)
            )
            translations = [translated_lines[count + x] for x in range(group_size)]
            translation = " ".join(t for t in translations if t).strip()
            if raw_text:
                if translation:
                    parts.append(
                        f"<ruby>{translation}<rt>{raw_text}</rt></ruby>\n\n"
                    )
                else:
                    parts.append(f"{raw_text}\n\n")
            count += group_size
        else:
            parts.append("\n")
            count += 1
    return "".join(parts)


# ---------------------------------------------------------------------------
# extract_frequent_nouns
# ---------------------------------------------------------------------------


def extract_frequent_nouns(
    raw_lines: list[str],
    already_in_glossary: set[str],
    min_freq: int = 2,
    *,
    _tagger=None,
) -> list[tuple[str, int]]:
    """
    Tokenize raw_lines with MeCab via fugashi, return (noun, count) pairs sorted by count desc.

    Skips: verbs, numbers (名詞-数詞), single-char tokens, terms in already_in_glossary.
    _tagger: injection seam — any object with .parse(str) -> str; defaults to fugashi.Tagger().
    Raises ImportError if fugashi is not installed and _tagger is None.
    """
    if _tagger is None:
        import fugashi as _fugashi
        _tagger = _fugashi.Tagger()

    counts: dict[str, int] = {}
    for line in raw_lines:
        if not line.strip():
            continue
        parsed = _tagger.parse(line)
        for token_line in parsed.split("\n"):
            if not token_line or token_line == "EOS":
                continue
            parts = token_line.split("\t")
            if len(parts) < 5:
                continue
            surface = parts[0]
            features = parts[4].split("-")
            if not features or features[0] != "名詞":
                continue
            if len(features) > 1 and features[1] == "数詞":
                continue
            if len(surface) < 2:
                continue
            if surface in already_in_glossary:
                continue
            counts[surface] = counts.get(surface, 0) + 1

    return sorted(
        [(term, cnt) for term, cnt in counts.items() if cnt >= min_freq],
        key=lambda x: x[1],
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def compute_streaks(history: list[dict]) -> dict:
    """
    Compute current streak, longest streak, and best day from daily stats history.

    Args:
        history: list of dicts with keys "date" (ISO string "YYYY-MM-DD") and
                 "paragraphs" (int).

    Returns:
        dict with keys:
        - current_streak: int (active or ended yesterday)
        - longest_streak: int (all time)
        - best_day_date: str (ISO date, empty if no data)
        - best_day_paras: int (max paragraphs, 0 if no data)
    """
    from datetime import date, timedelta

    active_set = {r["date"] for r in history if r["paragraphs"] > 0}
    active = sorted(active_set)

    if not active:
        return {"current_streak": 0, "longest_streak": 0, "best_day_date": "", "best_day_paras": 0}

    longest = 1
    run = 1
    for i in range(1, len(active)):
        prev = date.fromisoformat(active[i - 1])
        curr = date.fromisoformat(active[i])
        if (curr - prev).days == 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    today = date.today()
    check = today if today.isoformat() in active_set else today - timedelta(days=1)
    current = 0
    while check.isoformat() in active_set:
        current += 1
        check -= timedelta(days=1)

    best = max(history, key=lambda r: r["paragraphs"])
    return {
        "current_streak": current,
        "longest_streak": longest,
        "best_day_date": best["date"],
        "best_day_paras": best["paragraphs"],
    }

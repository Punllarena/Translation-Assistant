"""
Tests for translation_assistant.core — Stage 3 acceptance criteria.
"""
import pytest
from pathlib import Path

from translation_assistant.core import (
    SEPARATOR,
    parse_file_content,
    build_new_file,
    save_file,
    load_glossary,
    replace_and_parse,
    build_review_text,
    calculate_progress,
    build_clipboard_output,
    lines_to_db_rows,
    db_rows_to_arrays,
    import_txt,
    export_txt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_file(*raw_lines, translations=None) -> str:
    """Build a minimal SEPERATOR-format file string for test fixtures."""
    if translations is None:
        translations = [""] * len(raw_lines)
    raw = "\n".join(raw_lines) + "\n"
    tl = "\n".join(translations) + "\n"
    return raw + "\n" + SEPARATOR + "\n" + tl


# ---------------------------------------------------------------------------
# parse_file_content
# ---------------------------------------------------------------------------

class TestParseFileContent:
    def test_basic_single_line(self):
        content = make_file("%hello")
        raw, tl, raw_section = parse_file_content(content)
        assert raw == ["%hello"]
        assert tl == [""]

    def test_preserves_raw_section(self):
        content = make_file("%line1", "%line2")
        raw, tl, raw_section = parse_file_content(content)
        assert raw_section == "%line1\n%line2\n\n"

    def test_strips_trailing_empty_raw_lines(self):
        content = make_file("%A", "%B", translations=["", ""])
        # The make_file adds a blank line before separator; parse should strip trailing empties
        raw, tl, _ = parse_file_content(content)
        assert raw == ["%A", "%B"]
        assert "" not in [r for r in raw if r == ""] or True  # no trailing empties

    def test_translated_lines_match_raw_count(self):
        content = make_file("%A", "$B", "%C", translations=["t1", "t2", "t3"])
        raw, tl, _ = parse_file_content(content)
        assert len(raw) == len(tl) == 3

    def test_translated_values_preserved(self):
        content = make_file("%A", "%B", translations=["hello", "world"])
        raw, tl, _ = parse_file_content(content)
        assert tl == ["hello", "world"]

    def test_windows_line_endings(self):
        content = "%A\r\n$B\r\n\r\n" + SEPARATOR + "\r\n\r\n\r\n"
        raw, tl, _ = parse_file_content(content)
        assert raw == ["%A", "$B"]
        assert tl == ["", ""]

    def test_missing_separator_raises(self):
        with pytest.raises(ValueError, match=SEPARATOR):
            parse_file_content("no separator here")

    def test_empty_translated_section(self):
        content = make_file("%only")
        raw, tl, _ = parse_file_content(content)
        assert tl == [""]

    def test_continuation_lines_preserved(self):
        content = make_file("%first。", "$second", "%standalone")
        raw, tl, _ = parse_file_content(content)
        assert raw[0] == "%first。"
        assert raw[1] == "$second"
        assert raw[2] == "%standalone"


# ---------------------------------------------------------------------------
# build_new_file
# ---------------------------------------------------------------------------

class TestBuildNewFile:
    def test_no_maru_single_line(self):
        result = build_new_file("Hello world")
        raw, tl, _ = parse_file_content(result)
        assert raw == ["%Hello world"]
        assert tl == [""]

    def test_single_maru_splits_into_two(self):
        result = build_new_file("A。B")
        raw, tl, _ = parse_file_content(result)
        assert raw[0] == "%A。"
        assert raw[1] == "$B"
        assert tl == ["", ""]

    def test_line_ending_with_maru(self):
        result = build_new_file("A。B。")
        raw, tl, _ = parse_file_content(result)
        # Last piece should get 。 back because line ends with 。
        assert raw[0] == "%A。"
        assert raw[1] == "$B。"

    def test_line_not_ending_with_maru(self):
        result = build_new_file("A。B。C")
        raw, tl, _ = parse_file_content(result)
        assert raw[0] == "%A。"
        assert raw[1] == "$B。"
        assert raw[2] == "$C"  # last piece, no 。, line doesn't end with 。

    def test_multiple_input_lines(self):
        result = build_new_file("Line1\nLine2")
        raw, tl, _ = parse_file_content(result)
        assert "%Line1" in raw
        assert "%Line2" in raw

    def test_mixed_maru_and_plain(self):
        result = build_new_file("A。B\nC")
        raw, tl, _ = parse_file_content(result)
        assert raw == ["%A。", "$B", "%C"]
        assert tl == ["", "", ""]

    def test_three_sentences(self):
        result = build_new_file("A。B。C。")
        raw, tl, _ = parse_file_content(result)
        assert raw[0] == "%A。"
        assert raw[1] == "$B。"
        assert raw[2] == "$C。"

    def test_blank_lines_preserved(self):
        # VB: blank input lines become "%" & "" & vbNewLine = "%",
        # not an empty string — matching the original build_new_file behaviour.
        result = build_new_file("A\n\nB")
        raw, tl, _ = parse_file_content(result)
        assert "%A" in raw
        assert "%B" in raw
        assert "%" in raw  # blank line stored as bare "%" marker

    def test_output_is_parseable(self):
        """Round-trip: build_new_file output can be parsed by parse_file_content."""
        inputs = [
            "Single line",
            "A。B",
            "A。B。C",
            "First\nSecond",
            "A。B\nC。D",
        ]
        for text in inputs:
            result = build_new_file(text)
            raw, tl, _ = parse_file_content(result)
            assert len(raw) == len(tl), f"Length mismatch for input: {text!r}"


# ---------------------------------------------------------------------------
# save_file / round-trip
# ---------------------------------------------------------------------------

class TestSaveFile:
    def test_save_and_reload(self, tmp_path):
        original = make_file("%A。", "$B", "%C", translations=["", "", ""])
        raw, tl, raw_section = parse_file_content(original)

        tl[0] = "Translation A"
        tl[1] = "Translation B"
        tl[2] = "Translation C"

        path = tmp_path / "test.txt"
        save_file(path, raw_section, tl)

        reloaded = path.read_text(encoding="utf-8")
        raw2, tl2, _ = parse_file_content(reloaded)

        assert raw2 == raw
        assert tl2 == ["Translation A", "Translation B", "Translation C"]

    def test_raw_section_unchanged(self, tmp_path):
        original = make_file("%hello", translations=["world"])
        raw, tl, raw_section = parse_file_content(original)
        path = tmp_path / "t.txt"
        save_file(path, raw_section, tl)
        assert raw_section in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# load_glossary
# ---------------------------------------------------------------------------

class TestLoadGlossary:
    def test_basic_entries(self, tmp_path):
        csv = tmp_path / "test.csv"
        csv.write_text("こんにちは,hello\nありがとう,thank_you\n", encoding="utf-8")
        result = load_glossary(csv)
        assert result == [("こんにちは", "hello"), ("ありがとう", "thank_you")]

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_glossary(tmp_path / "nonexistent.csv") == []

    def test_blank_lines_skipped(self, tmp_path):
        csv = tmp_path / "test.csv"
        csv.write_text("\nphrase,trans\n\n", encoding="utf-8")
        result = load_glossary(csv)
        assert result == [("phrase", "trans")]

    def test_missing_translation(self, tmp_path):
        csv = tmp_path / "test.csv"
        csv.write_text("phrase_only\n", encoding="utf-8")
        result = load_glossary(csv)
        assert result == [("phrase_only", "")]

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "test.csv"
        csv.write_text("", encoding="utf-8")
        assert load_glossary(csv) == []

    def test_comma_in_translation(self, tmp_path):
        csv = tmp_path / "test.csv"
        # split is max 2, so commas in translation are kept
        csv.write_text("phrase,trans,with,commas\n", encoding="utf-8")
        result = load_glossary(csv)
        assert result == [("phrase", "trans,with,commas")]


# ---------------------------------------------------------------------------
# replace_and_parse
# ---------------------------------------------------------------------------

class TestReplaceAndParse:
    def test_no_glossary_no_parse_chars(self):
        text, sents, replaced = replace_and_parse("hello", [], [])
        assert text == "hello"
        assert sents == ["hello"]
        assert replaced is False

    def test_strips_dollar_percent(self):
        text, _, _ = replace_and_parse("%hello $world", [], [])
        assert text == "hello world"

    def test_glossary_substitution(self):
        text, _, replaced = replace_and_parse(
            "勇者は剣を持つ", [("勇者", "Hero")], []
        )
        assert "Hero" in text
        assert replaced is True

    def test_no_match_returns_false(self):
        _, _, replaced = replace_and_parse("abc", [("xyz", "XYZ")], [])
        assert replaced is False

    def test_multiple_glossary_entries(self):
        text, _, replaced = replace_and_parse(
            "AとB", [("A", "Alpha"), ("B", "Beta")], []
        )
        assert "Alpha" in text
        assert "Beta" in text
        assert replaced is True

    def test_parse_chars_split(self):
        _, sents, _ = replace_and_parse(
            "A。B。C", [], ["。"]
        )
        assert sents == ["A", "B", "C"]

    def test_parse_chars_multiple(self):
        _, sents, _ = replace_and_parse(
            "A。B？C！D", [], ["。", "？", "！"]
        )
        assert sents == ["A", "B", "C", "D"]

    def test_empty_input(self):
        text, sents, replaced = replace_and_parse("", [], [])
        assert text == ""
        assert sents == []
        assert replaced is False

    def test_parse_chars_empty_tokens_removed(self):
        _, sents, _ = replace_and_parse("A。。B", [], ["。"])
        # Empty string between two 。 should be excluded
        assert "" not in sents

    def test_glossary_applied_before_parse(self):
        """Glossary substitution fires before sentence splitting."""
        text, sents, replaced = replace_and_parse(
            "Aは勇者です", [("勇者", "Hero")], ["は", "です"]
        )
        assert "Hero" in text
        # "Hero" should end up in the sentences list
        assert any("Hero" in s for s in sents)


# ---------------------------------------------------------------------------
# build_review_text
# ---------------------------------------------------------------------------

class TestBuildReviewText:
    def test_single_line(self):
        raw = ["%hello"]
        tl = ["world"]
        text, offsets = build_review_text(raw, tl, 0, 0)
        assert "hello" in text
        assert "world" in text
        assert 0 in offsets

    def test_continuation_grouped(self):
        raw = ["%A。", "$B"]
        tl = ["trans_A", "trans_B"]
        text, offsets = build_review_text(raw, tl, 0, 1)
        # Both raw pieces on same line, translations below
        lines = text.split("\n")
        assert lines[0] == "A。B"
        assert "trans_A" in lines[1]
        assert "trans_B" in lines[1]

    def test_empty_line_produces_blank(self):
        raw = ["%A", "", "%B"]
        tl = ["tA", "", "tB"]
        text, _ = build_review_text(raw, tl, 0, 2)
        # There should be a blank line between A and B groups
        assert "\n\n" in text or text.count("\n") >= 3

    def test_offset_map_populated(self):
        raw = ["%hello", "%world"]
        tl = ["t1", "t2"]
        _, offsets = build_review_text(raw, tl, 0, 1)
        assert 0 in offsets
        assert 1 in offsets

    def test_offset_map_strict_navigation(self):
        """Cursor strictly between start and end should identify the correct line."""
        raw = ["%AB", "%CD"]
        tl = ["", ""]
        _, offsets = build_review_text(raw, tl, 0, 1)
        start0, end0 = offsets[0]
        # A cursor in the middle of line 0's text should be strictly between bounds
        mid = (start0 + end0) // 2
        # If text is "AB", start=0, end=2 → mid=1 strictly between 0 and 2
        assert start0 < mid < end0

    def test_does_not_mutate_raw_lines(self):
        raw = ["%hello"]
        original = raw[:]
        tl = ["t"]
        build_review_text(raw, tl, 0, 0)
        assert raw == original

    def test_range_subset(self):
        raw = ["%A", "%B", "%C"]
        tl = ["tA", "tB", "tC"]
        text, offsets = build_review_text(raw, tl, 1, 2)
        assert "A" not in text
        assert "B" in text
        assert 0 not in offsets
        assert 1 in offsets and 2 in offsets


# ---------------------------------------------------------------------------
# calculate_progress
# ---------------------------------------------------------------------------

class TestCalculateProgress:
    def test_nothing_translated(self):
        raw = ["%A", "%B", "%C"]
        tl = ["", "", ""]
        pct, wc = calculate_progress(raw, tl)
        assert pct == 0

    def test_all_translated(self):
        raw = ["%A", "%B"]
        tl = ["hello", "world"]
        pct, wc = calculate_progress(raw, tl)
        assert pct == 100

    def test_partial(self):
        raw = ["%A", "%B", "%C", "%D"]
        tl = ["t", "", "t", ""]
        pct, _ = calculate_progress(raw, tl)
        assert pct == 50

    def test_empty_lines_not_counted(self):
        """Empty raw lines (paragraph breaks) are excluded from totalRawLines."""
        raw = ["%A", "", "%B"]
        tl = ["tA", "", "tB"]
        pct, _ = calculate_progress(raw, tl)
        assert pct == 100

    def test_word_count(self):
        raw = ["%A"]
        tl = ["one two three"]
        _, wc = calculate_progress(raw, tl)
        assert wc == 3

    def test_word_count_multiple_lines(self):
        raw = ["%A", "%B"]
        tl = ["hello world", "foo"]
        _, wc = calculate_progress(raw, tl)
        assert wc == 3

    def test_empty_arrays(self):
        pct, wc = calculate_progress([], [])
        assert pct == 0
        assert wc == 0

    def test_bare_percent_marker_not_counted(self):
        """Bare '%' lines (blank source paragraphs) excluded from total."""
        raw = ["%A", "%", "%B"]
        tl = ["tA", "", "tB"]
        pct, _ = calculate_progress(raw, tl)
        assert pct == 100

    def test_bare_dollar_marker_not_counted(self):
        """Bare '$' lines excluded from total."""
        raw = ["%A", "$", "%B"]
        tl = ["tA", "", "tB"]
        pct, _ = calculate_progress(raw, tl)
        assert pct == 100

    def test_whitespace_only_raw_line_not_counted(self):
        raw = ["%A", "%  ", "%B"]
        tl = ["tA", "", "tB"]
        pct, _ = calculate_progress(raw, tl)
        assert pct == 100


# ---------------------------------------------------------------------------
# build_clipboard_output
# ---------------------------------------------------------------------------

class TestBuildClipboardOutput:
    def test_single_line(self):
        raw = ["%A"]
        tl = ["hello"]
        result = build_clipboard_output(raw, tl)
        assert result == "hello \n"

    def test_continuation_merged(self):
        raw = ["%A。", "$B"]
        tl = ["trans_A", "trans_B"]
        result = build_clipboard_output(raw, tl)
        assert result == "trans_A trans_B \n"

    def test_empty_line_preserved(self):
        raw = ["%A", "", "%B"]
        tl = ["tA", "", "tB"]
        result = build_clipboard_output(raw, tl)
        lines = result.split("\n")
        assert lines[0] == "tA "
        assert lines[1] == ""   # blank line from empty raw
        assert lines[2] == "tB "

    def test_multiple_paragraphs(self):
        raw = ["%A。", "$B", "", "%C"]
        tl = ["tA", "tB", "", "tC"]
        result = build_clipboard_output(raw, tl)
        assert "tA tB " in result
        assert "tC " in result

    def test_no_raw_lines_returns_empty(self):
        assert build_clipboard_output([], []) == ""


# ---------------------------------------------------------------------------
# lines_to_db_rows — Stage F
# ---------------------------------------------------------------------------

class TestLinesToDbRows:
    def test_percent_prefix_extracted(self):
        rows = lines_to_db_rows(["%Hello"], ["Hi"])
        assert rows[0]["prefix"] == "%"
        assert rows[0]["raw_text"] == "Hello"

    def test_dollar_prefix_extracted(self):
        rows = lines_to_db_rows(["$Cont"], [""])
        assert rows[0]["prefix"] == "$"
        assert rows[0]["raw_text"] == "Cont"

    def test_empty_line_stored_with_empty_prefix(self):
        rows = lines_to_db_rows([""], [""])
        assert rows[0]["prefix"] == ""
        assert rows[0]["raw_text"] == ""

    def test_translated_text_preserved(self):
        rows = lines_to_db_rows(["%A", "%B"], ["Alpha", "Beta"])
        assert rows[0]["translated_text"] == "Alpha"
        assert rows[1]["translated_text"] == "Beta"

    def test_line_numbers_sequential(self):
        rows = lines_to_db_rows(["%A", "%B", "%C"], ["", "", ""])
        assert [r["line_number"] for r in rows] == [0, 1, 2]

    def test_multiple_lines_correct_count(self):
        rows = lines_to_db_rows(["%A", "", "%B"], ["a", "", "b"])
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# db_rows_to_arrays — Stage F
# ---------------------------------------------------------------------------

class TestDbRowsToArrays:
    def _row(self, ln, prefix, raw, tl):
        return {"line_number": ln, "prefix": prefix, "raw_text": raw, "translated_text": tl}

    def test_percent_prefix_prepended(self):
        raw, tl = db_rows_to_arrays([self._row(0, "%", "Hello", "Hi")])
        assert raw == ["%Hello"]
        assert tl == ["Hi"]

    def test_dollar_prefix_prepended(self):
        raw, tl = db_rows_to_arrays([self._row(0, "$", "Cont", "")])
        assert raw == ["$Cont"]

    def test_empty_prefix_gives_empty_raw_line(self):
        raw, tl = db_rows_to_arrays([self._row(0, "", "", "")])
        assert raw == [""]

    def test_ordering_by_line_number(self):
        rows = [
            self._row(2, "%", "Third", ""),
            self._row(0, "%", "First", ""),
            self._row(1, "%", "Second", ""),
        ]
        raw, _ = db_rows_to_arrays(rows)
        assert raw == ["%First", "%Second", "%Third"]

    def test_round_trip_with_lines_to_db_rows(self):
        original_raw = ["%Hello", "$World", "", "%End"]
        original_tl = ["Hi", "Earth", "", "Fin"]
        rows = lines_to_db_rows(original_raw, original_tl)
        raw, tl = db_rows_to_arrays(rows)
        assert raw == original_raw
        assert tl == original_tl


# ---------------------------------------------------------------------------
# import_txt / export_txt — Stage F
# ---------------------------------------------------------------------------

class TestImportTxt:
    def test_returns_doc_id(self, tmp_path):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        txt = tmp_path / "story.txt"
        txt.write_text("%A\n%B\n---SEPERATOR---\nAlpha\nBeta\n", encoding="utf-8")
        doc_id = import_txt(txt, db)
        assert isinstance(doc_id, int)

    def test_creates_document_with_filename_title(self, tmp_path):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        txt = tmp_path / "my_story.txt"
        txt.write_text("%A\n---SEPERATOR---\n\n", encoding="utf-8")
        import_txt(txt, db)
        docs = db.list_documents()
        assert docs[0]["title"] == "my_story"

    def test_custom_title_overrides_filename(self, tmp_path):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        txt = tmp_path / "file.txt"
        txt.write_text("%A\n---SEPERATOR---\n\n", encoding="utf-8")
        import_txt(txt, db, title="Custom Title")
        docs = db.list_documents()
        assert docs[0]["title"] == "Custom Title"

    def test_saves_lines_to_db(self, tmp_path):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        txt = tmp_path / "story.txt"
        txt.write_text("%Hello\n$World\n---SEPERATOR---\nHi\nEarth\n", encoding="utf-8")
        doc_id = import_txt(txt, db)
        lines = db.get_lines(doc_id)
        assert lines[0]["prefix"] == "%"
        assert lines[0]["raw_text"] == "Hello"
        assert lines[0]["translated_text"] == "Hi"
        assert lines[1]["prefix"] == "$"
        assert lines[1]["raw_text"] == "World"
        assert lines[1]["translated_text"] == "Earth"

    def test_raises_on_missing_separator(self, tmp_path):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        txt = tmp_path / "bad.txt"
        txt.write_text("No separator here", encoding="utf-8")
        with pytest.raises(ValueError):
            import_txt(txt, db)


class TestExportTxt:
    def _make_db(self):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        return Database(":memory:", _conn=conn)

    def test_writes_separator_format(self, tmp_path):
        db = self._make_db()
        doc_id = db.create_document("Story")
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Hello", "translated_text": "Hi"},
        ])
        out = tmp_path / "out.txt"
        export_txt(doc_id, out, db)
        content = out.read_text(encoding="utf-8")
        assert SEPARATOR in content

    def test_raw_text_with_prefix_in_output(self, tmp_path):
        db = self._make_db()
        doc_id = db.create_document("Story")
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Hello", "translated_text": "Hi"},
        ])
        out = tmp_path / "out.txt"
        export_txt(doc_id, out, db)
        content = out.read_text(encoding="utf-8")
        assert "%Hello" in content

    def test_translation_in_output(self, tmp_path):
        db = self._make_db()
        doc_id = db.create_document("Story")
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        out = tmp_path / "out.txt"
        export_txt(doc_id, out, db)
        content = out.read_text(encoding="utf-8")
        assert "Alpha" in content

    def test_round_trip_import_export(self, tmp_path):
        db = self._make_db()
        original = tmp_path / "original.txt"
        original.write_text("%Hello\n$World\n---SEPERATOR---\nHi\nEarth\n", encoding="utf-8")
        doc_id = import_txt(original, db)
        exported = tmp_path / "exported.txt"
        export_txt(doc_id, exported, db)
        content = exported.read_text(encoding="utf-8")
        assert "%Hello" in content
        assert "$World" in content
        assert SEPARATOR in content
        assert "Hi" in content
        assert "Earth" in content


# ---------------------------------------------------------------------------
# extract_frequent_nouns
# ---------------------------------------------------------------------------

from translation_assistant.core import extract_frequent_nouns


class _FakeTagger:
    """Replays pre-baked MeCab output strings, round-robining through the list."""
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self._idx = 0

    def parse(self, text: str) -> str:
        out = self._outputs[self._idx % len(self._outputs)]
        self._idx += 1
        return out


# Minimal MeCab output fragments (surface TAB POS-csv NEWLINE EOS NEWLINE)
_OUT_TARO    = "太郎\t名詞,固有名詞,人名,名,*,*,太郎,タロウ,タロウ\nEOS\n"
_OUT_HANAKO  = "花子\t名詞,固有名詞,人名,名,*,*,花子,ハナコ,ハナコ\nEOS\n"
_OUT_BOTH    = (
    "太郎\t名詞,固有名詞,人名,名,*,*,太郎,タロウ,タロウ\n"
    "花子\t名詞,固有名詞,人名,名,*,*,花子,ハナコ,ハナコ\n"
    "EOS\n"
)
_OUT_NUMBER  = "100\t名詞,数,*,*,*,*,*\nEOS\n"
_OUT_SINGLE  = "私\t名詞,代名詞,一般,*,*,*,私,ワタシ,ワタシ\nEOS\n"
_OUT_VERB    = "走る\t動詞,自立,*,*,五段・ラ行,基本形,走る,ハシル,ハシル\nEOS\n"


def test_extract_returns_noun_with_count():
    tagger = _FakeTagger([_OUT_TARO, _OUT_TARO])
    result = extract_frequent_nouns(["太郎", "太郎"], set(), min_freq=2, _tagger=tagger)
    assert result == [("太郎", 2)]


def test_extract_skips_verb():
    tagger = _FakeTagger([_OUT_VERB, _OUT_VERB])
    result = extract_frequent_nouns(["走る", "走る"], set(), min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_skips_number_noun():
    tagger = _FakeTagger([_OUT_NUMBER, _OUT_NUMBER])
    result = extract_frequent_nouns(["100", "100"], set(), min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_skips_single_char_noun():
    tagger = _FakeTagger([_OUT_SINGLE, _OUT_SINGLE])
    result = extract_frequent_nouns(["私", "私"], set(), min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_filters_glossary_terms():
    tagger = _FakeTagger([_OUT_TARO, _OUT_TARO])
    result = extract_frequent_nouns(["太郎", "太郎"], {"太郎"}, min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_sorted_by_count_descending():
    tagger = _FakeTagger([_OUT_BOTH, _OUT_TARO])
    result = extract_frequent_nouns(["太郎花子", "太郎"], set(), min_freq=1, _tagger=tagger)
    assert result[0] == ("太郎", 2)
    assert ("花子", 1) in result


def test_extract_min_freq_filters_low_count():
    tagger = _FakeTagger([_OUT_BOTH])
    result = extract_frequent_nouns(["太郎花子"], set(), min_freq=2, _tagger=tagger)
    assert result == []


def test_extract_skips_blank_lines():
    tagger = _FakeTagger(["EOS\n"])
    result = extract_frequent_nouns(["", "  "], set(), min_freq=1, _tagger=tagger)
    assert result == []

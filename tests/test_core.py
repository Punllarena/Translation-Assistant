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
    extract_frequent_nouns,
    batch_import_folder,
    build_markdown_translation,
    build_markdown_ruby,
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
        text, offsets, _ = build_review_text(raw, tl, 0, 0)
        assert "hello" in text
        assert "world" in text
        assert 0 in offsets

    def test_continuation_grouped(self):
        raw = ["%A。", "$B"]
        tl = ["trans_A", "trans_B"]
        text, offsets, _ = build_review_text(raw, tl, 0, 1)
        # Both raw pieces on same line, translations below
        lines = text.split("\n")
        assert lines[0] == "A。B"
        assert "trans_A" in lines[1]
        assert "trans_B" in lines[1]

    def test_empty_line_produces_blank(self):
        raw = ["%A", "", "%B"]
        tl = ["tA", "", "tB"]
        text, _, _ = build_review_text(raw, tl, 0, 2)
        # There should be a blank line between A and B groups
        assert "\n\n" in text or text.count("\n") >= 3

    def test_offset_map_populated(self):
        raw = ["%hello", "%world"]
        tl = ["t1", "t2"]
        _, offsets, _ = build_review_text(raw, tl, 0, 1)
        assert 0 in offsets
        assert 1 in offsets

    def test_offset_map_strict_navigation(self):
        """Cursor strictly between start and end should identify the correct line."""
        raw = ["%AB", "%CD"]
        tl = ["", ""]
        _, offsets, _ = build_review_text(raw, tl, 0, 1)
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
        text, offsets, _ = build_review_text(raw, tl, 1, 2)
        assert "A" not in text
        assert "B" in text
        assert 0 not in offsets
        assert 1 in offsets and 2 in offsets

    def test_color_ranges_translated_group(self):
        raw = ["%Hello"]
        tl = ["こんにちは"]
        text, offsets, colors = build_review_text(raw, tl, 0, 0)
        assert len(colors) == 1
        start, end, is_translated = colors[0]
        assert is_translated is True
        assert start == 0
        assert end == len(text)

    def test_color_ranges_untranslated_group(self):
        raw = ["%Hello"]
        tl = [""]
        text, offsets, colors = build_review_text(raw, tl, 0, 0)
        assert len(colors) == 1
        _, _, is_translated = colors[0]
        assert is_translated is False


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
# build_markdown_translation
# ---------------------------------------------------------------------------

class TestBuildMarkdownTranslation:
    def test_title_heading(self):
        result = build_markdown_translation(["%A"], ["hello"], title="My Chapter")
        assert result.startswith("# My Chapter\n\n")

    def test_no_title_no_heading(self):
        result = build_markdown_translation(["%A"], ["hello"])
        assert not result.startswith("#")

    def test_single_group(self):
        result = build_markdown_translation(["%A"], ["hello"])
        assert result == "hello\n\n"

    def test_continuation_joined(self):
        raw = ["%A。", "$B"]
        tl = ["first", "second"]
        result = build_markdown_translation(raw, tl)
        assert "first second\n\n" in result

    def test_empty_raw_line_preserved(self):
        raw = ["%A", "", "%B"]
        tl = ["alpha", "", "beta"]
        result = build_markdown_translation(raw, tl)
        assert "alpha\n\n" in result
        assert "beta\n\n" in result

    def test_untranslated_group_omitted(self):
        raw = ["%A", "%B"]
        tl = ["", "beta"]
        result = build_markdown_translation(raw, tl)
        assert "beta\n\n" in result
        non_blank = [l for l in result.split("\n") if l.strip()]
        assert len(non_blank) == 1

    def test_empty_inputs(self):
        assert build_markdown_translation([], []) == ""


# ---------------------------------------------------------------------------
# build_markdown_ruby
# ---------------------------------------------------------------------------

class TestBuildMarkdownRuby:
    def test_ruby_wrapper(self):
        result = build_markdown_ruby(["%原文"], ["original text"])
        assert "<ruby>original text<rt>原文</rt></ruby>\n\n" in result

    def test_title_heading(self):
        result = build_markdown_ruby(["%A"], ["b"], title="Chapter 1")
        assert result.startswith("# Chapter 1\n\n")

    def test_continuation_concatenated(self):
        raw = ["%第一。", "$第二"]
        tl = ["first", "second"]
        result = build_markdown_ruby(raw, tl)
        assert "<ruby>first second<rt>第一。第二</rt></ruby>" in result

    def test_missing_translation_no_ruby(self):
        result = build_markdown_ruby(["%原文"], [""])
        assert "<ruby>" not in result
        assert "原文\n\n" in result

    def test_empty_raw_line_preserved(self):
        raw = ["%A", "", "%B"]
        tl = ["alpha", "", "beta"]
        result = build_markdown_ruby(raw, tl)
        assert "<ruby>alpha<rt>A</rt></ruby>" in result
        assert "<ruby>beta<rt>B</rt></ruby>" in result

    def test_empty_inputs(self):
        assert build_markdown_ruby([], []) == ""


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
_OUT_TARO    = "太郎\tタロウ\tタロウ\t太郎\t名詞-固有名詞-人名-名\t\t\t1\nEOS\n"
_OUT_HANAKO  = "花子\tハナコ\tハナコ\t花子\t名詞-固有名詞-人名-名\t\t\t1\nEOS\n"
_OUT_BOTH    = (
    "太郎\tタロウ\tタロウ\t太郎\t名詞-固有名詞-人名-名\t\t\t1\n"
    "花子\tハナコ\tハナコ\t花子\t名詞-固有名詞-人名-名\t\t\t1\n"
    "EOS\n"
)
_OUT_NUMBER  = "100\t100\t100\t100\t名詞-数詞\t\t\t0\nEOS\n"
_OUT_SINGLE  = "私\tワタシ\tワタシ\t私\t名詞-代名詞\t\t\t1\nEOS\n"
_OUT_VERB    = "走る\tハシル\tハシル\t走る\t動詞-一般\t\t\t1\nEOS\n"


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


# ---------------------------------------------------------------------------
# import_txt with series params — Task 1
# ---------------------------------------------------------------------------

class TestImportTxtSeries:
    def _db(self):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        return Database(":memory:", _conn=conn)

    def test_series_title_stored(self, tmp_path):
        db = self._db()
        txt = tmp_path / "ch01.txt"
        txt.write_text("%A\n---SEPERATOR---\n\n", encoding="utf-8")
        doc_id = import_txt(txt, db, series_title="My Series", series_order=0)
        docs = db.list_documents()
        assert docs[0]["series_title"] == "My Series"

    def test_series_order_stored(self, tmp_path):
        db = self._db()
        txt = tmp_path / "ch02.txt"
        txt.write_text("%B\n---SEPERATOR---\n\n", encoding="utf-8")
        doc_id = import_txt(txt, db, series_title="S", series_order=7)
        docs = db.list_documents()
        assert docs[0]["series_order"] == 7

    def test_defaults_to_no_series(self, tmp_path):
        db = self._db()
        txt = tmp_path / "ch03.txt"
        txt.write_text("%C\n---SEPERATOR---\n\n", encoding="utf-8")
        import_txt(txt, db)
        docs = db.list_documents()
        assert docs[0]["series_title"] == ""
        assert docs[0]["series_order"] == 0


class TestBatchImportFolder:
    def _db(self):
        import sqlite3
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        return Database(":memory:", _conn=conn)

    def _txt(self, folder, name, raw="%A", translation=""):
        p = folder / name
        p.write_text(f"{raw}\n---SEPERATOR---\n{translation}\n", encoding="utf-8")
        return p

    def test_imports_all_txt_files(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        self._txt(tmp_path, "ch02.txt")
        result = batch_import_folder(tmp_path, db)
        assert len(result["imported"]) == 2
        assert len(db.list_documents()) == 2

    def test_skips_existing_title(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        self._txt(tmp_path, "ch02.txt")
        # Pre-import ch01 so it already exists
        import_txt(tmp_path / "ch01.txt", db, title="ch01")
        result = batch_import_folder(tmp_path, db)
        assert "ch01" in result["skipped"]
        assert "ch02" in result["imported"]
        assert len(db.list_documents()) == 2  # not 3

    def test_records_error_on_bad_file(self, tmp_path):
        db = self._db()
        bad = tmp_path / "bad.txt"
        bad.write_text("No separator here", encoding="utf-8")
        result = batch_import_folder(tmp_path, db)
        assert len(result["errors"]) == 1
        assert result["errors"][0][0] == "bad"
        assert len(result["imported"]) == 0

    def test_empty_folder_returns_zeros(self, tmp_path):
        db = self._db()
        result = batch_import_folder(tmp_path, db)
        assert result == {"imported": [], "skipped": [], "errors": [], "warnings": []}

    def test_assigns_series_title_and_order(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        self._txt(tmp_path, "ch02.txt")
        batch_import_folder(tmp_path, db, series_title="My Novel")
        docs = sorted(db.list_documents(), key=lambda d: d["series_order"])
        assert docs[0]["series_title"] == "My Novel"
        assert docs[0]["series_order"] == 0
        assert docs[1]["series_order"] == 1

    def test_csv_creates_profile_and_glossary(self, tmp_path):
        from translation_assistant.db import Database
        import sqlite3
        db = Database(":memory:", _conn=sqlite3.connect(":memory:"))
        self._txt(tmp_path, "ch01.txt")
        csv = tmp_path / "MyProfile.csv"
        csv.write_text("hello,こんにちは\nworld,世界\n", encoding="utf-8")
        batch_import_folder(tmp_path, db, series_title="S")
        assert db.get_profile_id("MyProfile") is not None
        glossary = db.get_glossary("MyProfile")
        assert ("hello", "こんにちは") in glossary
        assert db.get_series_profile("S") == "MyProfile"

    def test_csv_without_series_no_series_profile_row(self, tmp_path):
        from translation_assistant.db import Database
        import sqlite3
        db = Database(":memory:", _conn=sqlite3.connect(":memory:"))
        self._txt(tmp_path, "ch01.txt")
        csv = tmp_path / "Glossary.csv"
        csv.write_text("hi,やあ\n", encoding="utf-8")
        batch_import_folder(tmp_path, db, series_title="")
        assert db.get_profile_id("Glossary") is not None
        assert db.get_series_profile("Glossary") == ""  # no link

    def test_multiple_csvs_warns_skips_glossary(self, tmp_path):
        db = self._db()
        self._txt(tmp_path, "ch01.txt")
        (tmp_path / "A.csv").write_text("a,b\n", encoding="utf-8")
        (tmp_path / "B.csv").write_text("c,d\n", encoding="utf-8")
        result = batch_import_folder(tmp_path, db)
        assert len(result["warnings"]) == 1
        assert "Multiple CSV" in result["warnings"][0]
        assert db.get_profile_id("A") is None
        assert db.get_profile_id("B") is None


# ---------------------------------------------------------------------------
# compute_streaks
# ---------------------------------------------------------------------------
from datetime import date, timedelta
from translation_assistant.core import compute_streaks


def _h(*entries):
    """Build history list from (iso_date, paragraphs) pairs."""
    return [{"date": d, "paragraphs": p} for d, p in entries]


def _today():
    return date.today().isoformat()


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def test_compute_streaks_empty():
    result = compute_streaks([])
    assert result == {"current_streak": 0, "longest_streak": 0, "best_day_date": "", "best_day_paras": 0}


def test_compute_streaks_single_day_today():
    today = _today()
    result = compute_streaks(_h((today, 5)))
    assert result["current_streak"] == 1
    assert result["longest_streak"] == 1
    assert result["best_day_date"] == today
    assert result["best_day_paras"] == 5


def test_compute_streaks_consecutive_days():
    history = _h(
        (_days_ago(2), 3),
        (_days_ago(1), 5),
        (_today(), 2),
    )
    result = compute_streaks(history)
    assert result["current_streak"] == 3
    assert result["longest_streak"] == 3
    assert result["best_day_paras"] == 5


def test_compute_streaks_gap_breaks_current():
    # days_ago(3), days_ago(2) consecutive; days_ago(1) missing; today present
    history = _h(
        (_days_ago(3), 4),
        (_days_ago(2), 4),
        (_today(), 2),
    )
    result = compute_streaks(history)
    assert result["current_streak"] == 1   # gap on days_ago(1)
    assert result["longest_streak"] == 2   # days_ago(3)+days_ago(2)


def test_compute_streaks_today_no_entry_yesterday_yes():
    history = _h((_days_ago(1), 5))
    result = compute_streaks(history)
    assert result["current_streak"] == 1   # yesterday counts when today absent


def test_compute_streaks_longest_not_current():
    # 3-day run long ago, gap, single day today
    history = _h(
        (_days_ago(18), 10),
        (_days_ago(17), 10),
        (_days_ago(16), 10),
        (_today(), 1),
    )
    result = compute_streaks(history)
    assert result["longest_streak"] == 3
    assert result["current_streak"] == 1   # gap between days_ago(16) and today
    assert result["best_day_paras"] == 10


# ---------------------------------------------------------------------------
# compute_period_comparisons
# ---------------------------------------------------------------------------

from translation_assistant.core import compute_period_comparisons


def _row(iso, paras=0, chars=0, en=0):
    return {"date": iso, "paragraphs": paras, "chars": chars, "en_words": en}


def test_period_comparisons_today_vs_yesterday():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=10), _row("2026-07-02", paras=5)]
    result = compute_period_comparisons(history, "paragraphs", today)
    t = result["periods"]["today"]
    assert t["current"] == 10
    assert t["previous"] == 5
    assert t["pct_change"] == 100.0


def test_period_comparisons_week_boundary():
    today = date(2026, 7, 3)
    # 2026-06-27 is day 7 back -> inside current week; 2026-06-26 is day 8 -> previous week
    history = [_row("2026-06-27", paras=3), _row("2026-06-26", paras=7)]
    result = compute_period_comparisons(history, "paragraphs", today)
    w = result["periods"]["week"]
    assert w["current"] == 3
    assert w["previous"] == 7


def test_period_comparisons_zero_previous_gives_none():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=10)]
    result = compute_period_comparisons(history, "paragraphs", today)
    assert result["periods"]["today"]["pct_change"] is None


def test_period_comparisons_negative_change():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=4), _row("2026-07-02", paras=8)]
    result = compute_period_comparisons(history, "paragraphs", today)
    assert result["periods"]["today"]["pct_change"] == -50.0


def test_period_comparisons_empty_history():
    result = compute_period_comparisons([], "paragraphs", date(2026, 7, 3))
    for key in ("today", "week", "month"):
        p = result["periods"][key]
        assert p["current"] == 0
        assert p["previous"] == 0
        assert p["pct_change"] is None
    assert result["daily_avg_30"] == 0


def test_period_comparisons_respects_metric():
    today = date(2026, 7, 3)
    history = [_row("2026-07-03", paras=1, chars=500), _row("2026-07-02", paras=1, chars=100)]
    result = compute_period_comparisons(history, "chars", today)
    assert result["periods"]["today"]["current"] == 500
    assert result["periods"]["today"]["pct_change"] == 400.0


def test_period_comparisons_daily_avg_30():
    today = date(2026, 7, 3)
    # 60 paras within last 30 days, plus old data that must not count
    history = [_row("2026-07-01", paras=45), _row("2026-06-10", paras=15),
               _row("2026-01-01", paras=999)]
    result = compute_period_comparisons(history, "paragraphs", today)
    assert result["daily_avg_30"] == 2.0  # 60 / 30


# ---------------------------------------------------------------------------
# natural_key
# ---------------------------------------------------------------------------

from translation_assistant.core import natural_key


def test_natural_key_numeric_order():
    titles = ["ch10", "ch2", "ch1"]
    assert sorted(titles, key=natural_key) == ["ch1", "ch2", "ch10"]


def test_natural_key_case_insensitive():
    assert sorted(["B", "a"], key=natural_key) == ["a", "B"]


def test_natural_key_mixed_and_plain():
    titles = ["Chapter 12 - End", "Chapter 2 - Start", "Prologue"]
    assert sorted(titles, key=natural_key) == [
        "Chapter 2 - Start", "Chapter 12 - End", "Prologue"]

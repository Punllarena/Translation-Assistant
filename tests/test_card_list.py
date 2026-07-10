"""
Tests for the card-list chapter view.
"""
import pytest
from PySide6.QtCore import Qt

from translation_assistant.ui.card_list import glossary_html


class TestGlossaryHtml:
    def test_strips_markers(self):
        assert glossary_html("%Hello", []) == "Hello"
        assert glossary_html("$World", []) == "World"

    def test_escapes_html(self):
        out = glossary_html("%a <b> & c", [])
        assert "&lt;b&gt;" in out
        assert "&amp;" in out

    def test_wraps_glossary_replacement_in_amber_span(self):
        out = glossary_html("%ホロウ駅へ", [("ホロウ", "Hollow")])
        assert ">Hollow</span>" in out
        assert "ホロウ" not in out
        assert "#e6c46a" in out

    def test_multiple_replacements(self):
        # Sequential like core.replace_and_parse, but chained matches into a
        # previous replacement's output are not re-matched (markup in between).
        out = glossary_html("%abc", [("a", "X"), ("c", "Y")])
        assert ">X</span>" in out
        assert ">Y</span>" in out

    def test_escapes_glossary_translation(self):
        out = glossary_html("%ホロウ", [("ホロウ", "<i>H</i>")])
        assert "&lt;i&gt;H&lt;/i&gt;" in out

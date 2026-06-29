import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def highlighter(qapp):
    from PySide6.QtGui import QTextDocument
    from translation_assistant.jp_highlighter import JpSyntaxHighlighter
    doc = QTextDocument()
    h = JpSyntaxHighlighter(doc)
    return h


def _make_fugashi_word(surface, pos1="名詞", kana="", lemma=""):
    from unittest.mock import MagicMock
    w = MagicMock()
    w.surface = surface
    w.feature.pos1 = pos1
    w.feature.kana = kana
    w.feature.lemma = lemma
    w.feature.pron = ""
    return w


def test_token_info_at_no_tagger(highlighter):
    """Returns empty string when no tagger available."""
    highlighter._tagger = None
    assert highlighter.token_info_at("語彙", 0) == ""


def test_token_info_at_returns_surface(highlighter):
    """Surface form always appears in tooltip text."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("語彙", pos1="名詞", kana="ゴイ", lemma="語彙")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    result = highlighter.token_info_at("語彙", 0)
    assert "語彙" in result


def test_token_info_at_includes_pos(highlighter):
    """POS tag appears in tooltip text."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("走る", pos1="動詞", kana="ハシル", lemma="走る")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    result = highlighter.token_info_at("走る", 0)
    assert "動詞" in result


def test_token_info_at_includes_reading(highlighter):
    """Kana reading appears when different from surface."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("語彙", pos1="名詞", kana="ゴイ", lemma="語彙")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    result = highlighter.token_info_at("語彙", 0)
    assert "ゴイ" in result


def test_token_info_at_char_pos_selects_correct_token(highlighter):
    """char_pos selects the token that spans that position."""
    from unittest.mock import MagicMock
    words = [
        _make_fugashi_word("語彙", pos1="名詞", kana="ゴイ"),   # pos 0–1
        _make_fugashi_word("が", pos1="助詞", kana="ガ"),         # pos 2
    ]
    highlighter._tagger = MagicMock(return_value=words)
    highlighter._use_fugashi = True
    result_noun = highlighter.token_info_at("語彙が", 0)
    result_particle = highlighter.token_info_at("語彙が", 2)
    assert "名詞" in result_noun
    assert "助詞" in result_particle


def test_token_info_at_out_of_range(highlighter):
    """Returns empty string for char_pos beyond all tokens."""
    from unittest.mock import MagicMock
    word = _make_fugashi_word("語彙")
    highlighter._tagger = MagicMock(return_value=[word])
    highlighter._use_fugashi = True
    assert highlighter.token_info_at("語彙", 99) == ""


def test_instantiation_does_not_raise(qapp):
    """JpSyntaxHighlighter instantiates without error even if MeCab absent."""
    from PySide6.QtGui import QTextDocument
    from translation_assistant.jp_highlighter import JpSyntaxHighlighter
    doc = QTextDocument()
    h = JpSyntaxHighlighter(doc)  # must not raise
    assert h is not None

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


from translation_assistant.ui.card_list import LineCard  # noqa: E402


@pytest.fixture
def card(qapp):
    c = LineCard(3, 4, "Source text", "Existing translation")
    yield c
    c.deleteLater()


class TestLineCard:
    def test_holds_index_and_number(self, card):
        assert card.index == 3
        assert card._num_label.text() == "4"

    def test_source_label_shows_html(self, card):
        assert "Source text" in card.source_label.text()

    def test_initial_state_from_translation(self, qapp):
        done = LineCard(0, 1, "s", "t")
        todo = LineCard(1, 2, "s", "")
        assert done.state() == "done"
        assert todo.state() == "todo"
        done.deleteLater()
        todo.deleteLater()

    def test_set_state_updates_status_text(self, card):
        card.set_state("active")
        assert card.state() == "active"
        assert card._status_label.text() == "In progress"
        card.set_state("done")
        assert card._status_label.text() == "Translated"
        card.set_state("todo")
        assert card._status_label.text() == "Not started"

    def test_set_translation_updates_label_and_state_basis(self, card):
        card.set_translation("")
        assert card.translation_text() == ""
        assert card._trans_label.property("empty") is True
        card.set_translation("Hi")
        assert card.translation_text() == "Hi"
        assert "Hi" in card._trans_label.text()

    def test_attach_detach_moves_editors(self, card, qapp):
        from PySide6.QtWidgets import QTextEdit
        src, tr = QTextEdit(), QTextEdit()
        card.attach(src, tr)
        assert src.parent() is not None
        assert card.source_label.isHidden()
        assert card._trans_label.isHidden()
        card.detach(src, tr)
        assert src.parent() is None
        assert not card.source_label.isHidden()

    def test_detach_recomputes_state(self, card, qapp):
        from PySide6.QtWidgets import QTextEdit
        src, tr = QTextEdit(), QTextEdit()
        card.set_state("active")
        card.set_translation("")
        card.attach(src, tr)
        card.detach(src, tr)
        assert card.state() == "todo"

    def test_click_emits_index(self, card, qapp):
        got = []
        card.clicked.connect(got.append)
        from PySide6.QtTest import QTest
        QTest.mouseClick(card, Qt.MouseButton.LeftButton)
        assert got == [3]

    def test_copied_pill_hidden_initially(self, card):
        assert card._copied_pill.isHidden()

    def test_show_copied_pill_makes_visible(self, card, qapp):
        card.show()
        card.show_copied_pill()
        assert not card._copied_pill.isHidden()

    def test_set_font_size(self, card):
        card.set_font_size(21.0)
        assert abs(card.source_label.font().pointSizeF() - 21.0) < 0.1
        assert abs(card._trans_label.font().pointSizeF() - 21.0) < 0.1


from translation_assistant.ui.card_list import CardListView  # noqa: E402


@pytest.fixture
def view(qapp):
    v = CardListView()
    yield v
    v.deleteLater()


@pytest.fixture
def editors(qapp):
    from PySide6.QtWidgets import QTextEdit
    src, tr = QTextEdit(), QTextEdit()
    yield src, tr
    src.deleteLater()
    tr.deleteLater()


class TestCardListView:
    def test_placeholder_before_load(self, view):
        assert view.card_count() == 0
        assert not view._placeholder.isHidden()

    def test_load_builds_cards_for_content_lines_only(self, view):
        view.load(["%A", "", "%", "%B"], ["", "", "", "x"], [])
        assert view.card_count() == 2
        assert view.card(0) is not None
        assert view.card(1) is None      # blank line
        assert view.card(2) is None      # marker-only line
        assert view.card(3) is not None

    def test_load_hides_placeholder(self, view):
        view.load(["%A"], [""], [])
        assert view._placeholder.isHidden()

    def test_reload_replaces_cards(self, view):
        view.load(["%A", "%B"], ["", ""], [])
        view.load(["%C"], [""], [])
        assert view.card_count() == 1
        assert "C" in view.card(0).source_label.text()

    def test_glossary_applied_to_source(self, view):
        view.load(["%ホロウ駅"], [""], [("ホロウ", "Hollow")])
        assert "Hollow" in view.card(0).source_label.text()

    def test_initial_states(self, view):
        view.load(["%A", "%B"], ["done", ""], [])
        assert view.card(0).state() == "done"
        assert view.card(1).state() == "todo"

    def test_set_active_attaches_editors(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A", "%B"], ["", ""], [])
        view.set_active(0)
        assert view.active_index == 0
        assert view.card(0).state() == "active"
        assert src.parent() is not None

    def test_set_active_moves_between_cards(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A", "%B"], ["", ""], [])
        view.set_active(0)
        view.set_active(1)
        assert view.card(0).state() == "todo"
        assert view.card(1).state() == "active"

    def test_set_active_missing_index_is_noop(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A", "", "%B"], ["", "", ""], [])
        view.set_active(0)
        view.set_active(1)   # blank line — no card
        assert view.active_index == 0

    def test_update_card_refreshes_label_and_state(self, view):
        view.load(["%A"], [""], [])
        view.update_card(0, "Done now")
        assert view.card(0).translation_text() == "Done now"
        assert view.card(0).state() == "done"

    def test_update_card_keeps_active_state(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A"], [""], [])
        view.set_active(0)
        view.update_card(0, "text")
        assert view.card(0).state() == "active"

    def test_card_click_forwards_signal(self, view):
        view.load(["%A", "%B"], ["", ""], [])
        got = []
        view.card_clicked.connect(got.append)
        view.card(1).clicked.emit(1)
        assert got == [1]

    def test_show_copied_pill(self, view, qapp):
        view.load(["%A"], [""], [])
        view.show()
        view.show_copied_pill(0)
        assert not view.card(0)._copied_pill.isHidden()

    def test_set_font_size_propagates(self, view):
        view.load(["%A", "%B"], ["", ""], [])
        view.set_font_size(20.0)
        assert abs(view.card(0).source_label.font().pointSizeF() - 20.0) < 0.1

    def test_load_empty_shows_placeholder(self, view):
        view.load(["%A"], [""], [])
        view.load([], [], [])
        assert view.card_count() == 0
        assert not view._placeholder.isHidden()

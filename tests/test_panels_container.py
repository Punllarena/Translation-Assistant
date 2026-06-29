import pytest

@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    return app

@pytest.fixture
def container(qapp):
    from ta.ui.panels_container import PanelsContainer
    return PanelsContainer()

class FakeTranslator:
    name = "FakeEngine"
    translation_ready = None
    translation_error = None
    translation_started = None
    translation_chunk = None

    def can_translate(self, src, dst):
        return True

    def translate(self, text, src, dst):
        pass


def make_panel(name="FakeEngine"):
    from unittest.mock import MagicMock
    from PySide6.QtCore import Signal, QObject

    class FakeSig(QObject):
        sig = Signal(str)

    s = FakeSig()
    translator = MagicMock()
    translator.name = name
    translator.translation_ready = s.sig
    translator.translation_error = s.sig
    translator.translation_started = s.sig
    translator.translation_chunk = s.sig
    from ta.ui.translation_panel import TranslationPanel
    return TranslationPanel(translator)


def test_uses_tab_widget(container):
    from PySide6.QtWidgets import QTabWidget
    assert isinstance(container._tab_widget, QTabWidget)


def test_add_panel_creates_tab(container):
    panel = make_panel("DeepL")
    container.add_panel(panel)
    assert container._tab_widget.count() == 1
    assert container._tab_widget.tabText(0) == "DeepL"


def test_add_two_panels(container):
    container.add_panel(make_panel("DeepL"))
    container.add_panel(make_panel("Google"))
    assert container._tab_widget.count() == 2


def test_remove_panel(container):
    container.add_panel(make_panel("DeepL"))
    container.add_panel(make_panel("Google"))
    container.remove_panel("DeepL")
    assert container._tab_widget.count() == 1
    assert container._tab_widget.tabText(0) == "Google"


def test_save_restore_layout(container):
    container.add_panel(make_panel("DeepL"))
    container.add_panel(make_panel("Google"))
    container._tab_widget.setCurrentIndex(1)
    layout = container.save_layout()
    container._tab_widget.setCurrentIndex(0)
    container.restore_layout(layout)
    assert container._tab_widget.currentIndex() == 1


def test_restore_layout_with_old_splitter_data(container):
    """Backward compat: old layout.json with splitter keys is silently ignored."""
    container.add_panel(make_panel("DeepL"))
    old_data = {"horizontal": [300, 300], "col0": [200], "col1": []}
    container.restore_layout(old_data)  # must not raise
    assert container._tab_widget.currentIndex() == 0

"""UI package. Shared helpers for dialogs."""


def remember_dialog_geometry(dlg, settings, key: str) -> None:
    """Restore a dialog's saved size/position and save it back when it closes."""
    geo = settings.get_geometry(key)
    if not geo.isEmpty():
        dlg.restoreGeometry(geo)
    dlg.finished.connect(lambda _result: settings.set_geometry(key, dlg.saveGeometry()))

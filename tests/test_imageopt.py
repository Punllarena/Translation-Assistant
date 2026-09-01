import os

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

from translation_assistant.imageopt import shrink_image


def _big_png(w: int, h: int) -> bytes:
    """A hard-to-compress PNG (random pixels) well over any sane target."""
    raw = os.urandom(w * h * 3)
    img = QImage(raw, w, h, w * 3, QImage.Format_RGB888).copy()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_shrink_caps_size_and_dimension(qapp):
    data = _big_png(1500, 1500)
    assert len(data) > 300_000
    out = shrink_image(data, max_dim=600, target_bytes=120_000)
    assert 0 < len(out) <= 120_000
    dec = QImage.fromData(out)
    assert not dec.isNull()
    assert max(dec.width(), dec.height()) <= 600


def test_shrink_returns_same_object_when_already_small(qapp):
    small = b"tiny, not even an image"
    assert shrink_image(small) is small


def test_shrink_returns_original_on_undecodable_large_blob(qapp):
    blob = os.urandom(500_000)
    assert shrink_image(blob) is blob

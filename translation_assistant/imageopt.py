"""Shrink oversized images before they go into a WordPress publish payload.

EasyWP's proxy resets any request whose body exceeds ~1 MB, and EPUB covers /
colour plates are 500-750 KB JPEGs that base64-inflate past that on their own.
Downscaling + re-encoding as JPEG keeps the whole JSON body well under the cap.

Qt-only (PySide6 is already a dependency); kept out of ``wp_publisher.py`` so
that module stays Qt-free.
"""
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

_QUALITY_STEPS = (82, 70, 60, 50, 40)


def shrink_image(
    data: bytes, max_dim: int = 1600, target_bytes: int = 350_000
) -> bytes:
    """A smaller JPEG rendering of ``data``.

    Returns ``data`` unchanged (same object) when it is already under
    ``target_bytes``, cannot be decoded, or no re-encoding beats the original.
    """
    if len(data) <= target_bytes:
        return data
    img = QImage.fromData(data)
    if img.isNull():
        return data
    if max(img.width(), img.height()) > max_dim:
        img = img.scaled(
            max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    out = b""
    for quality in _QUALITY_STEPS:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPG", quality)
        out = bytes(buf.data())
        if out and len(out) <= target_bytes:
            return out
    return out if out and len(out) < len(data) else data

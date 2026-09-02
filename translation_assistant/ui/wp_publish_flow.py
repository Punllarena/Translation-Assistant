"""
Shared WordPress publish machinery, caller-agnostic.

Everything keys off a Database, an AppSettings, and a doc_id — never a widget's
`self`. Used by TranslationAssistantWidget (single, currently-open doc) and
OpenDocumentDialog (single selected row + batch).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

import translation_assistant.wp_publisher as _wp
from translation_assistant.wp_publisher import WPPublishError
from translation_assistant.ui import remember_dialog_geometry
from translation_assistant.ui.dlg_series import SeriesManagerDialog
from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog


class PublishWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(self, endpoint_url: str, payload: dict, parent=None) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._payload = payload

    def run(self) -> None:
        try:
            self.succeeded.emit(_wp.publish(self._endpoint_url, self._payload))
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.error.emit(str(exc))


class StatusCheckWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(
        self, endpoint_url: str, api_key: str, series_slug: str, chapter: int, parent=None
    ) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._series_slug = series_slug
        self._chapter = chapter

    def run(self) -> None:
        try:
            self.succeeded.emit(
                _wp.check_status(
                    self._endpoint_url, self._api_key, self._series_slug, self._chapter
                )
            )
        except WPPublishError as exc:
            self.error.emit(exc.message)
        except Exception as exc:  # noqa: BLE001 — worker boundary
            self.error.emit(str(exc))


class PublishJobError(Exception):
    """Raised by build_job when a chapter cannot be published (e.g. no translation)."""


@dataclass(frozen=True)
class PublishJob:
    doc_id: int
    doc_meta: dict
    series_meta: dict
    lines: list[dict]
    inline_images: list[dict]
    cover_image: dict | None
    password: str | None
    unlock_chapter_index: int | None
    prev_wp_chapter_index: int | None
    series_order: int
    chapter_title: str


def build_job(db, settings, doc_id: int) -> PublishJob:
    doc_meta = db.get_document(doc_id)
    series_title = doc_meta["series_title"]
    series_meta = db.get_series_wp_meta(series_title)

    pw_settings = db.get_series_wp_password_settings(series_title)
    pw_enabled = _wp.resolve_wp_password_enabled(pw_settings, settings.wp_password_enabled)
    unlock_after = (
        pw_settings["wp_unlock_after"]
        if pw_settings["wp_unlock_after"] != -1
        else settings.wp_unlock_after
    )
    password = unlock_chapter_index = None
    if pw_enabled:
        password, unlock_chapter_index = _wp.compute_password_fields(
            doc_meta["series_order"], unlock_after
        )

    lines = db.get_lines(doc_id)
    if not any(ln["translated_text"].strip() for ln in lines):
        raise PublishJobError("No translated lines to publish.")

    doc_images = db.get_document_images(doc_id)
    inline_images = [im for im in doc_images if not im["is_cover"] and not im["exclude_export"]]
    cover_image = next((im for im in doc_images if im["is_cover"]), None)

    # EasyWP's proxy resets requests over ~1 MB; full-res EPUB art blows that
    # on its own. Downscale before it goes into the base64 payload.
    from translation_assistant.imageopt import shrink_image
    for im in [*inline_images, *([cover_image] if cover_image else [])]:
        shrunk = shrink_image(im["data"])
        if shrunk is not im["data"]:
            im["data"] = shrunk
            im["src_path"] = im["src_path"].rsplit(".", 1)[0] + ".jpg"

    prev_wp_chapter_index = db.get_document_wp_status(doc_id).get("wp_chapter_index")

    return PublishJob(
        doc_id=doc_id,
        doc_meta=doc_meta,
        series_meta=series_meta,
        lines=lines,
        inline_images=inline_images,
        cover_image=cover_image,
        password=password,
        unlock_chapter_index=unlock_chapter_index,
        prev_wp_chapter_index=prev_wp_chapter_index,
        series_order=doc_meta["series_order"],
        chapter_title=doc_meta["chapter_title"],
    )


def job_to_payload(job: PublishJob, api_key: str, *, scheduled_date, attribution: bool) -> dict:
    return _wp.build_payload(
        job.doc_meta,
        job.series_meta,
        job.lines,
        api_key=api_key,
        password=job.password,
        unlock_chapter_index=job.unlock_chapter_index,
        scheduled_date=scheduled_date,
        attribution=attribution,
        images=job.inline_images,
        cover=job.cover_image,
        previous_chapter_index=job.prev_wp_chapter_index,
    )


def persist_publish_result(
    db, doc_id: int, result: dict, *, scheduled_date, chapter_index
) -> bool:
    """Write wp_status back after a publish. Returns True if a write happened."""
    if not (result.get("created") or result.get("updated")):
        return False
    status = "future" if scheduled_date else "publish"
    date = scheduled_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.set_document_wp_status(
        doc_id, status, result.get("post_url") or None, date, chapter_index
    )
    return True


def ensure_wp_config(settings, parent):
    """Ensure WordPress endpoint_url and api_key are configured.

    Returns (endpoint_url, api_key) if both are set, else None after showing settings dialog.
    """
    endpoint_url = settings.wp_endpoint_url
    api_key = settings.wp_api_key
    if endpoint_url and api_key:
        return endpoint_url, api_key
    dlg = WPSettingsDialog(settings, parent=parent)
    if not dlg.exec():
        return None
    endpoint_url = settings.wp_endpoint_url
    api_key = settings.wp_api_key
    if not endpoint_url or not api_key:
        return None
    return endpoint_url, api_key


def ensure_series_wp_meta(db, settings, series_title: str, parent):
    """Ensure series has series_slug and series_title_short set.

    Returns the series_wp_meta dict if both fields are set, else None after showing dialog.
    """
    meta = db.get_series_wp_meta(series_title)
    if meta["series_slug"] and meta["series_title_short"]:
        return meta
    dlg = SeriesManagerDialog(db, settings=settings, parent=parent)
    remember_dialog_geometry(dlg, settings, "dlg_series")
    dlg.exec()
    meta = db.get_series_wp_meta(series_title)
    if not meta["series_slug"] or not meta["series_title_short"]:
        return None
    return meta

"""
Shared WordPress publish machinery, caller-agnostic.

Everything keys off a Database, an AppSettings, and a doc_id — never a widget's
`self`. Used by TranslationAssistantWidget (single, currently-open doc) and
OpenDocumentDialog (single selected row + batch).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QDateTime, Qt, QThread, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QMessageBox, QVBoxLayout,
)

import translation_assistant.wp_publisher as _wp
from translation_assistant.wp_publisher import WPPublishError, compute_auto_schedule
from translation_assistant.ui import remember_dialog_geometry
from translation_assistant.ui.dlg_series import SeriesManagerDialog
from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog

# Keepalive for PublishWorkers spawned with parent=None — without a Qt parent
# and without a surviving Python ref they can be GC'd mid-flight.
_ORPHAN_WORKERS: set = set()


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
    QMessageBox.information(
        parent, "WP Fields Missing",
        f'Set "Series Slug" and "Short Title" for "{series_title}" in Series Manager.',
    )
    dlg = SeriesManagerDialog(db, settings=settings, parent=parent)
    remember_dialog_geometry(dlg, settings, "dlg_series")
    dlg.exec()
    meta = db.get_series_wp_meta(series_title)
    if not meta["series_slug"] or not meta["series_title_short"]:
        return None
    return meta


class PublishConfirmDialog(QDialog):
    def __init__(self, job, db, settings, endpoint_url, api_key, parent=None):
        super().__init__(parent)
        self._job = job
        self._db = db
        self._settings = settings
        self._status_worker = None
        self.setWindowTitle("Publish to WordPress")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        doc_meta, series_meta = job.doc_meta, job.series_meta
        layout = QVBoxLayout(self)

        prev_status = None
        prev_scheduled = False
        if job.series_order > 0:
            prev_status = db.get_wp_status_by_series_position(
                doc_meta["series_title"], job.series_order - 1
            )
            prev_scheduled = prev_status is not None and prev_status.get("wp_status") == "future"

        cached = db.get_document_wp_status(job.doc_id)
        status_text_map = {"publish": "Published", "future": "Scheduled", "draft": "Draft"}
        cached_text = status_text_map.get(cached["wp_status"] or "", "Not published")
        self._status_lbl = QLabel(f"WP status: {cached_text}")
        layout.addWidget(self._status_lbl)

        chapter_label = "Synopsis" if job.series_order == 0 else f"Chapter {job.series_order}"
        prompt = f'Publish <b>{doc_meta["chapter_title"]}</b> ({chapter_label}) to WordPress?'
        if cached["wp_status"] == "publish":
            prompt += " — republishing will overwrite the live chapter."
        layout.addWidget(QLabel(prompt))

        if prev_scheduled:
            warn = QLabel(
                f"Warning: Chapter {job.series_order - 1} is still scheduled "
                "and hasn't gone live yet."
            )
            warn.setWordWrap(True)
            layout.addWidget(warn)

        self._schedule_cb = QCheckBox("Schedule for later")
        layout.addWidget(self._schedule_cb)

        default_time = settings.wp_default_schedule_time
        h = m = None
        if default_time:
            try:
                h, m = map(int, default_time.split(":"))
            except (ValueError, IndexError):
                default_time = ""
        if default_time:
            candidate = QDateTime.currentDateTime()
            candidate.setTime(QTime(h, m))
            if candidate <= QDateTime.currentDateTime():
                candidate = candidate.addDays(1)
            self._dte = QDateTimeEdit(candidate)
        else:
            self._dte = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self._dte.setCalendarPopup(True)
        self._dte.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._dte.setEnabled(False)
        self._schedule_cb.toggled.connect(self._dte.setEnabled)
        layout.addWidget(self._dte)

        if prev_scheduled:
            self._schedule_cb.setChecked(True)
            prev_date = prev_status.get("wp_date") if prev_status else None
            if prev_date:
                scope_series = (
                    None if settings.wp_schedule_scope_global else doc_meta["series_title"]
                )
                try:
                    auto = compute_auto_schedule(
                        prev_date,
                        db.get_wp_dates(scope_series),
                        settings.wp_chapters_per_day,
                        settings.wp_default_schedule_time,
                    )
                    self._dte.setDateTime(QDateTime(auto))
                except ValueError:
                    pass

        if prev_scheduled:
            btns = QDialogButtonBox()
            btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
            btns.addButton("Publish Anyway", QDialogButtonBox.ButtonRole.AcceptRole)
        else:
            btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._status_worker = StatusCheckWorker(
            endpoint_url, api_key, series_meta["series_slug"], job.series_order, parent=self
        )
        self._cached = cached
        self._cached_text = cached_text
        self._status_worker.succeeded.connect(self._on_status_ok)
        self._status_worker.error.connect(self._on_status_err)
        self._status_worker.start()

    def _on_status_ok(self, result: dict) -> None:
        m = {"publish": "Published", "future": "Scheduled", "draft": "Draft",
             "not_found": "Not published"}
        self._status_lbl.setText(f"WP status: {m.get(result.get('status', ''), 'Unknown')}")
        self._db.set_document_wp_status(
            self._job.doc_id, result.get("status") or None, result.get("post_url"),
            result.get("date"), self._cached.get("wp_chapter_index"),
        )

    def _on_status_err(self, msg: str) -> None:
        self._status_lbl.setText(f"WP status: {self._cached_text} (cached — {msg})")

    def scheduled_date_utc(self):
        if not self._schedule_cb.isChecked():
            return None
        local = self._dte.dateTime().toPython()
        return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def done(self, r: int) -> None:
        if self._status_worker is not None:
            self._status_worker.quit()
            self._status_worker.wait(500)
        super().done(r)


def show_publish_result(result, job, scheduled_date, parent):
    created = result.get("created", False)
    updated = result.get("updated", False)
    page_url = result.get("page_url", "")
    post_url = result.get("post_url", "")

    dlg = QDialog(parent)
    dlg.setWindowTitle("WordPress Publish")
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
    dlg.setMinimumWidth(420)
    layout = QVBoxLayout(dlg)

    if created:
        status_text = "Scheduled!" if scheduled_date else "Published!"
    elif updated:
        status_text = "Scheduled!" if scheduled_date else "Updated!"
    else:
        status_text = "Already published."
    layout.addWidget(QLabel(status_text))

    form = QFormLayout()
    if page_url:
        lbl = QLabel(f'<a href="{page_url}">{page_url}</a>')
        lbl.setOpenExternalLinks(True)
        form.addRow("Page:", lbl)
    if post_url and (created or updated):
        lbl = QLabel(f'<a href="{post_url}">{post_url}</a>')
        lbl.setOpenExternalLinks(True)
        form.addRow("Post:", lbl)
    layout.addLayout(form)

    if (created or updated) and job.password:
        pw_edit = QLineEdit(job.password)
        pw_edit.setReadOnly(True)
        pw_edit.selectAll()
        layout.addWidget(QLabel("Password (copy this):"))
        layout.addWidget(pw_edit)

    if (created or updated) and job.unlock_chapter_index is not None:
        layout.addWidget(QLabel(f"Chapter {job.unlock_chapter_index} is now unlocked."))

    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    btns.accepted.connect(dlg.accept)
    layout.addWidget(btns)
    dlg.exec()


def run_single_publish(db, settings, doc_id, parent, *, on_status_changed=None):
    cfg = ensure_wp_config(settings, parent)
    if cfg is None:
        return
    endpoint_url, api_key = cfg

    series_title = db.get_document(doc_id)["series_title"]
    if ensure_series_wp_meta(db, settings, series_title, parent) is None:
        return

    try:
        job = build_job(db, settings, doc_id)
    except PublishJobError as exc:
        QMessageBox.warning(parent, "Nothing to Publish", str(exc))
        return

    dlg = PublishConfirmDialog(job, db, settings, endpoint_url, api_key, parent=parent)
    if not dlg.exec():
        return
    scheduled_date = dlg.scheduled_date_utc()

    try:
        payload = job_to_payload(
            job, api_key, scheduled_date=scheduled_date,
            attribution=settings.wp_attribution_enabled,
        )
    except ValueError as exc:
        QMessageBox.warning(parent, "Payload Error", str(exc))
        return

    worker = PublishWorker(endpoint_url, payload, parent=parent)
    if parent is not None:
        keep = getattr(parent, "_wp_flow_keepalive", None)
        if keep is None:
            keep = []
            parent._wp_flow_keepalive = keep
    else:
        keep = _ORPHAN_WORKERS  # no widget parent — hold a ref so it survives

    def _release():
        try:
            keep.remove(worker)
        except (ValueError, KeyError):
            pass

    def _done(result):
        if persist_publish_result(
            db, doc_id, result, scheduled_date=scheduled_date,
            chapter_index=job.series_order,
        ) and on_status_changed:
            on_status_changed()
        show_publish_result(result, job, scheduled_date, parent)
        _release()

    def _err(msg):
        QMessageBox.warning(parent, "Publish Failed", msg)
        _release()

    worker.succeeded.connect(_done)
    worker.error.connect(_err)
    if isinstance(keep, set):
        keep.add(worker)
    else:
        keep.append(worker)
    worker.start()

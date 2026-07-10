"""
WordPress Settings dialog — endpoint URL and API key.
"""
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout,
)

from translation_assistant.settings import AppSettings


class WPSettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("WordPress Settings")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)

        self._url_edit = QLineEdit(self._settings.wp_endpoint_url)
        self._url_edit.setPlaceholderText("https://yoursite.com/wp-json/ta-publisher/v1/publish")
        form.addRow("Endpoint URL:", self._url_edit)

        self._key_edit = QLineEdit(self._settings.wp_api_key)
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("API key from WP Admin → Settings → TA Publisher")
        form.addRow("API Key:", self._key_edit)

        self._pw_check = QCheckBox("Enable password protection by default")
        self._pw_check.setChecked(self._settings.wp_password_enabled)
        form.addRow("", self._pw_check)

        self._unlock_spin = QSpinBox()
        self._unlock_spin.setRange(1, 99)
        self._unlock_spin.setValue(self._settings.wp_unlock_after)
        self._unlock_spin.setEnabled(self._settings.wp_password_enabled)
        self._pw_check.toggled.connect(self._unlock_spin.setEnabled)
        form.addRow("Keep N chapters locked:", self._unlock_spin)

        self._attribution_check = QCheckBox("Add attribution footer to published chapters")
        self._attribution_check.setChecked(self._settings.wp_attribution_enabled)
        form.addRow("", self._attribution_check)

        sched_time = self._settings.wp_default_schedule_time
        self._schedule_cb = QCheckBox("Set default schedule time")
        self._schedule_cb.setChecked(bool(sched_time))
        form.addRow("", self._schedule_cb)

        self._schedule_time_edit = QTimeEdit()
        self._schedule_time_edit.setDisplayFormat("HH:mm")
        if sched_time:
            try:
                h, m = map(int, sched_time.split(":"))
                self._schedule_time_edit.setTime(QTime(h, m))
            except (ValueError, IndexError):
                self._schedule_time_edit.setTime(QTime(20, 0))
        else:
            self._schedule_time_edit.setTime(QTime(20, 0))
        self._schedule_time_edit.setEnabled(bool(sched_time))
        self._schedule_cb.toggled.connect(self._schedule_time_edit.setEnabled)
        form.addRow("Time:", self._schedule_time_edit)

        layout.addLayout(form)

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._on_test)
        layout.addWidget(self._test_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        self._settings.wp_endpoint_url = self._url_edit.text().strip()
        self._settings.wp_api_key = self._key_edit.text().strip()
        self._settings.wp_password_enabled = self._pw_check.isChecked()
        self._settings.wp_unlock_after = self._unlock_spin.value()
        self._settings.wp_attribution_enabled = self._attribution_check.isChecked()
        if self._schedule_cb.isChecked():
            self._settings.wp_default_schedule_time = self._schedule_time_edit.time().toString("HH:mm")
        else:
            self._settings.wp_default_schedule_time = ""
        self.accept()

    def _on_test(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter an endpoint URL first.")
            return
        import json
        import urllib.request
        from urllib.error import URLError, HTTPError
        from translation_assistant.wp_publisher import normalize_endpoint_url
        url = normalize_endpoint_url(url)
        try:
            data = json.dumps({}).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            QMessageBox.information(self, "Connection OK", "Endpoint reached.")
        except HTTPError as exc:
            if exc.code == 400:
                QMessageBox.information(
                    self, "Connection OK",
                    "Endpoint reached (400 = missing fields, as expected).",
                )
            elif exc.code == 401:
                QMessageBox.warning(self, "Auth Error", "Endpoint reachable but API key rejected (401).")
            else:
                QMessageBox.warning(self, "HTTP Error", f"HTTP {exc.code}: {exc.reason}")
        except URLError as exc:
            QMessageBox.critical(self, "Connection Failed", f"Could not reach endpoint:\n{exc.reason}")

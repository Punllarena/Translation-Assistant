from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QWidget,
    QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem,
    QPushButton, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt

from ta.core.substitutions import SubstitutionStore


class SubstitutionsDialog(QDialog):
    def __init__(self, store: SubstitutionStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._staged: dict[str, list[tuple[str, str]]] = {}
        self._deleted_profiles: set[str] = set()
        self.setWindowTitle("Substitutions")
        self.setMinimumSize(620, 420)
        self._setup_ui()
        self._load_profiles()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        main = QVBoxLayout(self)

        # Top: profiles (left) + rules (right)
        content = QHBoxLayout()

        # Left: profile list
        left = QVBoxLayout()
        self._profile_list = QListWidget()
        self._profile_list.currentTextChanged.connect(self._on_profile_changed)
        left.addWidget(self._profile_list)

        profile_btns = QHBoxLayout()
        add_profile_btn = QPushButton("+ Profile")
        add_profile_btn.clicked.connect(self._on_add_profile)
        rm_profile_btn = QPushButton("- Profile")
        rm_profile_btn.clicked.connect(self._on_remove_profile)
        profile_btns.addWidget(add_profile_btn)
        profile_btns.addWidget(rm_profile_btn)
        left.addLayout(profile_btns)
        content.addLayout(left, stretch=1)

        # Right: rules table
        right = QVBoxLayout()
        self._rules_table = QTableWidget(0, 2)
        self._rules_table.setHorizontalHeaderLabels(["Original", "Replacement"])
        self._rules_table.horizontalHeader().setStretchLastSection(True)
        right.addWidget(self._rules_table)

        rule_btns = QHBoxLayout()
        add_rule_btn = QPushButton("+ Rule")
        add_rule_btn.clicked.connect(self._on_add_rule)
        rm_rule_btn = QPushButton("- Rule")
        rm_rule_btn.clicked.connect(self._on_remove_rule)
        rule_btns.addWidget(add_rule_btn)
        rule_btns.addWidget(rm_rule_btn)
        right.addLayout(rule_btns)
        content.addLayout(right, stretch=3)

        main.addLayout(content)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_ok)
        self._buttons.rejected.connect(self.reject)
        main.addWidget(self._buttons)

    def _load_profiles(self) -> None:
        self._profile_list.clear()
        for name in self._store.profiles():
            self._profile_list.addItem(name)
            profile = self._store.get_profile(name)
            if profile:
                self._staged[name] = [(r.old, r.new) for r in profile.rules]
        # Select "*" by default
        items = self._profile_list.findItems("*", Qt.MatchFlag.MatchExactly)
        if items:
            self._profile_list.setCurrentItem(items[0])

    def _on_profile_changed(self, name: str) -> None:
        self._rules_table.setRowCount(0)
        if not name:
            return
        for old, new in self._staged.get(name, []):
            self._append_table_row(old, new)

    def _append_table_row(self, old: str, new: str) -> None:
        row = self._rules_table.rowCount()
        self._rules_table.insertRow(row)
        self._rules_table.setItem(row, 0, QTableWidgetItem(old))
        self._rules_table.setItem(row, 1, QTableWidgetItem(new))

    def _on_add_rule(self) -> None:
        profile = self.current_profile()
        if not profile:
            return
        old, ok1 = QInputDialog.getText(self, "Add Rule", "Original text:")
        if not ok1 or not old:
            return
        new, ok2 = QInputDialog.getText(self, "Add Rule", "Replacement:")
        if not ok2:
            return
        self._staged.setdefault(profile, []).append((old, new))
        self._append_table_row(old, new)

    def _on_remove_rule(self) -> None:
        profile = self.current_profile()
        if not profile:
            return
        row = self._rules_table.currentRow()
        if row < 0:
            return
        old = self._rules_table.item(row, 0).text()
        self._rules_table.removeRow(row)
        self._staged[profile] = [
            (o, n) for o, n in self._staged.get(profile, []) if o != old
        ]

    def _on_add_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name and name not in self._staged:
            self._staged[name] = []
            self._deleted_profiles.discard(name)
            self._profile_list.addItem(name)

    def _on_remove_profile(self) -> None:
        profile = self.current_profile()
        if not profile or profile == "*":
            return
        self._deleted_profiles.add(profile)
        del self._staged[profile]
        items = self._profile_list.findItems(profile, Qt.MatchFlag.MatchExactly)
        for item in items:
            self._profile_list.takeItem(self._profile_list.row(item))

    def _on_ok(self) -> None:
        # Apply staged changes to store
        for name in self._deleted_profiles:
            self._store.remove_profile(name)

        for name, rules in self._staged.items():
            self._store.add_profile(name)
            profile = self._store.get_profile(name)
            if profile:
                profile.rules.clear()
            for old, new in rules:
                self._store.add_rule(name, old, new)

        self.accept()

    # ------------------------------------------------------------------
    # Test-facing accessors
    # ------------------------------------------------------------------

    def profile_list(self) -> list[str]:
        return [self._profile_list.item(i).text()
                for i in range(self._profile_list.count())]

    def current_profile(self) -> str:
        item = self._profile_list.currentItem()
        return item.text() if item else ""

    def select_profile(self, name: str) -> None:
        items = self._profile_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self._profile_list.setCurrentItem(items[0])

    def current_rules(self) -> list[tuple[str, str]]:
        rules = []
        for row in range(self._rules_table.rowCount()):
            old = self._rules_table.item(row, 0).text()
            new = self._rules_table.item(row, 1).text()
            rules.append((old, new))
        return rules

    def add_rule(self, old: str, new: str) -> None:
        profile = self.current_profile()
        if not profile:
            return
        self._staged.setdefault(profile, []).append((old, new))
        self._append_table_row(old, new)

    def remove_rule(self, old: str) -> None:
        profile = self.current_profile()
        if not profile:
            return
        for row in range(self._rules_table.rowCount()):
            item = self._rules_table.item(row, 0)
            if item and item.text() == old:
                self._rules_table.removeRow(row)
                self._staged[profile] = [
                    (o, n) for o, n in self._staged.get(profile, []) if o != old
                ]
                return

    def add_profile(self, name: str) -> None:
        if name not in self._staged:
            self._staged[name] = []
            self._profile_list.addItem(name)

    def remove_profile(self, name: str) -> None:
        if name == "*":
            return
        self._on_remove_profile() if self.current_profile() == name else None
        if name in self._staged:
            self._deleted_profiles.add(name)
            del self._staged[name]
            items = self._profile_list.findItems(name, Qt.MatchFlag.MatchExactly)
            for item in items:
                self._profile_list.takeItem(self._profile_list.row(item))

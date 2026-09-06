from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QMessageBox, QPushButton, QVBoxLayout,
)

from .i18n import translate


class ImportDestinationDialog(QDialog):
    def __init__(self, database, language: str, project_id=None, group_id=None, case_id=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.language = language
        self.initial_project_id = project_id
        self.initial_group_id = group_id
        self.initial_case_id = case_id
        self.setWindowTitle(self._t("import_destination"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.project_combo = QComboBox(); self.group_combo = QComboBox(); self.case_combo = QComboBox()
        form.addRow(self._t("project"), self.project_combo)
        group_row = QHBoxLayout(); group_row.addWidget(self.group_combo, 1)
        self.new_group_button = QPushButton(self._t("new_group")); group_row.addWidget(self.new_group_button)
        form.addRow(self._t("group"), group_row)
        case_row = QHBoxLayout(); case_row.addWidget(self.case_combo, 1)
        self.new_case_button = QPushButton(self._t("new_case")); case_row.addWidget(self.new_case_button)
        form.addRow(self._t("case"), case_row)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.project_combo.currentIndexChanged.connect(self._populate_groups)
        self.group_combo.currentIndexChanged.connect(self._populate_cases)
        self.new_group_button.clicked.connect(self._new_group)
        self.new_case_button.clicked.connect(self._new_case)
        self._populate_projects()

    def _t(self, key, **values):
        return translate(self.language, key, **values)

    def _populate_projects(self):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for row in self.database.projects():
            self.project_combo.addItem(row["name"], row["id"])
        target = self.initial_project_id
        if self.initial_case_id:
            match = next((r for r in self.database.cases() if r["id"] == self.initial_case_id), None)
            if match: target = match["project_id"]
        elif self.initial_group_id:
            match = next((r for r in self.database.groups() if r["id"] == self.initial_group_id), None)
            if match: target = match["project_id"]
        index = self.project_combo.findData(target)
        self.project_combo.setCurrentIndex(index if index >= 0 else 0)
        self.project_combo.blockSignals(False)
        self._populate_groups()

    def _populate_groups(self):
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        project_id = self.project_combo.currentData()
        for row in self.database.groups(project_id):
            self.group_combo.addItem(row["name"], row["id"])
        target = self.initial_group_id
        if self.initial_case_id:
            match = next((r for r in self.database.cases() if r["id"] == self.initial_case_id), None)
            if match: target = match["group_id"]
        index = self.group_combo.findData(target)
        self.group_combo.setCurrentIndex(index if index >= 0 else 0)
        self.group_combo.blockSignals(False)
        self.new_group_button.setEnabled(project_id is not None)
        self._populate_cases()

    def _populate_cases(self):
        self.case_combo.clear()
        group_id = self.group_combo.currentData()
        rows = [row for row in self.database.cases() if row["group_id"] == group_id]
        for row in rows:
            self.case_combo.addItem(row["name"], row["id"])
        index = self.case_combo.findData(self.initial_case_id)
        self.case_combo.setCurrentIndex(index if index >= 0 else 0)
        self.new_case_button.setEnabled(group_id is not None)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.case_combo.currentData() is not None)

    def _new_group(self):
        project_id = self.project_combo.currentData()
        name, ok = QInputDialog.getText(self, self._t("new_group_title"), self._t("group_name"))
        if not ok or not name.strip(): return
        try:
            group_id = self.database.create_group(project_id, name.strip())
            self.initial_group_id = group_id
            self.initial_case_id = None
            self._populate_groups()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, self._t("duplicate"), self._t("duplicate_group"))

    def _new_case(self):
        group_id = self.group_combo.currentData()
        name, ok = QInputDialog.getText(self, self._t("new_case_title"), self._t("case_name"))
        if not ok or not name.strip(): return
        try:
            case_id = self.database.create_case(group_id, name.strip())
            self.initial_case_id = case_id
            self._populate_cases()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, self._t("duplicate"), self._t("duplicate_case"))

    @property
    def case_id(self):
        return self.case_combo.currentData()


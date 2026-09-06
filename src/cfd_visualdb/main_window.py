from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
from PySide6.QtCore import QLocale, QMimeData, QSettings, Qt
from PySide6.QtGui import QAction, QColor, QDrag
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDockWidget, QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressDialog,
    QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .console import PythonConsole
from .destination_dialog import ImportDestinationDialog
from .importers import inspect_dataset
from .i18n import translate
from .roi_dialog import ROIStatisticsDialog
from .streamlines import StreamlineDialog, generate_streamlines, vector_fields
from .viewer import ViewPanel, sync_camera_relative


ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ID = Qt.ItemDataRole.UserRole + 1
DATASET_MIME = "application/x-cfd-visualdb-dataset-id"
LAYOUTS = {
    "1×1": (1, 1), "2×2": (2, 2), "3×3": (3, 3), "3×4": (3, 4),
    "4×4": (4, 4), "5×4": (5, 4), "5×5": (5, 5),
}


class DatasetTreeWidget(QTreeWidget):
    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None or item.data(0, ROLE_KIND) != "dataset":
            return
        mime = QMimeData()
        mime.setData(DATASET_MIME, str(item.data(0, ROLE_ID)).encode("ascii"))
        mime.setText(item.text(0))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class MainWindow(QMainWindow):
    def __init__(self, app_context):
        super().__init__()
        self.app = app_context
        self.settings = QSettings("CFDVisualDB", "CFDVisualDB")
        default_language = "zh" if QLocale.system().name().lower().startswith("zh") else "en"
        self.language = self.settings.value("language", default_language)
        self.background_color = self.settings.value("background_color", "#ffffff")
        self.resize(1500, 900)
        self._active_panel = None
        self._camera_syncing = False
        self._build_ui()
        self.apply_language(self.language)
        self.refresh_tree()
        self.set_layout("1×1")

    def _build_ui(self):
        toolbar = self.addToolBar("View controls")
        toolbar.setMovable(False)
        self.layout_label = QLabel()
        toolbar.addWidget(self.layout_label)
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(LAYOUTS)
        self.layout_combo.currentTextChanged.connect(self.set_layout)
        toolbar.addWidget(self.layout_combo)
        self.camera_link = QCheckBox()
        self.field_link = QCheckBox()
        self.colorbar_link = QCheckBox()
        self.colorbar_link.setChecked(True)
        self.colorbar_link.toggled.connect(self.apply_color_policy)
        toolbar.addSeparator()
        toolbar.addWidget(self.camera_link)
        toolbar.addWidget(self.field_link)
        toolbar.addWidget(self.colorbar_link)
        toolbar.addSeparator()
        self.color_range_label = QLabel()
        toolbar.addWidget(self.color_range_label)
        self.color_mode = QComboBox()
        for key in ("global", "independent", "manual"):
            self.color_mode.addItem(key, key)
        self.color_mode.currentIndexChanged.connect(self._color_mode_changed)
        toolbar.addWidget(self.color_mode)
        self.manual_min = QDoubleSpinBox()
        self.manual_max = QDoubleSpinBox()
        for box in (self.manual_min, self.manual_max):
            box.setRange(-1e15, 1e15)
            box.setDecimals(6)
            box.valueChanged.connect(self.apply_color_policy)
            toolbar.addWidget(box)
        self.manual_max.setValue(1.0)
        self.reset_action = QAction(self)
        self.reset_action.triggered.connect(self.app.viewer.reset_cameras)
        toolbar.addAction(self.reset_action)
        self.streamline_action = QAction(self)
        self.streamline_action.triggered.connect(self.start_streamlines)
        toolbar.addAction(self.streamline_action)
        self.clear_streamline_action = QAction(self)
        self.clear_streamline_action.triggered.connect(self.clear_streamlines)
        toolbar.addAction(self.clear_streamline_action)
        toolbar.addSeparator()
        self.background_label = QLabel()
        toolbar.addWidget(self.background_label)
        self.background_combo = QComboBox()
        for key, color in (("background_white", "#ffffff"), ("background_dark", "#17202a"),
                           ("background_gray", "#e5e7eb"), ("background_black", "#000000"),
                           ("background_custom", "custom")):
            self.background_combo.addItem(key, color)
        background_index = self.background_combo.findData(self.background_color)
        self.background_combo.setCurrentIndex(background_index if background_index >= 0 else 4)
        self.background_combo.currentIndexChanged.connect(self._background_selected)
        toolbar.addWidget(self.background_combo)
        toolbar.addSeparator()
        self.language_label = QLabel()
        toolbar.addWidget(self.language_label)
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.language)))
        self.language_combo.currentIndexChanged.connect(self._language_selected)
        toolbar.addWidget(self.language_combo)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        self.database_label = QLabel()
        left_layout.addWidget(self.database_label)
        buttons = QHBoxLayout()
        self.entity_buttons = {}
        for key, callback in (("new_project", self.new_project), ("new_group", self.new_group), ("new_case", self.new_case)):
            button = QPushButton()
            button.clicked.connect(callback)
            buttons.addWidget(button)
            self.entity_buttons[key] = button
        left_layout.addLayout(buttons)
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self.import_files)
        left_layout.addWidget(self.import_button)
        self.show_selected_button = QPushButton()
        self.show_selected_button.clicked.connect(self.show_selected_dataset)
        left_layout.addWidget(self.show_selected_button)
        self.delete_selected_button = QPushButton()
        self.delete_selected_button.clicked.connect(self.delete_selected)
        left_layout.addWidget(self.delete_selected_button)
        self.drag_hint_label = QLabel()
        self.drag_hint_label.setWordWrap(True)
        self.drag_hint_label.setStyleSheet("color: #667788; padding: 2px 4px;")
        left_layout.addWidget(self.drag_hint_label)
        self.tree = DatasetTreeWidget()
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.sectionDoubleClicked.connect(self.tree.resizeColumnToContents)
        header.sectionResized.connect(self._save_tree_header)
        self.tree.itemDoubleClicked.connect(self.open_tree_item)
        left_layout.addWidget(self.tree, 1)
        self.roi_group_label = QLabel()
        self.roi_group_label.setStyleSheet("font-weight: 700; margin-top: 4px;")
        left_layout.addWidget(self.roi_group_label)
        self.active_view_label = QLabel()
        self.active_view_label.setStyleSheet("color: #2563eb; font-weight: 600;")
        left_layout.addWidget(self.active_view_label)
        roi_mode_row = QHBoxLayout()
        self.roi_mode_label = QLabel()
        self.roi_mode_combo = QComboBox()
        for key in ("add", "remove", "replace"):
            self.roi_mode_combo.addItem(key, key)
        self.roi_mode_combo.currentIndexChanged.connect(self._roi_mode_changed)
        roi_mode_row.addWidget(self.roi_mode_label)
        roi_mode_row.addWidget(self.roi_mode_combo, 1)
        left_layout.addLayout(roi_mode_row)
        roi_controls = QGridLayout()
        self.roi_button = QPushButton(); self.roi_button.clicked.connect(self.start_roi_selection)
        self.roi_undo_button = QPushButton(); self.roi_undo_button.clicked.connect(self.undo_roi_selection)
        self.roi_clear_button = QPushButton(); self.roi_clear_button.clicked.connect(self.clear_roi_selection)
        self.roi_save_button = QPushButton(); self.roi_save_button.clicked.connect(self.save_roi_selection)
        self.roi_stats_button = QPushButton(); self.roi_stats_button.clicked.connect(self.show_roi_statistics)
        roi_controls.addWidget(self.roi_button, 0, 0)
        roi_controls.addWidget(self.roi_undo_button, 0, 1)
        roi_controls.addWidget(self.roi_clear_button, 1, 0)
        roi_controls.addWidget(self.roi_save_button, 1, 1)
        roi_controls.addWidget(self.roi_stats_button, 2, 0, 1, 2)
        left_layout.addLayout(roi_controls)

        self.view_container = QWidget()
        self.view_grid = QGridLayout(self.view_container)
        self.view_grid.setContentsMargins(2, 2, 2, 2)
        self.view_grid.setSpacing(3)
        self.left_panel = left
        self.left_panel.setMinimumWidth(220)
        self.main_splitter = QSplitter()
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(9)
        self.main_splitter.setStyleSheet(
            "QSplitter::handle { background: #aab4bf; margin: 1px 2px; border-radius: 2px; }"
            "QSplitter::handle:hover { background: #4387d9; }"
        )
        self.main_splitter.addWidget(left)
        self.main_splitter.addWidget(self.view_container)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        splitter_state = self.settings.value("main_splitter_state")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)
        else:
            self.main_splitter.setSizes([460, 1040])
        header_state = self.settings.value("tree_header_state")
        if header_state:
            self.tree.header().restoreState(header_state)
        else:
            self.tree.setColumnWidth(0, 330)
            self.tree.setColumnWidth(1, 100)
        self.main_splitter.splitterMoved.connect(self._save_splitter)
        self.setCentralWidget(self.main_splitter)

        self.console_dock = QDockWidget(self)
        self.python_console = PythonConsole({"app": self.app})
        self.console_dock.setWidget(self.python_console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)
        self.console_dock.hide()
        self.console_action = self.console_dock.toggleViewAction()
        self.view_menu = self.menuBar().addMenu("")
        self.view_menu.addAction(self.console_action)

    def _t(self, key, **values):
        return translate(self.language, key, **values)

    def _save_splitter(self, *_):
        self.settings.setValue("main_splitter_state", self.main_splitter.saveState())

    def _save_tree_header(self, *_):
        self.settings.setValue("tree_header_state", self.tree.header().saveState())

    def _language_selected(self):
        language = self.language_combo.currentData()
        if language:
            self.apply_language(language)

    def apply_language(self, language: str):
        self.language = language if language in {"zh", "en"} else "en"
        self.settings.setValue("language", self.language)
        self.setWindowTitle(self._t("window_title"))
        self.layout_label.setText(f" {self._t('layout')} ")
        self.camera_link.setText(self._t("camera_link"))
        self.field_link.setText(self._t("field_link"))
        self.colorbar_link.setText(self._t("colorbar_link"))
        self.color_range_label.setText(f" {self._t('color_range')} ")
        current_mode = self.color_mode.currentData()
        for index, key in enumerate(("global", "independent", "manual")):
            self.color_mode.setItemText(index, self._t(key))
        self.color_mode.setCurrentIndex(max(0, self.color_mode.findData(current_mode)))
        self.reset_action.setText(self._t("reset_cameras"))
        self.streamline_action.setText(self._t("streamlines"))
        self.clear_streamline_action.setText(self._t("clear_streamlines"))
        self.background_label.setText(f" {self._t('background')} ")
        for index, key in enumerate(("background_white", "background_dark", "background_gray",
                                     "background_black", "background_custom")):
            self.background_combo.setItemText(index, self._t(key))
        self.language_label.setText(f" {self._t('language')} ")
        self.database_label.setText(self._t("simulation_database"))
        self.database_label.setToolTip(self._t("resize_hint"))
        self.tree.setToolTip(self._t("resize_hint"))
        self.main_splitter.setToolTip(self._t("resize_hint"))
        for key, button in self.entity_buttons.items():
            button.setText(self._t(key))
        self.import_button.setText(self._t("import"))
        self.show_selected_button.setText(self._t("show_selected"))
        self.delete_selected_button.setText(self._t("delete_selected"))
        self.drag_hint_label.setText(self._t("drag_dataset_hint"))
        self.tree.setHeaderLabels([self._t("tree_header"), self._t("info")])
        self.roi_group_label.setText(self._t("roi_workflow"))
        self.roi_button.setText(self._t("roi_start"))
        self.roi_mode_label.setText(self._t("roi_mode"))
        for index, key in enumerate(("roi_mode_add", "roi_mode_remove", "roi_mode_replace")):
            self.roi_mode_combo.setItemText(index, self._t(key))
        self.roi_undo_button.setText(self._t("roi_undo"))
        self.roi_clear_button.setText(self._t("roi_clear"))
        self.roi_save_button.setText(self._t("roi_save_calculate"))
        self.roi_stats_button.setText(self._t("roi_view_statistics"))
        active_number = self._active_panel.view_number if self._active_panel else 1
        self.active_view_label.setText(self._t("active_view", number=active_number))
        self.console_dock.setWindowTitle(self._t("python_console"))
        self.console_action.setText(self._t("python_console"))
        self.view_menu.setTitle(self._t("view_menu"))
        self.python_console.set_language(self.language)
        for panel in self.app.viewer.panels:
            panel.set_language(self.language)
        self.refresh_tree()
        self.statusBar().showMessage(self._t("ready"), 3000)

    def _make_panel(self):
        panel = ViewPanel(self.app.database)
        panel.set_language(self.language)
        panel.set_background_color(self.background_color)
        panel.dataset_changed.connect(self._on_dataset_changed)
        panel.field_changed.connect(self._on_field_changed)
        panel.camera_changed.connect(self._on_camera_changed)
        panel.activated.connect(self._activate_panel)
        return panel

    def _background_selected(self, *_):
        selected = self.background_combo.currentData()
        if selected == "custom":
            chosen = QColorDialog.getColor(QColor(self.background_color), self, self._t("background"))
            if not chosen.isValid():
                previous = self.background_combo.findData(self.background_color)
                self.background_combo.blockSignals(True)
                self.background_combo.setCurrentIndex(previous if previous >= 0 else 4)
                self.background_combo.blockSignals(False)
                return
            selected = chosen.name()
        self.background_color = selected
        self.settings.setValue("background_color", selected)
        for panel in self.app.viewer.panels:
            panel.set_background_color(selected)

    def _activate_panel(self, panel):
        self._active_panel = panel
        for candidate in self.app.viewer.panels:
            candidate.set_active_view(candidate is panel and candidate.isVisible())
        if hasattr(self, "active_view_label"):
            self.active_view_label.setText(self._t("active_view", number=panel.view_number or 1))
        self.roi_mode_combo.blockSignals(True)
        self.roi_mode_combo.setCurrentIndex(max(0, self.roi_mode_combo.findData(panel.roi_selection_mode)))
        self.roi_mode_combo.blockSignals(False)

    def _roi_mode_changed(self, *_):
        panel = self._active_panel or self.app.viewer.active()
        if panel:
            panel.roi_selection_mode = self.roi_mode_combo.currentData() or "add"

    def set_layout(self, name: str):
        if name not in LAYOUTS:
            return
        rows, cols = LAYOUTS[name]
        count = rows * cols
        while len(self.app.viewer.panels) < count:
            self.app.viewer.panels.append(self._make_panel())
        while self.view_grid.count():
            self.view_grid.takeAt(0)
        for index, panel in enumerate(self.app.viewer.panels):
            panel.set_view_number(index + 1)
            panel.setVisible(index < count)
            if index < count:
                self.view_grid.addWidget(panel, index // cols, index % cols)
        self._activate_panel(self.app.viewer.panels[0])
        self.statusBar().showMessage(self._t("layout_status", name=name, count=count))

    def refresh_all(self):
        self.refresh_tree()
        for panel in self.app.viewer.panels:
            panel.refresh_cases()

    def refresh_tree(self):
        self.tree.clear()
        project_items, group_items, case_items, dataset_items = {}, {}, {}, {}
        for row in self.app.database.tree():
            pid = row["project_id"]
            if pid not in project_items:
                item = QTreeWidgetItem([row["project_name"], self._t("project")])
                item.setData(0, ROLE_KIND, "project"); item.setData(0, ROLE_ID, pid)
                self.tree.addTopLevelItem(item); project_items[pid] = item
            gid = row["group_id"]
            if gid and gid not in group_items:
                item = QTreeWidgetItem([row["group_name"], self._t("group")])
                item.setData(0, ROLE_KIND, "group"); item.setData(0, ROLE_ID, gid)
                project_items[pid].addChild(item); group_items[gid] = item
            cid = row["case_id"]
            if cid and cid not in case_items:
                item = QTreeWidgetItem([row["case_name"], self._t("case")])
                item.setData(0, ROLE_KIND, "case"); item.setData(0, ROLE_ID, cid)
                group_items[gid].addChild(item); case_items[cid] = item
            did = row["dataset_id"]
            if did and did not in dataset_items:
                item = QTreeWidgetItem([row["dataset_name"], Path(row["file_path"]).suffix.upper()])
                item.setToolTip(0, row["file_path"])
                item.setData(0, ROLE_KIND, "dataset"); item.setData(0, ROLE_ID, did)
                case_items[cid].addChild(item); dataset_items[did] = item
            rid = row["roi_id"]
            if rid:
                item = QTreeWidgetItem([row["roi_name"], self._t("roi")])
                item.setData(0, ROLE_KIND, "roi"); item.setData(0, ROLE_ID, rid)
                dataset_items[did].addChild(item)
        self.tree.expandToDepth(2)

    def _selected_id(self, kind):
        item = self.tree.currentItem()
        while item:
            if item.data(0, ROLE_KIND) == kind:
                return item.data(0, ROLE_ID)
            item = item.parent()
        return None

    def new_project(self):
        name, ok = QInputDialog.getText(self, self._t("new_project_title"), self._t("project_name"))
        if ok and name.strip():
            try: self.app.database.create_project(name.strip()); self.refresh_all()
            except sqlite3.IntegrityError: QMessageBox.warning(self, self._t("duplicate"), self._t("duplicate_project"))

    def new_group(self):
        projects = self.app.database.projects()
        if not projects: return
        selected = self._selected_id("project")
        labels = [r["name"] for r in projects]
        start = next((i for i, r in enumerate(projects) if r["id"] == selected), 0)
        label, ok = QInputDialog.getItem(self, self._t("new_group_title"), self._t("choose_project"), labels, start, False)
        if not ok: return
        name, ok = QInputDialog.getText(self, self._t("new_group_title"), self._t("group_name"))
        if ok and name.strip():
            project_id = projects[labels.index(label)]["id"]
            try: self.app.database.create_group(project_id, name.strip()); self.refresh_all()
            except sqlite3.IntegrityError: QMessageBox.warning(self, self._t("duplicate"), self._t("duplicate_group"))

    def new_case(self):
        groups = self.app.database.groups()
        if not groups: return
        selected = self._selected_id("group")
        labels = [f"{r['project_name']} / {r['name']}" for r in groups]
        start = next((i for i, r in enumerate(groups) if r["id"] == selected), 0)
        label, ok = QInputDialog.getItem(self, self._t("new_case_title"), self._t("choose_group"), labels, start, False)
        if not ok: return
        name, ok = QInputDialog.getText(self, self._t("new_case_title"), self._t("case_name"))
        if ok and name.strip():
            group_id = groups[labels.index(label)]["id"]
            try: self.app.database.create_case(group_id, name.strip()); self.refresh_all()
            except sqlite3.IntegrityError: QMessageBox.warning(self, self._t("duplicate"), self._t("duplicate_case"))

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, self._t("import_title"), "", "VTK XML (*.vtu *.vtp)")
        if not files: return
        destination = ImportDestinationDialog(
            self.app.database, self.language,
            project_id=self._selected_id("project"),
            group_id=self._selected_id("group"),
            case_id=self._selected_id("case"),
            parent=self,
        )
        if destination.exec() != QDialog.DialogCode.Accepted or destination.case_id is None:
            return
        case_id = destination.case_id
        progress = QProgressDialog(self._t("reading"), self._t("cancel"), 0, len(files), self)
        errors = []
        imported_ids = []
        for i, path in enumerate(files):
            if progress.wasCanceled(): break
            progress.setLabelText(self._t("reading_file", name=Path(path).name))
            try:
                _, meta = inspect_dataset(path)
                imported_ids.append(self.app.database.upsert_dataset(case_id, meta))
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")
            progress.setValue(i + 1)
        self.refresh_all()
        if imported_ids:
            panel = self._active_panel or self.app.viewer.active()
            if panel:
                panel.set_dataset(imported_ids[-1])
        if errors: QMessageBox.warning(self, self._t("some_failed"), "\n".join(errors))
        else: self.statusBar().showMessage(self._t("imported", count=len(files)), 5000)

    def open_tree_item(self, item, _column):
        if item.data(0, ROLE_KIND) != "dataset": return
        panel = self._active_panel or self.app.viewer.active()
        panel.set_dataset(item.data(0, ROLE_ID))

    def show_selected_dataset(self):
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_KIND) != "dataset":
            QMessageBox.information(self, self._t("show_selected"), self._t("select_dataset_in_tree"))
            return
        self.open_tree_item(item, 0)

    def delete_selected(self):
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_KIND) not in {"project", "group", "case", "dataset", "roi"}:
            QMessageBox.information(self, self._t("delete_selected"), self._t("delete_nothing"))
            return
        kind = item.data(0, ROLE_KIND)
        entity_id = item.data(0, ROLE_ID)
        name = item.text(0)
        answer = QMessageBox.question(
            self, self._t("delete_confirm_title"), self._t("delete_confirm", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.app.database.delete_entity(kind, entity_id)
        for panel in self.app.viewer.panels:
            if panel.state.dataset_id and self.app.database.dataset(panel.state.dataset_id) is None:
                panel.case_combo.setCurrentIndex(0)
        self.refresh_all()
        self.statusBar().showMessage(self._t("deleted", name=name), 5000)

    def _on_dataset_changed(self, source, dataset_id):
        self._activate_panel(source)
        self.apply_color_policy()

    def _on_field_changed(self, source, name, association):
        self._activate_panel(source)
        if self.field_link.isChecked():
            for panel in self._visible_panels():
                if panel is not source: panel.set_field(name, association)
        self.apply_color_policy()

    def _color_mode_changed(self, *_):
        if self.color_mode.currentData() == "manual":
            panel = self._active_panel or self.app.viewer.active()
            if panel and panel.state.dataset_id:
                key = panel.display_field_key()
                for field in self.app.database.fields(panel.state.dataset_id):
                    if (field["name"], field["association"]) == key and field["minimum"] is not None:
                        self.manual_min.blockSignals(True); self.manual_max.blockSignals(True)
                        self.manual_min.setValue(field["minimum"]); self.manual_max.setValue(field["maximum"])
                        self.manual_min.blockSignals(False); self.manual_max.blockSignals(False)
                        break
        self.apply_color_policy()

    def _visible_panels(self):
        return [p for p in self.app.viewer.panels if p.isVisible()]

    def _on_camera_changed(self, source):
        if not self.camera_link.isChecked() or self._camera_syncing: return
        self._camera_syncing = True
        try:
            for panel in self._visible_panels():
                if panel is not source and panel.state.mesh is not None:
                    sync_camera_relative(source, panel)
        finally:
            self._camera_syncing = False

    def apply_color_policy(self, *_):
        mode = self.color_mode.currentData()
        visible = self._visible_panels()
        global_ranges = {}
        if mode == "global":
            for panel in visible:
                key = panel.display_field_key()
                if not key[0]: continue
                for field in self.app.database.fields(panel.state.dataset_id):
                    if (field["name"], field["association"]) == key and field["minimum"] is not None:
                        current = global_ranges.setdefault(key, [field["minimum"], field["maximum"]])
                        current[0] = min(current[0], field["minimum"]); current[1] = max(current[1], field["maximum"])
        for panel in visible:
            clim = None
            if mode == "manual":
                low, high = self.manual_min.value(), self.manual_max.value()
                if high <= low:
                    high = low + max(abs(low) * 1e-6, 1e-12)
                clim = (low, high)
            elif mode == "global": clim = global_ranges.get(panel.display_field_key())
            panel.render(clim=clim, show_scalar_bar=True)

    def start_streamlines(self):
        panel = self._active_panel or self.app.viewer.active()
        if panel is None or panel.state.mesh is None:
            QMessageBox.information(self, self._t("streamlines"), self._t("roi_load_first"))
            return
        if not vector_fields(panel.state.mesh):
            QMessageBox.information(self, self._t("streamlines"), self._t("no_vector_field"))
            return
        dialog = StreamlineDialog(panel.state.mesh, self.language, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.options()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            stream_mesh, scalar_name = generate_streamlines(panel.state.mesh, options)
            panel.set_streamlines(stream_mesh, scalar_name, options.field, options.association,
                                  options.context_opacity, options.line_width)
            self._active_panel = panel
            self.apply_color_policy()
            self.statusBar().showMessage(self._t("streamline_ready", count=stream_mesh.n_cells), 8000)
        except Exception as exc:
            QMessageBox.critical(self, self._t("streamline_failed"), str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def clear_streamlines(self):
        panel = self._active_panel or self.app.viewer.active()
        if panel and panel.streamline_mesh is not None:
            panel.clear_streamlines()
            self.statusBar().showMessage(self._t("streamline_cleared"), 5000)

    def start_roi_selection(self):
        panel = self._active_panel or self.app.viewer.active()
        if panel is None or panel.state.mesh is None:
            QMessageBox.information(self, "ROI", self._t("roi_load_first")); return

        def selected(selection):
            ids = None
            for key in ("vtkOriginalCellIds", "vtkOriginalCellId"):
                if key in selection.cell_data:
                    ids = np.asarray(selection.cell_data[key], dtype=int).tolist(); break
            if not ids:
                QMessageBox.warning(self, "ROI", self._t("roi_no_ids")); return
            panel.update_pending_roi_selection(ids, panel.roi_selection_mode)
            self.statusBar().showMessage(self._t("roi_selection_ready", number=panel.view_number,
                                                 count=len(panel.pending_roi_cell_ids)))
        try:
            self._activate_panel(panel)
            panel.enable_roi_selection(selected)
            self.statusBar().showMessage(self._t("roi_select_hint"))
        except Exception as exc:
            QMessageBox.warning(self, "ROI", str(exc))

    def clear_roi_selection(self):
        panel = self._active_panel or self.app.viewer.active()
        if panel is None:
            return
        panel.clear_pending_roi_selection()
        self.statusBar().showMessage(self._t("roi_selection_cleared", number=panel.view_number), 5000)

    def undo_roi_selection(self):
        panel = self._active_panel or self.app.viewer.active()
        if panel is None or not panel.undo_pending_roi_selection():
            QMessageBox.information(self, self._t("roi_workflow"), self._t("roi_nothing_to_undo"))
            return
        self.statusBar().showMessage(self._t("roi_selection_undone", count=len(panel.pending_roi_cell_ids)), 5000)

    def save_roi_selection(self):
        panel = self._active_panel or self.app.viewer.active()
        if panel is None or panel.state.mesh is None or not panel.pending_roi_cell_ids:
            QMessageBox.information(self, "ROI", self._t("roi_nothing_selected"))
            return
        name, ok = QInputDialog.getText(self, self._t("save_roi"), self._t("roi_name"))
        if not ok or not name.strip():
            return
        dataset = self.app.database.dataset(panel.state.dataset_id)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            roi_id = self.app.roi.save(dataset["id"], name.strip(), dataset["file_hash"],
                                       panel.pending_roi_cell_ids, panel.state.mesh)
            count = len(panel.pending_roi_cell_ids)
            panel.clear_pending_roi_selection()
            self.refresh_tree()
            self.statusBar().showMessage(self._t("roi_saved", name=name, id=roi_id, count=count), 8000)
        except Exception as exc:
            QMessageBox.critical(self, self._t("roi_failed"), str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def show_roi_statistics(self):
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_KIND) != "roi":
            QMessageBox.information(self, self._t("roi_workflow"), self._t("roi_choose_saved"))
            return
        roi = self.app.database.roi(item.data(0, ROLE_ID))
        if roi is None:
            self.refresh_tree()
            return
        ROIStatisticsDialog(roi, self.app.database.roi_statistics(roi["id"]), self.language, self).exec()

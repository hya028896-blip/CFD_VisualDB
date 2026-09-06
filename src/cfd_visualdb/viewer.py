from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyvista as pv
from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from .i18n import translate


DATASET_MIME = "application/x-cfd-visualdb-dataset-id"


def sync_camera_relative(source_panel, target_panel):
    """Copy a camera in normalized model coordinates, not absolute world coordinates."""
    source_mesh = source_panel.state.mesh
    target_mesh = target_panel.state.mesh
    if source_mesh is None or target_mesh is None:
        return
    source_scale = max(float(source_mesh.length), 1e-12)
    target_scale = max(float(target_mesh.length), 1e-12)
    source_center = np.asarray(source_mesh.center, dtype=float)
    target_center = np.asarray(target_mesh.center, dtype=float)
    source_camera = source_panel.plotter.camera
    target_camera = target_panel.plotter.camera
    source_focal = np.asarray(source_camera.focal_point, dtype=float)
    source_position = np.asarray(source_camera.position, dtype=float)

    normalized_focal_offset = (source_focal - source_center) / source_scale
    normalized_view_vector = (source_position - source_focal) / source_scale
    target_focal = target_center + normalized_focal_offset * target_scale
    target_position = target_focal + normalized_view_vector * target_scale

    target_camera.focal_point = tuple(target_focal)
    target_camera.position = tuple(target_position)
    target_camera.up = source_camera.up
    target_camera.view_angle = source_camera.view_angle
    target_camera.parallel_scale = source_camera.parallel_scale * (target_scale / source_scale)
    target_camera.SetParallelProjection(source_camera.GetParallelProjection())
    target_panel.plotter.reset_camera_clipping_range()
    target_panel.plotter.render()


@dataclass
class ViewState:
    dataset_id: int | None = None
    field_name: str | None = None
    association: str | None = None
    mesh: pv.DataSet | None = None


class ViewPanel(QWidget):
    field_changed = Signal(object, str, str)
    dataset_changed = Signal(object, object)
    camera_changed = Signal(object)
    activated = Signal(object)

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self.state = ViewState()
        self.streamline_mesh = None
        self.streamline_scalar = None
        self.streamline_source_field = None
        self.streamline_source_association = None
        self.streamline_line_width = 1.0
        self.context_opacity = 1.0
        self.background_color = "#ffffff"
        self.foreground_color = "#111111"
        self.view_number = 0
        self.pending_roi_cell_ids: list[int] = []
        self.roi_selection_history: list[list[int]] = []
        self.roi_selection_mode = "add"
        self._is_active_view = False
        self._drop_highlight = False
        self._syncing = False
        self.case_combo = QComboBox()
        self.dataset_combo = QComboBox()
        self.field_combo = QComboBox()
        self.style_combo = QComboBox()
        self._header_labels = []
        header = QHBoxLayout()
        self.view_badge = QLabel("V—")
        self.view_badge.setStyleSheet("font-weight: 700; padding: 1px 4px;")
        header.addWidget(self.view_badge)
        for key, widget in (("case_label", self.case_combo), ("data_label", self.dataset_combo), ("field_label", self.field_combo), ("view_label", self.style_combo)):
            label = QLabel()
            self._header_labels.append((key, label))
            header.addWidget(label)
            header.addWidget(widget, 1)
        self.plotter = QtInteractor(self)
        self.plotter.set_background(self.background_color)
        self.setAcceptDrops(True)
        self.plotter.interactor.setAcceptDrops(True)
        self.plotter.interactor.installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addLayout(header)
        layout.addWidget(self.plotter.interactor, 1)
        self.case_combo.currentIndexChanged.connect(self._case_selected)
        self.dataset_combo.currentIndexChanged.connect(self._dataset_selected)
        self.field_combo.currentIndexChanged.connect(self._field_selected)
        self.style_combo.currentIndexChanged.connect(lambda *_: self.render())
        try:
            self.plotter.iren.add_observer("EndInteractionEvent", lambda *_: self.camera_changed.emit(self))
        except Exception:
            pass
        self.language = "en"
        self.set_language("en")
        self.refresh_cases()

    def _set_drop_highlight(self, enabled: bool):
        self._drop_highlight = enabled
        self._update_border()

    def set_active_view(self, enabled: bool):
        self._is_active_view = enabled
        self._update_border()

    def set_view_number(self, number: int):
        self.view_number = number
        self.view_badge.setText(f"V{number}")

    def _update_border(self):
        if self._drop_highlight:
            border = "3px solid #00a3ff"
        elif self._is_active_view:
            border = "2px solid #2563eb"
        else:
            border = "1px solid transparent"
        self.setStyleSheet(f"ViewPanel {{ border: {border}; border-radius: 4px; }}")

    def _accept_dataset_drag(self, event) -> bool:
        if event.mimeData().hasFormat(DATASET_MIME):
            event.acceptProposedAction()
            return True
        event.ignore()
        return False

    def dragEnterEvent(self, event):
        if self._accept_dataset_drag(event):
            self._set_drop_highlight(True)

    def dragMoveEvent(self, event):
        self._accept_dataset_drag(event)

    def dragLeaveEvent(self, event):
        self._set_drop_highlight(False)
        event.accept()

    def dropEvent(self, event):
        self._set_drop_highlight(False)
        if not event.mimeData().hasFormat(DATASET_MIME):
            event.ignore()
            return
        try:
            dataset_id = int(bytes(event.mimeData().data(DATASET_MIME)).decode("ascii"))
        except (TypeError, ValueError, UnicodeDecodeError):
            event.ignore()
            return
        self.set_dataset(dataset_id)
        event.acceptProposedAction()

    def eventFilter(self, watched, event):
        if watched is self.plotter.interactor:
            if event.type() == QEvent.Type.MouseButtonPress:
                self.activated.emit(self)
            if event.type() == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.DragMove:
                self.dragMoveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.DragLeave:
                self.dragLeaveEvent(event)
                return True
            if event.type() == QEvent.Type.Drop:
                self.dropEvent(event)
                return event.isAccepted()
        return super().eventFilter(watched, event)

    def set_language(self, language: str):
        self.language = language
        for key, label in self._header_labels:
            label.setText(translate(language, key))
        current_style = self.style_combo.currentData() or "surface"
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItem(translate(language, "surface"), "surface")
        self.style_combo.addItem(translate(language, "wireframe"), "wireframe")
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(current_style)))
        self.style_combo.blockSignals(False)
        if self.field_combo.count():
            self.field_combo.setItemText(0, translate(language, "solid_color"))
        if self.state.mesh is None:
            self.render()

    def set_background_color(self, color: str):
        parsed = QColor(color)
        if not parsed.isValid():
            return
        self.background_color = parsed.name()
        luminance = (0.2126 * parsed.red()) + (0.7152 * parsed.green()) + (0.0722 * parsed.blue())
        self.foreground_color = "#111111" if luminance >= 145 else "#ffffff"
        self.plotter.set_background(self.background_color)
        self.render()

    def refresh_cases(self):
        selected = self.case_combo.currentData()
        self.case_combo.blockSignals(True)
        self.case_combo.clear()
        self.case_combo.addItem("—", None)
        for row in self.database.cases():
            self.case_combo.addItem(f"{row['project_name']} / {row['group_name']} / {row['name']}", row["id"])
        index = self.case_combo.findData(selected)
        self.case_combo.setCurrentIndex(max(0, index))
        self.case_combo.blockSignals(False)

    def _case_selected(self):
        case_id = self.case_combo.currentData()
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        self.dataset_combo.addItem("—", None)
        if case_id:
            for row in self.database.datasets(case_id):
                self.dataset_combo.addItem(row["name"], row["id"])
        self.dataset_combo.blockSignals(False)
        self._dataset_selected()

    def set_dataset(self, dataset_id: int | None):
        if dataset_id is None:
            return
        row = self.database.dataset(dataset_id)
        if not row:
            return
        case_index = self.case_combo.findData(row["case_id"])
        if case_index >= 0:
            self.case_combo.setCurrentIndex(case_index)
        data_index = self.dataset_combo.findData(dataset_id)
        if data_index >= 0:
            self.dataset_combo.setCurrentIndex(data_index)

    def _dataset_selected(self):
        dataset_id = self.dataset_combo.currentData()
        self.state = ViewState(dataset_id=dataset_id)
        self.streamline_mesh = None
        self.streamline_scalar = None
        self.streamline_source_field = None
        self.streamline_source_association = None
        self.streamline_line_width = 1.0
        self.context_opacity = 1.0
        self.pending_roi_cell_ids = []
        self.roi_selection_history = []
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        self.field_combo.addItem(translate(self.language, "solid_color"), None)
        if dataset_id:
            for field in self.database.fields(dataset_id):
                self.field_combo.addItem(f"{field['name']} [{field['association']}]", (field["name"], field["association"]))
            row = self.database.dataset(dataset_id)
            try:
                self.state.mesh = pv.read(row["file_path"])
            except Exception as exc:
                self.plotter.clear()
                self.plotter.add_text(f"{translate(self.language, 'unable_load')}\n{exc}", color="tomato")
        self.field_combo.blockSignals(False)
        self.render(reset_camera=True)
        if not self._syncing:
            self.dataset_changed.emit(self, dataset_id)

    def _field_selected(self):
        data = self.field_combo.currentData()
        self.state.field_name, self.state.association = data if data else (None, None)
        self.render()
        if data and not self._syncing:
            self.field_changed.emit(self, data[0], data[1])

    def set_field(self, name: str, association: str):
        index = -1
        for candidate in range(self.field_combo.count()):
            data = self.field_combo.itemData(candidate)
            if data and tuple(data) == (name, association):
                index = candidate
                break
        if index >= 0:
            self._syncing = True
            self.field_combo.setCurrentIndex(index)
            self._syncing = False

    def render(self, clim=None, show_scalar_bar=True, reset_camera=False):
        had_scene = bool(self.plotter.renderer.actors)
        old_camera = self.plotter.camera_position if had_scene and not reset_camera else None
        self.plotter.clear()
        mesh = self.state.mesh
        if mesh is None:
            self.plotter.add_text(translate(self.language, "select_dataset"), color=self.foreground_color, font_size=10)
            return
        data = self.field_combo.currentData()
        name, association = data if data else (None, None)
        self.state.field_name, self.state.association = name, association
        style = self.style_combo.currentData() or "surface"
        kwargs = {
            "style": style,
            "show_scalar_bar": bool(name and show_scalar_bar and self.streamline_mesh is None),
            "scalar_bar_args": {"color": self.foreground_color, "title_font_size": 12, "label_font_size": 10},
            "opacity": self.context_opacity,
        }
        if name:
            kwargs.update({"scalars": name, "preference": association, "cmap": "turbo"})
            if clim is not None:
                kwargs["clim"] = clim
        else:
            kwargs["color"] = "#9eb2c1" if self.foreground_color == "#111111" else "#d8e2e8"
        self.plotter.add_mesh(mesh, **kwargs)
        if self.streamline_mesh is not None:
            self.plotter.add_mesh(
                self.streamline_mesh,
                scalars=self.streamline_scalar,
                preference="point",
                cmap="turbo",
                clim=clim,
                show_scalar_bar=show_scalar_bar,
                scalar_bar_args={"color": self.foreground_color, "title": self.streamline_scalar,
                                 "title_font_size": 12, "label_font_size": 10},
                line_width=self.streamline_line_width,
            )
        self._add_pending_roi_actor()
        if old_camera is not None:
            self.plotter.camera_position = old_camera
        else:
            self.plotter.reset_camera()
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

    def display_field_key(self):
        if self.streamline_mesh is not None and self.streamline_source_field:
            return self.streamline_source_field, self.streamline_source_association
        return self.state.field_name, self.state.association

    def set_streamlines(self, mesh, scalar_name: str, source_field: str, source_association: str,
                        context_opacity: float, line_width: float = 1.0):
        self.streamline_mesh = mesh
        self.streamline_scalar = scalar_name
        self.streamline_source_field = source_field
        self.streamline_source_association = source_association
        self.streamline_line_width = line_width
        self.context_opacity = context_opacity
        self.render(reset_camera=True)

    def clear_streamlines(self):
        self.streamline_mesh = None
        self.streamline_scalar = None
        self.streamline_source_field = None
        self.streamline_source_association = None
        self.streamline_line_width = 1.0
        self.context_opacity = 1.0
        self.render()

    def enable_roi_selection(self, callback):
        if self.state.mesh is None:
            raise ValueError(translate(self.language, "load_before_roi"))
        self.plotter.enable_cell_picking(callback=callback, through=False, show=False, show_message=False,
                                         style="wireframe", color="yellow")

    def update_pending_roi_selection(self, cell_ids: list[int], mode: str | None = None):
        mode = mode or self.roi_selection_mode
        current = set(self.pending_roi_cell_ids)
        incoming = set(map(int, cell_ids))
        self.roi_selection_history.append(sorted(current))
        if len(self.roi_selection_history) > 100:
            self.roi_selection_history.pop(0)
        if mode == "remove":
            current.difference_update(incoming)
        elif mode == "replace":
            current = incoming
        else:
            current.update(incoming)
        self.pending_roi_cell_ids = sorted(current)
        self._add_pending_roi_actor()

    def undo_pending_roi_selection(self) -> bool:
        if not self.roi_selection_history:
            return False
        self.pending_roi_cell_ids = self.roi_selection_history.pop()
        self._add_pending_roi_actor()
        return True

    def _add_pending_roi_actor(self):
        try:
            self.plotter.remove_actor("roi_pending_selection", reset_camera=False, render=False)
        except Exception:
            pass
        if self.state.mesh is not None and self.pending_roi_cell_ids:
            selected = self.state.mesh.extract_cells(np.asarray(self.pending_roi_cell_ids, dtype=int))
            self.plotter.add_mesh(
                selected, name="roi_pending_selection", color="#ffd000", opacity=0.55,
                show_edges=True, edge_color="#ff8c00", line_width=1.5,
                pickable=False, show_scalar_bar=False, reset_camera=False,
            )
        self.plotter.render()

    def clear_pending_roi_selection(self):
        self.pending_roi_cell_ids = []
        self.roi_selection_history = []
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        self.render()

    def closeEvent(self, event):
        self.plotter.close()
        super().closeEvent(event)


class ViewerAPI:
    def __init__(self):
        self.panels: list[ViewPanel] = []

    def active(self) -> ViewPanel | None:
        return self.panels[0] if self.panels else None

    def load(self, dataset_id: int, view_index: int = 0):
        self.panels[view_index].set_dataset(dataset_id)

    def set_field(self, name: str, association: str = "point", view_index: int = 0):
        self.panels[view_index].set_field(name, association)

    def reset_cameras(self):
        for panel in self.panels:
            panel.plotter.reset_camera()

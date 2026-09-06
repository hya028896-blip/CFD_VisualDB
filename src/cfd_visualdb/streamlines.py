from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyvista as pv
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLabel, QSpinBox, QVBoxLayout,
)

from .i18n import translate


def vector_fields(mesh: pv.DataSet) -> list[tuple[str, str]]:
    result = []
    for association, data in (("point", mesh.point_data), ("cell", mesh.cell_data)):
        for name in data.keys():
            array = np.asarray(data[name])
            if array.ndim == 2 and array.shape[1] == 3 and np.issubdtype(array.dtype, np.number):
                result.append((str(name), association))
    return result


@dataclass
class StreamlineOptions:
    field: str
    association: str
    seed_count: int
    direction: str
    initial_step_length: float
    max_length: float
    terminal_speed: float
    tube_radius: float
    line_width: float
    context_opacity: float


def generate_streamlines(mesh: pv.DataSet, options: StreamlineOptions) -> tuple[pv.PolyData, str]:
    working = mesh
    if options.association == "cell":
        working = mesh.cell_data_to_point_data(pass_cell_data=True)
    if options.field not in working.point_data:
        raise ValueError(f"Vector field '{options.field}' is not available as point data")
    if working.n_cells == 0:
        raise ValueError("The dataset has no cells for streamline integration")

    centers = np.asarray(working.cell_centers().points)
    count = min(options.seed_count, len(centers))
    indices = np.linspace(0, len(centers) - 1, count, dtype=int)
    source = pv.PolyData(centers[indices])
    lines = working.streamlines_from_source(
        source,
        vectors=options.field,
        integrator_type=45,
        integration_direction=options.direction,
        initial_step_length=options.initial_step_length,
        step_unit="cl",
        max_steps=4000,
        terminal_speed=options.terminal_speed,
        max_error=1e-6,
        compute_vorticity=False,
        max_length=options.max_length,
    )
    if lines.n_points == 0 or lines.n_cells == 0:
        raise ValueError("No streamlines were generated. Check the velocity field, units, seed coverage, and terminal speed.")

    magnitude_name = f"{options.field} magnitude"
    vectors = np.asarray(lines.point_data[options.field], dtype=float)
    lines.point_data[magnitude_name] = np.linalg.norm(vectors, axis=1)
    rendered = lines.tube(radius=options.tube_radius, n_sides=8) if options.tube_radius > 0 else lines
    return rendered, magnitude_name


class StreamlineDialog(QDialog):
    def __init__(self, mesh: pv.DataSet, language: str, parent=None):
        super().__init__(parent)
        self.mesh = mesh
        self.language = language
        self.setWindowTitle(translate(language, "streamlines"))
        layout = QVBoxLayout(self)
        note = QLabel(translate(language, "streamline_note"))
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.vector_combo = QComboBox()
        for name, association in vector_fields(mesh):
            self.vector_combo.addItem(f"{name} [{association}]", (name, association))
        form.addRow(translate(language, "vector_field"), self.vector_combo)
        self.seed_count = QSpinBox(); self.seed_count.setRange(5, 2000); self.seed_count.setValue(120)
        form.addRow(translate(language, "seed_count"), self.seed_count)
        self.direction = QComboBox()
        for key in ("both", "forward", "backward"):
            self.direction.addItem(translate(language, key), key)
        form.addRow(translate(language, "integration_direction"), self.direction)
        self.initial_step = QDoubleSpinBox(); self.initial_step.setRange(0.001, 10.0); self.initial_step.setDecimals(4); self.initial_step.setValue(0.2)
        form.addRow(translate(language, "initial_step"), self.initial_step)
        self.max_length = QDoubleSpinBox(); self.max_length.setRange(1e-9, 1e12); self.max_length.setDecimals(4); self.max_length.setValue(max(mesh.length * 2.0, 1e-6))
        form.addRow(translate(language, "max_length"), self.max_length)
        self.terminal_speed = QDoubleSpinBox(); self.terminal_speed.setRange(0.0, 1e12); self.terminal_speed.setDecimals(10); self.terminal_speed.setValue(1e-12)
        form.addRow(translate(language, "terminal_speed"), self.terminal_speed)
        self.tube_radius = QDoubleSpinBox(); self.tube_radius.setRange(0.0, 1e12); self.tube_radius.setDecimals(6); self.tube_radius.setValue(0.0)
        form.addRow(translate(language, "tube_radius"), self.tube_radius)
        self.line_width = QDoubleSpinBox(); self.line_width.setRange(1.0, 20.0); self.line_width.setDecimals(1); self.line_width.setSingleStep(0.5); self.line_width.setValue(1.0)
        form.addRow(translate(language, "line_width"), self.line_width)
        self.context_opacity = QDoubleSpinBox(); self.context_opacity.setRange(0.0, 1.0); self.context_opacity.setSingleStep(0.05); self.context_opacity.setValue(0.18)
        form.addRow(translate(language, "context_opacity"), self.context_opacity)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def options(self) -> StreamlineOptions:
        field, association = self.vector_combo.currentData()
        return StreamlineOptions(
            field=field, association=association, seed_count=self.seed_count.value(),
            direction=self.direction.currentData(), initial_step_length=self.initial_step.value(),
            max_length=self.max_length.value(), terminal_speed=self.terminal_speed.value(),
            tube_radius=self.tube_radius.value(), line_width=self.line_width.value(),
            context_opacity=self.context_opacity.value(),
        )

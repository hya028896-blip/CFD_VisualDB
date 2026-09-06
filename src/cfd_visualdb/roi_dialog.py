from __future__ import annotations

import json

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from .i18n import translate


class ROIStatisticsDialog(QDialog):
    STAT_KEYS = ("area_weighted_mean", "mean", "median", "p5", "p10", "p25", "p75", "p90", "p95", "min", "max", "std")

    def __init__(self, roi, rows, language: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate(language, "roi_statistics_title", name=roi["name"]))
        self.resize(1100, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(translate(language, "roi_summary", dataset=roi["dataset_name"],
                                          cells=len(json.loads(roi["cell_ids_json"])), area=roi["area"] or 0.0)))
        self.table = QTableWidget(len(rows), 2 + len(self.STAT_KEYS))
        self.table.setHorizontalHeaderLabels([translate(language, "field_label"), translate(language, "association"), *self.STAT_KEYS])
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(row["field_name"]))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["association"]))
            for column, key in enumerate(self.STAT_KEYS, start=2):
                value = row["statistics"].get(key)
                self.table.setItem(row_index, column, QTableWidgetItem("—" if value is None else f"{value:.8g}"))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

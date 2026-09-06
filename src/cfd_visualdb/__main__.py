from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .app_context import AppContext
from .main_window import MainWindow


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    db_path = Path(os.environ.get("CFD_VISUALDB_DB", project_root / "data" / "cfd_visualdb.sqlite3"))
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName("CFD VisualDB")
    context = AppContext.create(db_path)
    window = MainWindow(context)
    smoke_test = "--smoke-test" in sys.argv
    if not smoke_test:
        window.show()
    else:
        QTimer.singleShot(1200, qt_app.quit)
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

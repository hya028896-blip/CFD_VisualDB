from __future__ import annotations

import contextlib
import io
import traceback

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget


class PythonConsole(QWidget):
    def __init__(self, namespace: dict, parent=None):
        super().__init__(parent)
        self.namespace = namespace
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.input = QLineEdit()
        self.input.returnPressed.connect(self.execute)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.output)
        layout.addWidget(self.input)

    def set_language(self, language: str):
        from .i18n import translate
        if not self.output.toPlainText().strip():
            self.output.setPlainText(translate(language, "console_ready"))
        self.input.setPlaceholderText(translate(language, "console_prompt"))

    def execute(self):
        source = self.input.text().strip()
        if not source:
            return
        self.input.clear()
        capture = io.StringIO()
        self.output.appendPlainText(f">>> {source}")
        try:
            with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
                try:
                    value = eval(source, self.namespace, self.namespace)
                    if value is not None:
                        print(repr(value))
                except SyntaxError:
                    exec(source, self.namespace, self.namespace)
        except Exception:
            traceback.print_exc(file=capture)
        self.output.appendPlainText(capture.getvalue().rstrip())

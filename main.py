from __future__ import annotations

import ctypes
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

from promptcase_studio.config import initialize_runtime_environment, resource_path
from promptcase_studio.ui.main_window import MainWindow
from promptcase_studio.ui.styles import APP_STYLESHEET


def main() -> int:
    initialize_runtime_environment()
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PromptcaseStudio.Desktop.0.1"
        )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Promptcase Studio")
    app.setOrganizationName("Promptcase Studio")
    app.setWindowIcon(QIcon(str(resource_path("favicon.ico"))))
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())

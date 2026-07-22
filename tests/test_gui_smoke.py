import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from promptcase_studio.ui.main_window import MainWindow
from promptcase_studio.ui.settings_dialog import SettingsDialog


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_and_terminal_construct(self):
        window = MainWindow()
        self.assertEqual(window.windowTitle(), "Promptcase Studio")
        self.assertFalse(window.windowIcon().isNull())
        self.assertTrue(window.online_radio.isChecked())
        window.terminal.append_log("SCAN", "테스트 로그")
        self.assertIn("테스트 로그", window.terminal.output.toPlainText())
        window.terminal.clear()
        self.assertIn("터미널 로그를 지웠습니다", window.terminal.output.toPlainText())
        window.close()

    def test_settings_dialog_constructs(self):
        window = MainWindow()
        dialog = SettingsDialog(window.settings, window)
        self.assertEqual(dialog.windowTitle(), "Promptcase Studio 환경설정")
        self.assertEqual(dialog.qwen_settings_path.text(), "config/qwen.settings.json")
        self.assertEqual(dialog.gemini_timeout.value(), 300)
        self.assertEqual(dialog.gemini_attempts.value(), 3)
        self.assertEqual(dialog.qwen_timeout.value(), 300)
        self.assertEqual(dialog.qwen_attempts.value(), 3)
        dialog.close()
        window.close()


if __name__ == "__main__":
    unittest.main()

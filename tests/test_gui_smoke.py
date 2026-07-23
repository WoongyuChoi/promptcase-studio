import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QApplication, QFileDialog, QLineEdit, QMessageBox

from promptcase_studio.models import ChangeItem, PipelineResult, ScanBundle
from promptcase_studio.scanner import collect_changes
from promptcase_studio.ui.main_window import MainWindow
from promptcase_studio.ui.settings_dialog import SettingsDialog
from promptcase_studio.ui.styles import APP_STYLESHEET
from promptcase_studio.ui.worker import _git_change_input_line


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(APP_STYLESHEET)

    def test_main_window_and_terminal_construct(self):
        window = MainWindow()
        self.assertEqual(window.windowTitle(), "Promptcase Studio")
        self.assertFalse(window.windowIcon().isNull())
        self.assertTrue(window.online_radio.isChecked())
        today = QDate.currentDate()
        self.assertEqual(window.date_from.date(), QDate(today.year(), today.month(), 1))
        self.assertEqual(window.date_to.date(), today)
        self.assertEqual(window.date_from.maximumDate(), today)
        self.assertEqual(window.date_to.maximumDate(), today)
        self.assertTrue(window.date_from.calendarPopup())
        self.assertTrue(window.date_to.calendarPopup())
        self.assertEqual(window.date_from_label.text(), "시작일")
        self.assertEqual(window.date_to_label.text(), "종료일")
        self.assertEqual(window.template_button.text(), "템플릿 내려받기")
        self.assertEqual(window.header_environment.height(), window.settings_button.height())
        self.assertEqual(window.template_button.height(), window.settings_button.height())
        window.terminal.append_log("SCAN", "테스트 로그")
        self.assertIn("테스트 로그", window.terminal.output.toPlainText())
        window.terminal.append_log("TRACE", "A" * 2_000)
        self.assertIn("자 생략", window.terminal.output.toPlainText())
        window.terminal.reset_stream()
        window.terminal.append_chunk("B" * (window.terminal.MAX_STREAM_CHARS + 1_000))
        self.assertIn("응답 표시 한도", window.terminal.output.toPlainText())
        window.terminal.clear()
        self.assertIn("터미널 로그를 지웠습니다", window.terminal.output.toPlainText())
        window.close()

    def test_invalid_date_range_stops_analysis_with_clear_message(self):
        window = MainWindow()
        window.folder_list.addItem(str(Path(__file__).parent))
        window.request_text.setPlainText("날짜 범위 검증용 변경 내용")
        window.date_from.setMaximumDate(QDate(2099, 12, 31))
        window.date_to.setMaximumDate(QDate(2099, 12, 31))
        window.date_from.setDate(QDate(2026, 7, 22))
        window.date_to.setDate(QDate(2026, 7, 21))

        with patch.object(QMessageBox, "warning") as warning:
            window._start_pipeline()

        warning.assert_called_once_with(
            window,
            "날짜 범위 확인",
            "종료일은 시작일과 같거나 이후 날짜로 선택해 주세요.",
        )
        self.assertIsNone(window.worker)
        window.close()

    def test_disabling_modified_date_range_returns_open_range(self):
        window = MainWindow()
        window.date_checkbox.setChecked(False)

        self.assertEqual(window._selected_date_range(), (None, None))
        self.assertFalse(window.date_from.isEnabled())
        self.assertFalse(window.date_to.isEnabled())
        window.close()

    def test_test_case_download_uses_save_dialog_destination(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "단위테스트 템플릿.xlsx"
        case_root = project_root / "tmp" / "tests" / "gui-download"
        case_root.mkdir(parents=True, exist_ok=True)
        destination = case_root / "사업계획관리시스템_단위테스트_20260722_180000.xlsx"
        if destination.exists():
            destination.unlink()
        window = MainWindow()
        window.last_result = PipelineResult(
            run_id="test",
            run_directory=source.parent,
            document_path=source,
            suggested_filename=destination.name,
            response_path=source,
            scan_bundle=ScanBundle(),
        )
        with (
            patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")),
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "critical") as critical,
        ):
            window._download_test_case()
        self.assertTrue(destination.exists(), critical.call_args)
        critical.assert_not_called()
        window.close()

    def test_failed_workbook_validation_does_not_replace_existing_download(self):
        project_root = Path(__file__).resolve().parent.parent
        case_root = project_root / "tmp" / "tests" / "gui-download-validation"
        case_root.mkdir(parents=True, exist_ok=True)
        damaged_source = case_root / "damaged-preview.xlsx"
        destination = case_root / "existing-user-document.xlsx"
        temp_path = destination.with_name(f".{destination.name}.tmp")
        damaged_source.write_bytes(b"not-an-xlsx")
        destination.write_bytes(b"existing-user-content")
        if temp_path.exists():
            temp_path.unlink()

        window = MainWindow()
        window.last_result = PipelineResult(
            run_id="damaged",
            run_directory=case_root,
            document_path=damaged_source,
            suggested_filename=destination.name,
            response_path=damaged_source,
            scan_bundle=ScanBundle(),
        )
        with (
            patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")),
            patch.object(QMessageBox, "information") as information,
            patch.object(QMessageBox, "critical") as critical,
        ):
            window._download_test_case()

        self.assertEqual(destination.read_bytes(), b"existing-user-content")
        self.assertFalse(temp_path.exists())
        critical.assert_called_once()
        information.assert_not_called()
        window.close()

    def test_editing_an_input_invalidates_the_previous_download(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "단위테스트 템플릿.xlsx"
        window = MainWindow()
        window.last_result = PipelineResult(
            run_id="stale-result",
            run_directory=source.parent,
            document_path=source,
            suggested_filename="이전결과_단위테스트.xlsx",
            response_path=source,
            scan_bundle=ScanBundle(),
        )
        window.download_button.setEnabled(True)

        window.request_text.setPlainText("새로운 변경 의뢰 내용을 입력한다")

        self.assertIsNone(window.last_result)
        self.assertFalse(window.download_button.isEnabled())
        window.close()

    def test_result_is_discarded_if_inputs_change_during_analysis(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "단위테스트 템플릿.xlsx"
        result = PipelineResult(
            run_id="outdated-analysis",
            run_directory=source.parent,
            document_path=source,
            suggested_filename="이전분석_단위테스트.xlsx",
            response_path=source,
            scan_bundle=ScanBundle(),
        )
        window = MainWindow()
        window._active_request_revision = window._input_revision
        window.request_text.setPlainText("분석 도중 바뀐 입력")
        with patch.object(QMessageBox, "information") as information:
            window._pipeline_completed(result)

        self.assertIsNone(window.last_result)
        self.assertFalse(window.download_button.isEnabled())
        information.assert_not_called()
        window.close()

    def test_control_panel_fits_at_reference_resolution(self):
        window = MainWindow()
        window.resize(1500, 900)
        window.show()
        self.app.processEvents()
        self.assertFalse(window.control_scroll.verticalScrollBar().isVisible())
        window.close()

    def test_control_panel_fits_at_common_laptop_resolution(self):
        window = MainWindow()
        window.resize(1366, 768)
        window.show()
        self.app.processEvents()
        self.assertFalse(window.control_scroll.verticalScrollBar().isVisible())
        window.close()

    def test_settings_dialog_constructs(self):
        window = MainWindow()
        dialog = SettingsDialog(window.settings, window)
        self.assertEqual(dialog.windowTitle(), "Promptcase Studio 환경설정")
        self.assertEqual(dialog.qwen_settings_path.text(), "config/qwen.settings.json")
        self.assertEqual(dialog.gemini_timeout.value(), 300)
        self.assertEqual(dialog.gemini_attempts.value(), 3)
        self.assertEqual(dialog.gemini_output_tokens.value(), 32768)
        self.assertEqual(dialog.gemini_key.echoMode(), QLineEdit.Normal)
        self.assertEqual(dialog.qwen_timeout.value(), 300)
        self.assertEqual(dialog.qwen_attempts.value(), 3)
        self.assertEqual(dialog.qwen_output_tokens.value(), 32768)
        self.assertEqual(dialog.validation_attempts.value(), 3)
        self.assertTrue(dialog.quality_review_checkbox.isChecked())
        dialog.close()
        window.close()

    def test_settings_dialog_saves_only_user_editable_local_overrides(self):
        window = MainWindow()
        dialog = SettingsDialog(window.settings, window)
        dialog.gemini_attempts.setValue(4)

        with (
            patch("promptcase_studio.ui.settings_dialog.save_dotenv_secret"),
            patch("promptcase_studio.ui.settings_dialog.save_local_settings") as save_settings,
        ):
            dialog._save()

        saved = save_settings.call_args.args[0]
        self.assertEqual(
            set(saved),
            {
                "defaultEnvironment",
                "mockMode",
                "qualityReviewEnabled",
                "responseValidationAttempts",
                "providers",
            },
        )
        self.assertNotIn("scanner", saved)
        self.assertNotIn("templatePath", saved)
        self.assertEqual(saved["providers"]["online"]["maxAttempts"], 4)
        self.assertNotIn("retryDelaySeconds", saved["providers"]["online"])
        self.assertNotIn("type", saved["providers"]["online"])
        self.assertNotIn("retryDelaySeconds", saved["providers"]["secure"])
        self.assertNotIn("stream", saved["providers"]["secure"])
        self.assertNotIn("type", saved["providers"]["secure"])
        window.close()

    def test_qwen_file_browser_starts_from_resolved_config_directory(self):
        window = MainWindow()
        dialog = SettingsDialog(window.settings, window)
        with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")) as browse:
            dialog._browse_qwen_settings()
        initial = Path(browse.call_args.args[2]).resolve()
        self.assertEqual(initial, (Path(__file__).resolve().parent.parent / "config").resolve())
        dialog.close()
        window.close()

    def test_native_checkbox_indicator_is_not_replaced_by_solid_fill(self):
        self.assertNotIn("QCheckBox::indicator:checked", APP_STYLESHEET)

    def test_git_import_keeps_the_origin_root_for_duplicate_relative_paths(self):
        fixture = Path(__file__).parent / "fixtures" / "multi_root"
        frontend = (fixture / "frontend").resolve()
        backend = (fixture / "backend").resolve()
        line = _git_change_input_line(
            ChangeItem(str(frontend), "README.md", "변경", "git-working-tree", True)
        )
        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend, backend],
            line,
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(Path(changes[0].root), frontend)


if __name__ == "__main__":
    unittest.main()

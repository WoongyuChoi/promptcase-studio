import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QDate, QSize, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
)

from promptcase_studio import __version__
from promptcase_studio.models import ChangeItem, PipelineResult, ScanBundle
from promptcase_studio.scanner import collect_changes
from promptcase_studio.ui.main_window import MainWindow, _wrap_alert_text
from promptcase_studio.ui.release_note_dialog import ReleaseNoteDialog
from promptcase_studio.ui.settings_dialog import SettingsDialog
from promptcase_studio.ui.styles import APP_STYLESHEET
from promptcase_studio.ui.tooltip import HelpTooltipButton
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
        self.assertEqual(window.width(), 1366)
        self.assertEqual(window.height(), 768)
        self.assertFalse(window.windowIcon().isNull())
        self.assertEqual(
            window.online_radio.isChecked(),
            window.settings.get("defaultEnvironment", "secure") == "online",
        )
        self.assertEqual(
            window.secure_radio.isChecked(),
            window.settings.get("defaultEnvironment", "secure") == "secure",
        )
        self.assertEqual(window.online_radio.text(), "온라인(Gemini)")
        self.assertEqual(window.secure_radio.text(), "폐쇄망(Qwen)")
        self.assertEqual(window.findChild(QLabel, "brandTitle").text(), "PROMPTCASE STUDIO")
        self.assertIsNone(window.findChild(QLabel, "terminalSub"))
        self.assertEqual(window.terminal.status.text(), "READY")
        self.assertEqual(window.terminal.status.property("state"), "ready")
        startup_text = window.terminal.output.toPlainText()
        self.assertIn("PROMPTCASE STUDIO", startup_text)
        self.assertIn(f"(v{__version__})", startup_text)
        self.assertIn("[INFO] 실행 콘솔 준비 완료", startup_text)
        self.assertEqual(len(window.terminal._LOGO_COLUMNS), 10)
        self.assertEqual(len(window.terminal._LOGO_COLORS), 10)
        self.assertGreater(window.terminal.output.toHtml().count("\xa0"), 50)
        self.assertNotIn("SECURE NETWORK", startup_text)
        self.assertNotIn("qwen3.6-agent", startup_text)
        self.assertNotIn("SCAN > CONTEXT > AI > VALIDATE > EXCEL", startup_text)
        window.terminal.set_running(True)
        self.assertEqual(window.terminal.status.text(), "RUNNING")
        self.assertEqual(window.terminal.status.property("state"), "running")
        window.terminal.set_running(False)
        self.assertEqual(window.terminal.status.text(), "READY")
        self.assertEqual(window.terminal.status.property("state"), "ready")
        self.assertEqual(len(window.help_buttons), 4)
        self.assertTrue(all(button.toolTip() for button in window.help_buttons))
        self.assertTrue(all(button.width() == 12 for button in window.help_buttons))
        self.assertTrue(
            all(isinstance(button, HelpTooltipButton) for button in window.help_buttons)
        )
        self.assertTrue(
            all(button.focusPolicy() == Qt.StrongFocus for button in window.help_buttons)
        )
        self.assertEqual(window.release_note_button.text(), "릴리즈 노트 뷰")
        self.assertFalse(window.release_note_button.isEnabled())
        window.help_buttons[0].show_bubble()
        self.app.processEvents()
        bubble = window.help_buttons[0]._bubble
        self.assertTrue(bubble.isVisible())
        self.assertEqual(bubble.card.width(), bubble.CARD_WIDTH)
        self.assertEqual(bubble.arrow.geometry().right() + 1, bubble.card.geometry().left())
        self.assertEqual(bubble.seam.width(), 3)
        self.assertLessEqual(
            bubble.seam.geometry().left(), bubble.arrow.geometry().right()
        )
        self.assertGreaterEqual(
            bubble.seam.geometry().right(), bubble.card.geometry().left()
        )
        window.help_buttons[0].hide_bubble()
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
        self.assertFalse(window.template_button.icon().isNull())
        self.assertFalse(window.settings_button.icon().isNull())
        self.assertEqual(window.template_button.iconSize(), QSize(15, 15))
        self.assertEqual(window.settings_button.iconSize(), QSize(15, 15))
        self.assertFalse(window.template_button.icon().pixmap(QSize(30, 30)).isNull())
        self.assertFalse(window.settings_button.icon().pixmap(QSize(30, 30)).isNull())
        self.assertEqual(window.header_environment.height(), window.settings_button.height())
        self.assertEqual(window.template_button.height(), window.settings_button.height())
        button_texts = {button.text() for button in window.findChildren(QPushButton)}
        self.assertIn("행 추가", button_texts)
        self.assertIn("행 삭제", button_texts)
        self.assertNotIn("셀 추가", button_texts)
        self.assertNotIn("셀 삭제", button_texts)
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

    def test_release_note_dialog_is_editable_copyable_and_disposable(self):
        subject = "[공유] 저장 조건 변경"
        body = (
            "안녕하세요.\n\n저장 조건을 변경했습니다.\n\n"
            "변경 사항 유무에 따른 동작을 테스트해 주세요.\n\n감사합니다."
        )
        dialog = ReleaseNoteDialog(subject, body)

        self.assertFalse(dialog.windowFlags() & Qt.WindowContextHelpButtonHint)
        self.assertFalse(dialog.subject_edit.isReadOnly())
        self.assertFalse(dialog.body_edit.isReadOnly())
        self.assertFalse(dialog.copy_button.icon().isNull())
        self.assertEqual(
            dialog.close_button.font().pixelSize(),
            dialog.copy_button.font().pixelSize(),
        )

        dialog.subject_edit.setText("사용자가 수정한 제목")
        dialog.body_edit.setPlainText("사용자가 수정한 본문")
        dialog.copy_button.click()

        self.assertEqual(
            QApplication.clipboard().text(),
            "제목: 사용자가 수정한 제목\n\n사용자가 수정한 본문",
        )
        self.assertEqual(dialog.copy_status.text(), "메일 문안을 복사했습니다.")
        dialog.reject()

        reopened = ReleaseNoteDialog(subject, body)
        self.assertEqual(reopened.subject_edit.text(), subject)
        self.assertEqual(reopened.body_edit.toPlainText(), body)
        reopened.close()

    def test_project_path_cells_accept_direct_input_and_skip_invalid_paths(self):
        window = MainWindow()
        valid = str(Path(__file__).parent.resolve())
        window.folder_list.addItem(valid)
        window.folder_list.addItem("Z:/promptcase/path/that/does/not/exist")

        roots = window._selected_roots(report_skipped=True)

        self.assertEqual(roots, [Path(valid)])
        self.assertIn("검색 대상에서 제외", window.terminal.output.toPlainText())
        window.close()

    def test_project_paths_use_native_windows_separators(self):
        window = MainWindow()
        window.folder_list.add_path("C:/Project/promptcase-studio")

        self.assertIn(
            r"C:\Project\promptcase-studio",
            window.folder_list.paths(),
        )
        window.close()

    def test_project_path_list_shows_four_full_rows_without_clipping(self):
        window = MainWindow()
        for index in range(1, 4):
            window.folder_list.add_path(f"C:/Project/example-{index}")
        window.show()
        self.app.processEvents()

        last_rect = window.folder_list.visualItemRect(
            window.folder_list.item(window.folder_list.count() - 1)
        )
        self.assertEqual(window.folder_list.count(), 4)
        self.assertEqual(window.folder_list.viewport().height(), 140)
        self.assertEqual(window.folder_list.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(
            last_rect.bottom(), window.folder_list.viewport().rect().bottom()
        )
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

    def test_daily_quota_failure_uses_actionable_warning_dialog(self):
        window = MainWindow()
        message = "Gemini 무료 등급 모델의 일일 요청 한도를 모두 사용했습니다."

        with (
            patch.object(QMessageBox, "warning") as warning,
            patch.object(QMessageBox, "critical") as critical,
        ):
            window._pipeline_failed(message)

        warning.assert_called_once_with(window, "AI 사용량 한도 도달", message)
        critical.assert_not_called()
        self.assertEqual(window.terminal.status.text(), "ERROR")
        self.assertEqual(window.terminal.status.property("state"), "error")
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
        source = project_root / "templates" / "unittest_template.xlsx"
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
            patch(
                "promptcase_studio.ui.main_window.QDesktopServices.openUrl",
                return_value=True,
            ) as open_directory,
        ):
            window._download_test_case()
        self.assertTrue(destination.exists(), critical.call_args)
        critical.assert_not_called()
        open_directory.assert_called_once()
        self.assertEqual(
            Path(open_directory.call_args.args[0].toLocalFile()),
            destination.parent.resolve(),
        )
        window.close()

    def test_template_download_uses_english_source_and_korean_default_name(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "unittest_template.xlsx"
        case_root = project_root / "tmp" / "tests" / "gui-template-download"
        case_root.mkdir(parents=True, exist_ok=True)
        destination = case_root / "단위테스트 템플릿.xlsx"
        if destination.exists():
            destination.unlink()
        captured_default = {}

        def choose_destination(_parent, _title, default_path, _filter):
            captured_default["path"] = Path(default_path)
            return str(destination), ""

        window = MainWindow()
        with (
            patch.object(QFileDialog, "getSaveFileName", side_effect=choose_destination),
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "critical") as critical,
        ):
            window._download_template()

        self.assertEqual(captured_default["path"].name, "단위테스트 템플릿.xlsx")
        self.assertEqual(destination.read_bytes(), source.read_bytes())
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
        source = project_root / "templates" / "unittest_template.xlsx"
        window = MainWindow()
        window.last_result = PipelineResult(
            run_id="stale-result",
            run_directory=source.parent,
            document_path=source,
            suggested_filename="이전결과_단위테스트.xlsx",
            response_path=source,
            scan_bundle=ScanBundle(),
            release_note_subject="[공유] 이전 결과",
            release_note_body="안녕하세요.\n\n이전 결과입니다.\n\n감사합니다.",
        )
        window.download_button.setEnabled(True)
        window.release_note_button.setEnabled(True)

        window.request_text.setPlainText("새로운 변경 의뢰 내용을 입력한다")

        self.assertIsNone(window.last_result)
        self.assertFalse(window.download_button.isEnabled())
        self.assertFalse(window.release_note_button.isEnabled())
        window.close()

    def test_result_is_discarded_if_inputs_change_during_analysis(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "unittest_template.xlsx"
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
        self.assertFalse(window.release_note_button.isEnabled())
        information.assert_not_called()
        window.close()

    def test_review_required_result_still_enables_download_with_warning(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "unittest_template.xlsx"
        result = PipelineResult(
            run_id="review-required",
            run_directory=source.parent,
            document_path=source,
            suggested_filename="검토필요_단위테스트.xlsx",
            response_path=source,
            scan_bundle=ScanBundle(),
            quality_status="review_required",
            quality_score=53,
            quality_issue_count=5,
            quality_critical_count=4,
            release_note_subject="[공유] 검토 필요 결과",
            release_note_body="안녕하세요.\n\n검토가 필요한 변경입니다.\n\n감사합니다.",
        )
        window = MainWindow()
        window._active_request_revision = window._input_revision

        with (
            patch.object(QMessageBox, "warning") as warning,
            patch.object(QMessageBox, "information") as information,
        ):
            window._pipeline_completed(result)

        self.assertIs(window.last_result, result)
        self.assertTrue(window.download_button.isEnabled())
        self.assertTrue(window.release_note_button.isEnabled())
        warning.assert_called_once()
        self.assertIn("필수 검토 항목 4건", warning.call_args.args[2])
        information.assert_not_called()
        window.close()

    def test_soft_quality_review_warning_distinguishes_reference_items(self):
        project_root = Path(__file__).resolve().parent.parent
        source = project_root / "templates" / "unittest_template.xlsx"
        result = PipelineResult(
            run_id="soft-review",
            run_directory=source.parent,
            document_path=source,
            suggested_filename="참고검토_단위테스트.xlsx",
            response_path=source,
            scan_bundle=ScanBundle(),
            quality_status="review_required",
            quality_score=90,
            quality_issue_count=2,
            quality_critical_count=0,
        )
        window = MainWindow()
        window._active_request_revision = window._input_revision

        with patch.object(QMessageBox, "warning") as warning:
            window._pipeline_completed(result)

        warning.assert_called_once()
        self.assertIn("참고 검토 항목 2건", warning.call_args.args[2])
        self.assertTrue(window.download_button.isEnabled())
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
        self.assertEqual(window.control_scroll.parentWidget().width(), 580)
        self.assertLess(window.release_note_button.x(), window.download_button.x())
        self.assertEqual(
            window.release_note_button.height(),
            window.download_button.height(),
        )
        self.assertGreaterEqual(window.online_radio.width(), window.online_radio.sizeHint().width())
        radio_gap = (
            window.online_radio.geometry().left()
            - window.secure_radio.geometry().right()
            - 1
        )
        self.assertEqual(radio_gap, 8)
        self.assertGreater(window.date_from_label.x(), window.date_checkbox.geometry().right())
        self.assertLessEqual(window.date_from.width(), 132)
        self.assertLessEqual(window.date_to.width(), 132)
        self.assertGreaterEqual(window.date_from.width(), 110)
        self.assertGreaterEqual(window.date_to.width(), 110)
        self.assertEqual(
            window.date_from_label.font().pixelSize(),
            window.date_checkbox.font().pixelSize(),
        )
        self.assertEqual(
            window.date_to_label.font().pixelSize(),
            window.date_checkbox.font().pixelSize(),
        )
        window.close()

    def test_control_panel_is_usable_at_compact_target_resolution(self):
        window = MainWindow()
        window.resize(1024, 576)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.size().width(), 1024)
        self.assertEqual(window.size().height(), 576)
        vertical_scroll = window.control_scroll.verticalScrollBar()
        self.assertGreater(vertical_scroll.maximum(), 0)
        vertical_scroll.setValue(vertical_scroll.maximum())
        self.app.processEvents()
        self.assertEqual(vertical_scroll.value(), vertical_scroll.maximum())
        self.assertFalse(window.control_scroll.horizontalScrollBar().isVisible())
        self.assertFalse(
            window.terminal.output.horizontalScrollBar().isVisible()
        )
        self.assertGreaterEqual(window.control_scroll.parentWidget().width(), 500)
        self.assertLessEqual(window.control_scroll.parentWidget().width(), 620)
        self.assertEqual(window.progress.parentWidget().objectName(), "progressCluster")
        self.assertEqual(
            window.progress.parentWidget().parentWidget().objectName(), "card"
        )
        self.assertEqual(window.progress_label.text(), "PROGRESS")
        self.assertGreater(
            window.progress.geometry().top(),
            window.progress_label.geometry().bottom(),
        )
        self.assertEqual(window.progress.width(), 116)
        self.assertLess(window.secure_radio.geometry().x(), window.online_radio.geometry().x())
        self.assertGreater(window.git_checkbox.geometry().y(), window.date_checkbox.geometry().y())
        self.assertEqual(window.run_button.width(), 90)
        self.assertEqual(window.download_button.width(), 160)
        run_bottom = window.run_button.mapTo(
            window, window.run_button.rect().bottomLeft()
        ).y()
        download_bottom = window.download_button.mapTo(
            window, window.download_button.rect().bottomLeft()
        ).y()
        terminal_bottom = window.terminal.mapTo(
            window, window.terminal.rect().bottomLeft()
        ).y()
        self.assertEqual(run_bottom, download_bottom)
        self.assertEqual(run_bottom, terminal_bottom)
        window.close()

    def test_settings_dialog_constructs(self):
        window = MainWindow()
        window.settings["qualityReviewPasses"] = 2
        window.settings["qualityReviewValidationAttempts"] = 2
        window.settings["qualityGateMode"] = "best_effort"
        dialog = SettingsDialog(window.settings, window)
        self.assertEqual(dialog.windowTitle(), "Promptcase Studio 환경설정")
        self.assertEqual(dialog.width(), 800)
        self.assertEqual(dialog.height(), 580)
        self.assertEqual(dialog.findChild(QLabel, "dialogTitle").text(), "환경설정")
        self.assertEqual(dialog.tabs.objectName(), "settingsTabs")
        self.assertEqual(dialog.save_button.objectName(), "dialogPrimaryButton")
        self.assertEqual(dialog.cancel_button.objectName(), "dialogSecondaryButton")
        self.assertEqual(dialog.save_button.size(), QSize(88, 32))
        self.assertEqual(dialog.cancel_button.size(), QSize(72, 32))
        self.assertEqual(dialog.qwen_browse_button.size(), QSize(92, 28))
        self.assertEqual(dialog.qwen_settings_path.text(), "config/qwen.settings.json")
        self.assertEqual(dialog.gemini_timeout.value(), 300)
        self.assertEqual(dialog.gemini_model.currentData(), "auto")
        self.assertEqual(dialog.gemini_model.count(), 5)
        self.assertEqual(dialog.gemini_model.itemText(0), "Auto")
        self.assertEqual(dialog.gemini_model.itemText(1), "Gemini 3.6 Flash")
        self.assertIn("gemini-3.5-flash-lite", dialog.gemini_fallback_message)
        self.assertEqual(
            dialog.gemini_model_help.tooltip_body,
            dialog.gemini_fallback_message,
        )
        self.assertEqual(dialog.gemini_model.width(), 280)
        self.assertEqual(dialog.gemini_attempts.value(), 3)
        self.assertEqual(dialog.gemini_output_tokens.value(), 32768)
        self.assertEqual(dialog.gemini_key.echoMode(), QLineEdit.Normal)
        self.assertEqual(dialog.qwen_timeout.value(), 300)
        self.assertEqual(dialog.qwen_attempts.value(), 3)
        self.assertEqual(dialog.qwen_output_tokens.value(), 32768)
        self.assertEqual(dialog.validation_attempts.value(), 3)
        self.assertTrue(dialog.quality_review_checkbox.isChecked())
        self.assertEqual(dialog.quality_review_passes.value(), 2)
        self.assertEqual(dialog.quality_review_validation_attempts.value(), 2)
        self.assertEqual(dialog.quality_gate_mode.currentData(), "best_effort")
        self.assertIn("최대 4회", dialog.quality_request_help.tooltip_body)
        self.assertFalse(
            bool(dialog.windowFlags() & Qt.WindowContextHelpButtonHint)
        )
        self.assertGreaterEqual(
            len(dialog.findChildren(QFrame, "settingsSection")),
            4,
        )
        self.assertEqual(
            len(dialog.findChildren(QFrame, "settingsInfoSection")),
            2,
        )
        increase = dialog.quality_review_passes.findChild(
            QToolButton, "spinIncreaseButton"
        )
        decrease = dialog.quality_review_passes.findChild(
            QToolButton, "spinDecreaseButton"
        )
        self.assertIsNotNone(increase)
        self.assertIsNotNone(decrease)
        dialog.show()
        tabs = dialog.findChild(QTabWidget)
        tabs.setCurrentIndex(0)
        self.app.processEvents()
        tab_bar = tabs.tabBar()
        for index in range(tab_bar.count()):
            with self.subTest(tab=index):
                text_width = tab_bar.fontMetrics().horizontalAdvance(
                    tab_bar.tabText(index)
                )
                self.assertGreaterEqual(
                    tab_bar.tabRect(index).width(),
                    text_width + 32,
                )
        self.assertEqual(dialog.qwen_settings_path.minimumHeight(), 28)
        self.assertEqual(dialog.qwen_settings_path.maximumHeight(), 28)
        self.assertEqual(dialog.quality_gate_mode.height(), 24)
        self.assertGreaterEqual(dialog.quality_gate_mode.view().minimumHeight(), 52)
        dialog.quality_gate_mode.showPopup()
        self.app.processEvents()
        self.assertTrue(dialog.quality_gate_mode.view().isVisible())
        last_item = dialog.quality_gate_mode.model().index(
            dialog.quality_gate_mode.count() - 1,
            0,
        )
        self.assertLess(
            dialog.quality_gate_mode.view().visualRect(last_item).bottom(),
            dialog.quality_gate_mode.view().viewport().height(),
        )
        dialog.quality_gate_mode.hidePopup()
        self.assertEqual(dialog.qwen_timeout.minimumHeight(), 24)
        self.assertEqual(dialog.qwen_timeout.maximumHeight(), 24)
        field_labels = dialog.findChildren(QLabel, "settingsFieldLabel")
        self.assertEqual(len(field_labels), 14)
        self.assertTrue(
            all(
                label.font().pixelSize()
                == dialog.quality_review_checkbox.font().pixelSize()
                for label in field_labels
            )
        )
        self.assertTrue(
            all(
                label.font().weight()
                == dialog.quality_review_checkbox.font().weight()
                for label in field_labels
            )
        )
        self.assertEqual(
            dialog.quality_review_passes.font().pixelSize(),
            window.date_from.font().pixelSize(),
        )
        self.assertEqual(
            dialog.quality_gate_mode.font().pixelSize(),
            window.date_from.font().pixelSize(),
        )
        self.assertLessEqual(
            abs(dialog.quality_gate_mode.height() - window.date_from.height()),
            1,
        )
        self.assertEqual(dialog.qwen_settings_path.font().pixelSize(), 12)
        self.assertEqual(dialog.gemini_key.font().pixelSize(), 12)
        self.assertEqual(dialog.save_button.height(), window.run_button.height())
        self.assertEqual(dialog.qwen_browse_button.height(), 28)
        self.assertTrue(increase.isVisible())
        self.assertTrue(decrease.isVisible())
        self.assertLess(increase.geometry().right(), dialog.quality_review_passes.width())
        self.assertLess(decrease.geometry().right(), dialog.quality_review_passes.width())
        increase.click()
        self.assertEqual(dialog.quality_review_passes.value(), 3)
        decrease.click()
        self.assertEqual(dialog.quality_review_passes.value(), 2)
        dialog.close()
        window.close()

    def test_settings_dialog_remains_aligned_at_minimum_size(self):
        window = MainWindow()
        dialog = SettingsDialog(window.settings, window)
        dialog.resize(dialog.minimumSize())
        dialog.show()

        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            self.app.processEvents()
            page = dialog.tabs.currentWidget()
            self.assertGreater(page.width(), 0)
            self.assertGreater(page.height(), 0)

        self.assertEqual(dialog.size(), QSize(720, 540))
        self.assertLess(dialog.button_box.geometry().bottom(), dialog.height())
        self.assertGreaterEqual(dialog.tabs.width(), 680)
        self.assertEqual(dialog.save_button.height(), 32)
        self.assertEqual(dialog.cancel_button.height(), 32)
        dialog.close()
        window.close()

    def test_settings_dialog_saves_only_user_editable_local_overrides(self):
        window = MainWindow()
        window.settings["qualityReviewPasses"] = 2
        window.settings["qualityReviewValidationAttempts"] = 2
        window.settings["qualityGateMode"] = "best_effort"
        dialog = SettingsDialog(window.settings, window)
        dialog.gemini_attempts.setValue(4)
        dialog.gemini_model.setCurrentIndex(
            dialog.gemini_model.findData("gemini-3.5-flash-lite")
        )

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
                "qualityReviewPasses",
                "qualityReviewValidationAttempts",
                "qualityGateMode",
                "responseValidationAttempts",
                "providers",
            },
        )
        self.assertNotIn("scanner", saved)
        self.assertNotIn("templatePath", saved)
        self.assertEqual(saved["providers"]["online"]["maxAttempts"], 4)
        self.assertEqual(saved["providers"]["online"]["model"], "gemini-3.5-flash-lite")
        self.assertEqual(saved["qualityReviewPasses"], 2)
        self.assertEqual(saved["qualityReviewValidationAttempts"], 2)
        self.assertEqual(saved["qualityGateMode"], "best_effort")
        self.assertNotIn("fallbackOnDailyQuota", saved["providers"]["online"])
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
        self.assertNotIn("button-symbols", APP_STYLESHEET)
        self.assertIn(
            "QDialog#settingsDialog QRadioButton::indicator",
            APP_STYLESHEET,
        )
        self.assertIn(
            "QDialog#settingsDialog QCheckBox::indicator",
            APP_STYLESHEET,
        )
        self.assertNotIn(
            "QDialog#settingsDialog QComboBox::drop-down",
            APP_STYLESHEET,
        )

    def test_long_alert_message_wraps_within_a_bounded_width(self):
        message = (
            "저장 경로와 처리 결과를 확인해 주세요. "
            + "C:/Project/very-long-project-name/deeply/nested/output/"
            + ("generated-test-case-" * 12)
            + ".xlsx"
        )
        wrapped = _wrap_alert_text(message)

        self.assertIn("\n", wrapped)
        self.assertTrue(all(len(line) <= 48 for line in wrapped.splitlines()))
        self.assertEqual(
            "".join(wrapped.split()),
            "".join(message.split()),
        )

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

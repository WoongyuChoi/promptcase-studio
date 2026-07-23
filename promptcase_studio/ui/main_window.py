from __future__ import annotations

import html
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QDate, QTimer, Qt
from PyQt5.QtGui import QCloseEvent, QFont, QIcon, QTextCursor
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from promptcase_studio.config import PROJECT_ROOT, load_settings, resolve_project_path
from promptcase_studio.excel_writer import validate_workbook
from promptcase_studio.models import AnalysisRequest, PipelineResult
from promptcase_studio.template_catalog import UNIT_TEST_TEMPLATE
from promptcase_studio.ui.settings_dialog import SettingsDialog
from promptcase_studio.ui.styles import TERMINAL_STYLE
from promptcase_studio.ui.worker import GitDiffWorker, PipelineWorker


LOG_COLORS = {
    "START": "#8DF0A5",
    "SCAN": "#7DD3FC",
    "DATE": "#A5B4FC",
    "GIT": "#C4B5FD",
    "CONTEXT": "#67E8F9",
    "SCAN-FILE": "#7DD3FC",
    "DIFF": "#A5B4FC",
    "GRAPH": "#C4B5FD",
    "RELATED": "#67E8F9",
    "BUDGET": "#FDE68A",
    "MANUAL": "#93C5FD",
    "ARTIFACT": "#94A3B8",
    "PROMPT": "#FDE68A",
    "API": "#FDBA74",
    "RETRY": "#FBBF24",
    "FALLBACK": "#F59E0B",
    "MOCK": "#D8B4FE",
    "RESPONSE": "#86EFAC",
    "ATTEMPT": "#FDBA74",
    "USAGE": "#5EEAD4",
    "QUALITY": "#F0ABFC",
    "REVIEW": "#D8B4FE",
    "VALIDATE": "#F0ABFC",
    "EXCEL": "#93C5FD",
    "DONE": "#6EE7B7",
    "WARN": "#FCD34D",
    "QUOTA": "#FDBA74",
    "PAUSED": "#FDBA74",
    "ERROR": "#FDA4AF",
    "TRACE": "#64748B",
    "INFO": "#94A3B8",
}


def _validated_atomic_copy(source: Path, destination: Path) -> None:
    """Validate a copied workbook before replacing an existing user file."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copy2(source, temp_path)
        validate_workbook(temp_path)
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


class TerminalPanel(QFrame):
    MAX_LOG_CHARS = 1_600
    MAX_STREAM_CHARS = 12_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminalFrame")
        self.setStyleSheet(TERMINAL_STYLE)

        header = QFrame()
        header.setObjectName("terminalHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 10, 8)
        header_layout.setSpacing(8)

        dots = QLabel("CONSOLE")
        dots.setObjectName("terminalDots")
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("PROMPTCASE STUDIO  PIPELINE CONSOLE")
        title.setObjectName("terminalTitle")
        subtitle = QLabel("SCAN   CONTEXT   PROMPT   RESPONSE   DOCUMENT")
        subtitle.setObjectName("terminalSub")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status = QLabel("READY")
        self.status.setObjectName("terminalStatus")
        clear_button = QPushButton("로그 지우기")
        clear_button.setObjectName("terminalButton")
        clear_button.clicked.connect(self.clear)

        header_layout.addWidget(dots)
        header_layout.addSpacing(10)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        header_layout.addWidget(self.status)
        header_layout.addWidget(clear_button)

        self.output = QTextEdit()
        self.output.setObjectName("terminalOutput")
        self.output.setReadOnly(True)
        self.output.setAcceptRichText(True)
        self.output.document().setMaximumBlockCount(3_000)
        self.output.setFont(QFont("Cascadia Mono", 9))
        self._stream_chars = 0
        self._stream_truncated = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.output, 1)
        self.append_log("INFO", "실행 콘솔 준비 완료")
        self.append_log("INFO", "스캔, AI 요청, 응답, 문서 생성 과정이 여기에 기록됩니다")

    def append_log(self, level: str, message: str) -> None:
        if level == "ATTEMPT":
            self.reset_stream()
        color = LOG_COLORS.get(level, "#CBD5E1")
        message = str(message).strip()
        if len(message) > self.MAX_LOG_CHARS:
            omitted = len(message) - 1_000
            message = f"{message[:900]}\n표시 한도를 넘어 {omitted:,}자 생략\n{message[-100:]}"
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_message = html.escape(message).replace("\n", "<br>")
        self.output.append(
            f'<span style="color:#52657C">{timestamp}</span> '
            f'<span style="color:{color};font-weight:700">[{html.escape(level)}]</span> '
            f'<span style="color:#C8D7E7">{safe_message}</span>'
        )
        self.output.moveCursor(QTextCursor.End)

    def append_chunk(self, chunk: str) -> None:
        if self._stream_truncated:
            return
        if self._stream_chars == 0:
            self.append_log("RESPONSE", "AI 응답 내용 수신 시작")
        remaining = self.MAX_STREAM_CHARS - self._stream_chars
        visible = chunk[:remaining]
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        safe_chunk = html.escape(visible).replace(" ", "&nbsp;").replace("\n", "<br>")
        cursor.insertHtml(f'<span style="color:#86EFAC">{safe_chunk}</span>')
        self._stream_chars += len(visible)
        if len(chunk) > len(visible) or self._stream_chars >= self.MAX_STREAM_CHARS:
            cursor.insertHtml(
                '<br><span style="color:#64748B">응답 표시 한도를 넘어 이후 내용은 생략합니다</span>'
            )
            self._stream_truncated = True
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def reset_stream(self) -> None:
        self._stream_chars = 0
        self._stream_truncated = False

    def clear(self) -> None:
        self.output.clear()
        self.reset_stream()
        self.append_log("INFO", "터미널 로그를 지웠습니다")

    def set_running(self, running: bool) -> None:
        self.status.setText("RUNNING" if running else "READY")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings: dict[str, Any] = load_settings()
        self.worker: PipelineWorker | None = None
        self.git_worker: GitDiffWorker | None = None
        self.last_result: PipelineResult | None = None
        self.current_run_succeeded = False
        self._close_when_finished = False
        self._input_revision = 0
        self._active_request_revision: int | None = None
        self.setWindowTitle("Promptcase Studio")
        self.setWindowIcon(QIcon(str(PROJECT_ROOT / "favicon.ico")))
        self.resize(1500, 900)
        self.setMinimumSize(1180, 720)
        self._build_ui()
        self._apply_default_environment()
        self._connect_result_invalidation()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_top_bar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_control_panel())
        self.terminal = TerminalPanel()
        terminal_wrap = QWidget()
        terminal_layout = QVBoxLayout(terminal_wrap)
        terminal_layout.setContentsMargins(6, 14, 16, 16)
        terminal_layout.addWidget(self.terminal)
        splitter.addWidget(terminal_wrap)
        splitter.setSizes([610, 890])
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        frame.setFixedHeight(60)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 8, 16, 8)
        layout.setSpacing(8)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignCenter)
        icon_pixmap = QIcon(str(PROJECT_ROOT / "favicon.ico")).pixmap(24, 24)
        if icon_pixmap.isNull():
            mark.setText("PC")
        else:
            mark.setPixmap(icon_pixmap)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Promptcase Studio")
        title.setObjectName("brandTitle")
        subtitle = QLabel("SOURCE CHANGE TO UNIT TEST DOCUMENT")
        subtitle.setObjectName("brandSub")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.header_environment = QLabel()
        self.header_environment.setObjectName("environmentBadge")
        self.header_environment.setFixedHeight(32)
        self.header_environment.setAlignment(Qt.AlignCenter)
        self.template_button = QPushButton(UNIT_TEST_TEMPLATE.button_label)
        self.template_button.setObjectName("topActionButton")
        self.template_button.setFixedHeight(32)
        self.template_button.clicked.connect(self._download_template)
        self.settings_button = QPushButton("환경설정")
        self.settings_button.setObjectName("topActionButton")
        self.settings_button.setFixedHeight(32)
        self.settings_button.clicked.connect(self._open_settings)
        layout.addWidget(mark)
        layout.addSpacing(10)
        layout.addLayout(title_box)
        layout.addStretch(1)
        layout.addWidget(self.header_environment)
        layout.addWidget(self.template_button)
        layout.addWidget(self.settings_button)
        return frame

    def _build_control_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.control_scroll = scroll
        container = QWidget()
        container.setObjectName("controlPanel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 9, 6, 9)
        layout.setSpacing(6)

        layout.addWidget(self._build_environment_card())
        layout.addWidget(self._build_project_card())
        layout.addWidget(self._build_change_card())
        layout.addWidget(self._build_request_card())

        self.run_button = QPushButton("변경 분석 시작")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._start_pipeline)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.download_button = QPushButton("테스트케이스 다운로드")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._download_test_case)
        self.open_output_button = self.download_button
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.run_button, 1)
        actions.addWidget(self.download_button)
        layout.addLayout(actions)
        layout.addWidget(self.progress)
        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _card(self, title: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        hint_label = QLabel(hint)
        hint_label.setObjectName("sectionHint")
        hint_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        return card, layout

    def _build_environment_card(self) -> QFrame:
        card, layout = self._card("01  AI 연결 환경", "온라인은 Gemini API, 중요단말망은 Qwen 설정을 사용합니다.")
        self.online_radio = QRadioButton("온라인 Gemini")
        self.secure_radio = QRadioButton("중요단말망 Qwen")
        group = QButtonGroup(self)
        group.addButton(self.online_radio)
        group.addButton(self.secure_radio)
        self.online_radio.toggled.connect(self._update_environment_badge)
        row = QHBoxLayout()
        row.addWidget(self.online_radio)
        row.addSpacing(12)
        row.addWidget(self.secure_radio)
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _build_project_card(self) -> QFrame:
        card, layout = self._card("02  분석 대상", "프로젝트 루트 또는 분석이 필요한 핵심 폴더를 추가하세요.")
        self.folder_list = QListWidget()
        self.folder_list.setFixedHeight(52)
        self.folder_list.setToolTip("분석할 프로젝트 또는 핵심 소스 폴더 목록")
        add_button = QPushButton("프로젝트 추가")
        add_button.setObjectName("greenButton")
        remove_button = QPushButton("선택 제거")
        add_button.clicked.connect(self._add_folder)
        remove_button.clicked.connect(self._remove_folder)
        row = QHBoxLayout()
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addStretch(1)
        layout.addWidget(self.folder_list)
        layout.addLayout(row)
        return card

    def _build_change_card(self) -> QFrame:
        card, layout = self._card("03  변경 범위", "Git 이력, 수정일 범위, 수동 목록을 조합해 분석할 파일을 확정합니다.")
        date_row = QHBoxLayout()
        date_row.setSpacing(7)
        self.date_checkbox = QCheckBox("날짜 범위")
        self.date_checkbox.setChecked(True)
        self.date_checkbox.setToolTip("Git 이력과 파일 수정일에 같은 시작일과 종료일을 적용합니다.")
        today = QDate.currentDate()
        self.date_from_label = QLabel("시작일")
        self.date_from_label.setObjectName("dateRangeLabel")
        self.date_from = QDateEdit()
        self.date_from.setObjectName("rangeDate")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setMaximumDate(today)
        self.date_from.setDate(QDate(today.year(), today.month(), 1))
        self.date_from.setToolTip("변경 범위에 포함할 시작일")
        self.date_to_label = QLabel("종료일")
        self.date_to_label.setObjectName("dateRangeLabel")
        self.date_to = QDateEdit()
        self.date_to.setObjectName("rangeDate")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setMaximumDate(today)
        self.date_to.setDate(today)
        self.date_to.setToolTip("변경 범위에 포함할 종료일")
        self.git_checkbox = QCheckBox("Git 변경 포함")
        self.git_checkbox.setChecked(True)
        self.date_checkbox.toggled.connect(self.date_from_label.setEnabled)
        self.date_checkbox.toggled.connect(self.date_from.setEnabled)
        self.date_checkbox.toggled.connect(self.date_to_label.setEnabled)
        self.date_checkbox.toggled.connect(self.date_to.setEnabled)
        date_row.addWidget(self.date_checkbox)
        date_row.addWidget(self.date_from_label)
        date_row.addWidget(self.date_from)
        date_row.addWidget(self.date_to_label)
        date_row.addWidget(self.date_to)
        date_row.addWidget(self.git_checkbox)
        date_row.addStretch(1)
        self.manual_changes = QTextEdit()
        self.manual_changes.setFixedHeight(80)
        self.manual_changes.setPlaceholderText(
            "변경 파일을 한 줄에 하나씩 입력하세요.\n"
            "예: M src/api/UserApi.java\nD src/api/LegacyApi.java\n"
            "Git을 사용하지 않아도 파일명이나 경로로 찾을 수 있습니다."
        )
        self.diff_button = QPushButton("Git 변경 가져오기")
        self.diff_button.clicked.connect(self._load_git_diff)
        clear_button = QPushButton("목록 비우기")
        clear_button.clicked.connect(self.manual_changes.clear)
        button_row = QHBoxLayout()
        button_row.addWidget(self.diff_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        layout.addLayout(date_row)
        layout.addWidget(self.manual_changes)
        layout.addLayout(button_row)
        return card

    def _build_request_card(self) -> QFrame:
        card, layout = self._card("04  변경 내용 및 의뢰서", "구현 의도, 업무 규칙, 확인이 필요한 시나리오를 자연어로 작성하세요.")
        self.request_text = QTextEdit()
        self.request_text.setFixedHeight(90)
        self.request_text.setPlaceholderText(
            "예\n"
            "사용자 조회 API를 삭제하고 연관된 메뉴 진입 경로를 정리했습니다.\n"
            "계약유지서비스 조회 기준과 VISS_D1300 툴팁 계산식을 변경했습니다."
        )
        layout.addWidget(self.request_text)
        return card

    def _apply_default_environment(self) -> None:
        default = self.settings.get("defaultEnvironment", "online")
        self.online_radio.setChecked(default != "secure")
        self.secure_radio.setChecked(default == "secure")
        self._update_environment_badge()

    def _connect_result_invalidation(self) -> None:
        self.online_radio.toggled.connect(self._invalidate_result)
        self.date_checkbox.toggled.connect(self._invalidate_result)
        self.date_from.dateChanged.connect(self._invalidate_result)
        self.date_to.dateChanged.connect(self._invalidate_result)
        self.git_checkbox.toggled.connect(self._invalidate_result)
        self.manual_changes.textChanged.connect(self._invalidate_result)
        self.request_text.textChanged.connect(self._invalidate_result)
        self.folder_list.model().rowsInserted.connect(self._invalidate_result)
        self.folder_list.model().rowsRemoved.connect(self._invalidate_result)

    def _invalidate_result(self, *_args) -> None:
        self._input_revision += 1
        self.last_result = None
        self.current_run_succeeded = False
        self.download_button.setEnabled(False)

    def _update_environment_badge(self) -> None:
        environment = "온라인 Gemini" if self.online_radio.isChecked() else "중요단말망 Qwen"
        if self.settings.get("mockMode"):
            environment += " (MOCK)"
        self.header_environment.setText(environment)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "분석할 프로젝트 폴더 선택")
        if folder and not self.folder_list.findItems(folder, Qt.MatchExactly):
            self.folder_list.addItem(folder)

    def _remove_folder(self) -> None:
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))

    def _selected_roots(self) -> list[Path]:
        return [Path(self.folder_list.item(index).text()).resolve() for index in range(self.folder_list.count())]

    def _selected_date_range(self) -> tuple[date | None, date | None]:
        if not self.date_checkbox.isChecked():
            return None, None
        from_value = self.date_from.date()
        to_value = self.date_to.date()
        return (
            date(from_value.year(), from_value.month(), from_value.day()),
            date(to_value.year(), to_value.month(), to_value.day()),
        )

    def _validate_date_range(self) -> bool:
        date_from, date_to = self._selected_date_range()
        if date_from is None or date_to is None or date_from <= date_to:
            return True
        QMessageBox.warning(
            self,
            "날짜 범위 확인",
            "종료일은 시작일과 같거나 이후 날짜로 선택해 주세요.",
        )
        self.date_to.setFocus()
        return False

    def _load_git_diff(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if self.git_worker is not None and self.git_worker.isRunning():
            return
        roots = self._selected_roots()
        if not roots:
            QMessageBox.information(self, "Git Diff", "먼저 프로젝트 폴더를 추가해 주세요.")
            return
        if not self._validate_date_range():
            return
        date_from, date_to = self._selected_date_range()
        self.git_worker = GitDiffWorker(roots, date_from, date_to)
        self.git_worker.log_message.connect(self.terminal.append_log)
        self.git_worker.completed.connect(self._git_diff_completed)
        self.git_worker.failed.connect(self._git_diff_failed)
        self.git_worker.finished.connect(self._git_diff_finished)
        self.diff_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.terminal.append_log("GIT", "Git 변경 이력을 백그라운드에서 조회")
        self.git_worker.start()

    def _git_diff_completed(self, records: list[str]) -> None:
        if records:
            current = self.manual_changes.toPlainText().strip()
            combined = "\n".join(dict.fromkeys([*(current.splitlines() if current else []), *records]))
            self.manual_changes.setPlainText(combined)
            self.terminal.append_log("GIT", f"입력란에 Git 변경 {len(records)}개 반영")
        else:
            QMessageBox.information(self, "Git Diff", "불러올 Git 변경사항이 없습니다.")

    def _git_diff_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Git 변경 조회 실패", message)

    def _git_diff_finished(self) -> None:
        self.diff_button.setEnabled(True)
        self.run_button.setEnabled(self.worker is None)
        self.git_worker = None
        if self._close_when_finished and self.worker is None:
            self.setEnabled(True)
            QTimer.singleShot(0, self.close)

    def _start_pipeline(self) -> None:
        if self.git_worker is not None and self.git_worker.isRunning():
            QMessageBox.information(self, "Git 변경 조회", "Git 변경 조회가 끝난 뒤 분석을 시작해 주세요.")
            return
        roots = self._selected_roots()
        request_text = self.request_text.toPlainText().strip()
        if not roots:
            QMessageBox.warning(self, "입력 확인", "분석할 프로젝트 폴더를 한 개 이상 추가해 주세요.")
            return
        if not request_text:
            QMessageBox.warning(self, "입력 확인", "변경 로직 또는 의뢰서 내용을 입력해 주세요.")
            return
        if not self._validate_date_range():
            return
        date_from, date_to = self._selected_date_range()
        request = AnalysisRequest(
            project_roots=roots,
            manual_changes=self.manual_changes.toPlainText(),
            request_text=request_text,
            environment="online" if self.online_radio.isChecked() else "secure",
            date_from=date_from,
            date_to=date_to,
            include_git=self.git_checkbox.isChecked(),
        )
        self.worker = PipelineWorker(request, self.settings)
        self.worker.log_message.connect(self.terminal.append_log)
        self.worker.response_chunk.connect(self.terminal.append_chunk)
        self.worker.completed.connect(self._pipeline_completed)
        self.worker.failed.connect(self._pipeline_failed)
        self.worker.finished.connect(self._worker_finished)
        self._active_request_revision = self._input_revision
        self.current_run_succeeded = False
        self.last_result = None
        self.control_scroll.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.terminal.set_running(True)
        self.terminal.reset_stream()
        self.terminal.append_log("START", "사용자 요청을 작업 큐에 등록")
        self.worker.start()

    def _pipeline_completed(self, result: PipelineResult) -> None:
        if self._active_request_revision != self._input_revision:
            self.current_run_succeeded = False
            self.last_result = None
            self.download_button.setEnabled(False)
            self.terminal.append_log(
                "WARN",
                "분석 중 입력 상태가 달라져 완료 결과를 폐기했습니다. 현재 입력으로 다시 분석해 주세요",
            )
            return
        self.last_result = result
        self.current_run_succeeded = True
        self.download_button.setEnabled(True)
        if result.quality_status == "review_required":
            QMessageBox.warning(
                self,
                "검토 필요 초안 생성 완료",
                "다운로드 가능한 최선의 초안을 생성했습니다.\n"
                f"품질 점수 {result.quality_score}점, 필수 검토 항목 "
                f"{result.quality_critical_count}건이 남아 있습니다.\n"
                "저장 후 실행 폴더의 품질 진단과 문안을 함께 확인해 주세요.",
            )
            return
        QMessageBox.information(
            self,
            "분석 완료",
            "단위테스트 초안을 완성했습니다.\n"
            "테스트케이스 다운로드를 선택해 저장할 폴더와 파일명을 지정하세요.",
        )

    def _pipeline_failed(self, message: str) -> None:
        if "일일 요청 한도" in message or "AI 사용량 한도" in message:
            QMessageBox.warning(self, "AI 사용량 한도 도달", message)
            return
        QMessageBox.critical(self, "작업 실패", message)

    def _worker_finished(self) -> None:
        self.control_scroll.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if self.current_run_succeeded else 0)
        self.download_button.setEnabled(self.current_run_succeeded and self.last_result is not None)
        self.terminal.set_running(False)
        self.worker = None
        self._active_request_revision = None
        if self._close_when_finished and self.git_worker is None:
            self.setEnabled(True)
            QTimer.singleShot(0, self.close)

    def _default_save_directory(self) -> Path:
        configured = resolve_project_path(self.settings.get("outputDirectory", "outputs"))
        try:
            configured.mkdir(parents=True, exist_ok=True)
            return configured
        except OSError:
            return Path.home()

    def _download_test_case(self) -> None:
        if not self.last_result or not self.last_result.document_path.exists():
            QMessageBox.warning(self, "다운로드 확인", "먼저 변경 분석을 완료해 주세요.")
            return
        default_path = self._default_save_directory() / self.last_result.suggested_filename
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "테스트케이스 저장",
            str(default_path),
            "Excel 통합 문서 (*.xlsx)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.casefold() != ".xlsx":
            destination = destination.with_suffix(".xlsx")
        try:
            _validated_atomic_copy(self.last_result.document_path, destination)
        except Exception as exc:
            self.terminal.append_log("ERROR", f"테스트케이스 저장 실패: {exc}")
            QMessageBox.critical(self, "저장 실패", str(exc))
            return
        self.terminal.append_log("DONE", f"테스트케이스 저장 완료: {destination}")
        QMessageBox.information(self, "저장 완료", f"테스트케이스를 저장했습니다.\n\n{destination}")

    def _download_template(self) -> None:
        source = resolve_project_path(
            self.settings.get("templatePath", UNIT_TEST_TEMPLATE.relative_path)
        )
        if not source.exists():
            QMessageBox.critical(self, "템플릿 오류", f"템플릿을 찾을 수 없습니다.\n\n{source}")
            return
        default_path = self._default_save_directory() / UNIT_TEST_TEMPLATE.download_name
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "템플릿 저장",
            str(default_path),
            "Excel 통합 문서 (*.xlsx)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.casefold() != ".xlsx":
            destination = destination.with_suffix(".xlsx")
        try:
            _validated_atomic_copy(source, destination)
        except Exception as exc:
            self.terminal.append_log("ERROR", f"템플릿 저장 실패: {exc}")
            QMessageBox.critical(self, "저장 실패", str(exc))
            return
        self.terminal.append_log("DONE", f"템플릿 저장 완료: {destination}")
        QMessageBox.information(self, "저장 완료", f"템플릿을 저장했습니다.\n\n{destination}")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_():
            self.settings = load_settings()
            self._apply_default_environment()
            self._invalidate_result()
            self.terminal.append_log("INFO", "환경설정을 다시 불러왔습니다")

    def closeEvent(self, event: QCloseEvent) -> None:
        pipeline_running = self.worker is not None and self.worker.isRunning()
        git_running = self.git_worker is not None and self.git_worker.isRunning()
        if pipeline_running or git_running:
            answer = QMessageBox.question(
                self,
                "작업 진행 중",
                "진행 중인 작업이 끝난 뒤 안전하게 종료합니다. 종료를 예약하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self._close_when_finished = True
                self.setEnabled(False)
                self.terminal.append_log("INFO", "현재 작업이 끝나면 프로그램을 종료합니다")
            event.ignore()
            return
        super().closeEvent(event)

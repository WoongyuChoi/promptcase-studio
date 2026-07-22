from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QDate, QUrl, Qt
from PyQt5.QtGui import QDesktopServices, QFont, QIcon, QTextCursor
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

from promptcase_studio.config import PROJECT_ROOT, load_settings
from promptcase_studio.models import AnalysisRequest, PipelineResult
from promptcase_studio.scanner import collect_git_changes
from promptcase_studio.ui.settings_dialog import SettingsDialog
from promptcase_studio.ui.styles import TERMINAL_STYLE
from promptcase_studio.ui.worker import PipelineWorker


LOG_COLORS = {
    "START": "#8DF0A5",
    "SCAN": "#7DD3FC",
    "DATE": "#A5B4FC",
    "GIT": "#C4B5FD",
    "CONTEXT": "#67E8F9",
    "ARTIFACT": "#94A3B8",
    "PROMPT": "#FDE68A",
    "API": "#FDBA74",
    "RETRY": "#FBBF24",
    "MOCK": "#D8B4FE",
    "RESPONSE": "#86EFAC",
    "VALIDATE": "#F0ABFC",
    "EXCEL": "#93C5FD",
    "DONE": "#6EE7B7",
    "WARN": "#FCD34D",
    "ERROR": "#FDA4AF",
    "TRACE": "#64748B",
    "INFO": "#94A3B8",
}


class TerminalPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminalFrame")
        self.setStyleSheet(TERMINAL_STYLE)

        header = QFrame()
        header.setObjectName("terminalHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 12, 10)

        dots = QLabel("●  ●  ●")
        dots.setStyleSheet("color: #475569; letter-spacing: 2px;")
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("PROMPTCASE STUDIO / LIVE PIPELINE")
        title.setObjectName("terminalTitle")
        subtitle = QLabel("scan · context · prompt · response · document")
        subtitle.setObjectName("terminalSub")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status = QLabel("READY")
        self.status.setObjectName("terminalStatus")
        clear_button = QPushButton("CLEAR")
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
        self.output.document().setMaximumBlockCount(5000)
        self.output.setFont(QFont("Cascadia Mono", 10))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.output, 1)
        self.append_log("INFO", "Promptcase Studio terminal initialized")
        self.append_log("INFO", "외부 API 키는 로그에 표시하지 않습니다")

    def append_log(self, level: str, message: str) -> None:
        color = LOG_COLORS.get(level, "#CBD5E1")
        safe_message = html.escape(message).replace("\n", "<br>")
        self.output.append(
            f'<span style="color:#52657C">$</span> '
            f'<span style="color:{color};font-weight:700">[{html.escape(level)}]</span> '
            f'<span style="color:#C8D7E7">{safe_message}</span>'
        )
        self.output.moveCursor(QTextCursor.End)

    def append_chunk(self, chunk: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(f'<span style="color:#86EFAC">{html.escape(chunk)}</span>')
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def clear(self) -> None:
        self.output.clear()
        self.append_log("INFO", "터미널 로그를 지웠습니다")

    def set_running(self, running: bool) -> None:
        self.status.setText("RUNNING" if running else "READY")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings: dict[str, Any] = load_settings()
        self.worker: PipelineWorker | None = None
        self.last_result: PipelineResult | None = None
        self.current_run_succeeded = False
        self.setWindowTitle("Promptcase Studio")
        self.setWindowIcon(QIcon(str(PROJECT_ROOT / "favicon.ico")))
        self.resize(1500, 900)
        self.setMinimumSize(1180, 720)
        self._build_ui()
        self._apply_default_environment()

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
        splitter.setSizes([650, 850])
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        frame.setFixedHeight(68)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 10, 18, 10)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(44, 44)
        mark.setAlignment(Qt.AlignCenter)
        icon_pixmap = QIcon(str(PROJECT_ROOT / "favicon.ico")).pixmap(28, 28)
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
        self.header_environment.setStyleSheet(
            "background:#F1F5F9;color:#475569;border:1px solid #D8E0EA;border-radius:10px;padding:5px 10px;font-weight:700;"
        )
        settings_button = QPushButton("환경설정")
        settings_button.clicked.connect(self._open_settings)
        layout.addWidget(mark)
        layout.addSpacing(10)
        layout.addLayout(title_box)
        layout.addStretch(1)
        layout.addWidget(self.header_environment)
        layout.addWidget(settings_button)
        return frame

    def _build_control_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 14, 8, 16)
        layout.setSpacing(12)

        layout.addWidget(self._build_environment_card())
        layout.addWidget(self._build_project_card())
        layout.addWidget(self._build_change_card())
        layout.addWidget(self._build_request_card())

        self.run_button = QPushButton("분석 및 단위테스트 문서 생성")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._start_pipeline)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.open_output_button = QPushButton("마지막 생성 문서 열기")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_last_output)
        actions = QHBoxLayout()
        actions.addWidget(self.run_button, 1)
        actions.addWidget(self.open_output_button)
        layout.addLayout(actions)
        layout.addWidget(self.progress)
        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _card(self, title: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 15)
        layout.setSpacing(9)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        hint_label = QLabel(hint)
        hint_label.setObjectName("sectionHint")
        hint_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        return card, layout

    def _build_environment_card(self) -> QFrame:
        card, layout = self._card("01  실행 환경", "온라인은 Gemini, 중요단말망은 Qwen settings.json을 사용합니다.")
        self.online_radio = QRadioButton("온라인")
        self.secure_radio = QRadioButton("중요단말망")
        group = QButtonGroup(self)
        group.addButton(self.online_radio)
        group.addButton(self.secure_radio)
        self.online_radio.toggled.connect(self._update_environment_badge)
        row = QHBoxLayout()
        row.addWidget(self.online_radio)
        row.addSpacing(20)
        row.addWidget(self.secure_radio)
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _build_project_card(self) -> QFrame:
        card, layout = self._card("02  프로젝트 폴더", "전체 프로젝트 또는 분석에 필요한 핵심 폴더를 여러 개 추가할 수 있습니다.")
        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(78)
        add_button = QPushButton("폴더 추가")
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
        card, layout = self._card("03  변경 범위", "Git Diff, 수정 시작일, 수동 파일 목록을 함께 사용해 분석 대상을 확정합니다.")
        date_row = QHBoxLayout()
        self.date_checkbox = QCheckBox("수정일 이후 파일 포함")
        self.date_checkbox.setChecked(True)
        self.since_date = QDateEdit()
        self.since_date.setCalendarPopup(True)
        self.since_date.setDisplayFormat("yyyy-MM-dd")
        self.since_date.setDate(QDate.currentDate().addMonths(-1))
        self.git_checkbox = QCheckBox("Git 변경 자동 포함")
        self.git_checkbox.setChecked(True)
        date_row.addWidget(self.date_checkbox)
        date_row.addWidget(self.since_date)
        date_row.addSpacing(12)
        date_row.addWidget(self.git_checkbox)
        date_row.addStretch(1)
        self.manual_changes = QTextEdit()
        self.manual_changes.setMinimumHeight(112)
        self.manual_changes.setPlaceholderText(
            "예시\n변경: src/api/UserApi.java\n삭제: 사용자조회 API\nM VISS_D1300.tsx\n\n파일명만 입력해도 프로젝트 안에서 찾아봅니다."
        )
        diff_button = QPushButton("Git Diff 목록 불러오기")
        diff_button.clicked.connect(self._load_git_diff)
        clear_button = QPushButton("입력 지우기")
        clear_button.clicked.connect(self.manual_changes.clear)
        button_row = QHBoxLayout()
        button_row.addWidget(diff_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        layout.addLayout(date_row)
        layout.addWidget(self.manual_changes)
        layout.addLayout(button_row)
        return card

    def _build_request_card(self) -> QFrame:
        card, layout = self._card("04  변경 로직 · 의뢰서", "개발자가 작업한 내용이나 전달받은 의뢰서를 그대로 붙여넣으세요.")
        self.request_text = QTextEdit()
        self.request_text.setMinimumHeight(145)
        self.request_text.setPlaceholderText(
            "예시\n사용자조회 API 삭제함\n계약유지서비스 조회 기준 변경사항 반영\nVISS_D1300 툴팁 unit 계산식 보정"
        )
        layout.addWidget(self.request_text)
        return card

    def _apply_default_environment(self) -> None:
        default = self.settings.get("defaultEnvironment", "online")
        self.online_radio.setChecked(default != "secure")
        self.secure_radio.setChecked(default == "secure")
        self._update_environment_badge()

    def _update_environment_badge(self) -> None:
        environment = "온라인 · Gemini" if self.online_radio.isChecked() else "중요단말망 · Qwen"
        if self.settings.get("mockMode"):
            environment += " · MOCK"
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

    def _selected_since_date(self) -> date | None:
        if not self.date_checkbox.isChecked():
            return None
        value = self.since_date.date()
        return date(value.year(), value.month(), value.day())

    def _load_git_diff(self) -> None:
        roots = self._selected_roots()
        if not roots:
            QMessageBox.information(self, "Git Diff", "먼저 프로젝트 폴더를 추가해 주세요.")
            return
        records: list[str] = []
        for root in roots:
            changes = collect_git_changes(root, self._selected_since_date(), self.terminal.append_log)
            records.extend(f"{item.change_type}: {item.path}" for item in changes)
        if records:
            current = self.manual_changes.toPlainText().strip()
            combined = "\n".join(dict.fromkeys([*(current.splitlines() if current else []), *records]))
            self.manual_changes.setPlainText(combined)
            self.terminal.append_log("GIT", f"입력란에 Git 변경 {len(records)}개 반영")
        else:
            QMessageBox.information(self, "Git Diff", "불러올 Git 변경사항이 없습니다.")

    def _start_pipeline(self) -> None:
        roots = self._selected_roots()
        request_text = self.request_text.toPlainText().strip()
        if not roots:
            QMessageBox.warning(self, "입력 확인", "분석할 프로젝트 폴더를 한 개 이상 추가해 주세요.")
            return
        if not request_text:
            QMessageBox.warning(self, "입력 확인", "변경 로직 또는 의뢰서 내용을 입력해 주세요.")
            return
        request = AnalysisRequest(
            project_roots=roots,
            manual_changes=self.manual_changes.toPlainText(),
            request_text=request_text,
            environment="online" if self.online_radio.isChecked() else "secure",
            since_date=self._selected_since_date(),
            include_git=self.git_checkbox.isChecked(),
        )
        self.worker = PipelineWorker(request, self.settings)
        self.worker.log_message.connect(self.terminal.append_log)
        self.worker.response_chunk.connect(self.terminal.append_chunk)
        self.worker.completed.connect(self._pipeline_completed)
        self.worker.failed.connect(self._pipeline_failed)
        self.worker.finished.connect(self._worker_finished)
        self.current_run_succeeded = False
        self.run_button.setEnabled(False)
        self.open_output_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.terminal.set_running(True)
        self.terminal.append_log("START", "사용자 요청을 작업 큐에 등록")
        self.worker.start()

    def _pipeline_completed(self, result: PipelineResult) -> None:
        self.last_result = result
        self.current_run_succeeded = True
        self.open_output_button.setEnabled(True)
        QMessageBox.information(
            self,
            "문서 생성 완료",
            f"단위테스트 문서를 생성했습니다.\n\n{result.document_path}",
        )

    def _pipeline_failed(self, message: str) -> None:
        QMessageBox.critical(self, "작업 실패", message)

    def _worker_finished(self) -> None:
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if self.current_run_succeeded else 0)
        self.open_output_button.setEnabled(self.last_result is not None)
        self.terminal.set_running(False)
        self.worker = None

    def _open_last_output(self) -> None:
        if self.last_result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result.document_path)))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_():
            self.settings = load_settings()
            self._apply_default_environment()
            self.terminal.append_log("INFO", "환경설정을 다시 불러왔습니다")

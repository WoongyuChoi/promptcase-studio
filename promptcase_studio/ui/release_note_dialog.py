from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from promptcase_studio.ui.icons import interface_icon


class ReleaseNoteDialog(QDialog):
    """A disposable editor backed by the generated release-note original."""

    def __init__(self, subject: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("releaseNoteDialog")
        self.setWindowTitle("릴리즈 노트 뷰")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.resize(780, 640)
        self.setMinimumSize(680, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel("릴리즈 노트 메일")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "팀에 바로 공유할 수 있는 메일 문안입니다. 이 창에서 한 수정은 저장되지 않습니다."
        )
        subtitle.setObjectName("dialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        self.copy_button = QPushButton("복사")
        self.copy_button.setObjectName("releaseNoteCopyButton")
        self.copy_button.setIcon(interface_icon("copy", "#FFFFFF"))
        self.copy_button.setIconSize(QSize(15, 15))
        self.copy_button.setFixedSize(82, 32)
        self.copy_button.clicked.connect(self._copy_to_clipboard)
        header.addWidget(self.copy_button, 0, Qt.AlignTop)
        root.addLayout(header)

        editor = QWidget()
        editor.setObjectName("releaseNoteEditor")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(14, 14, 14, 14)
        editor_layout.setSpacing(7)

        subject_label = QLabel("메일 제목")
        subject_label.setObjectName("releaseNoteFieldLabel")
        self.subject_edit = QLineEdit(subject)
        self.subject_edit.setObjectName("releaseNoteSubject")
        self.subject_edit.setClearButtonEnabled(True)
        editor_layout.addWidget(subject_label)
        editor_layout.addWidget(self.subject_edit)
        editor_layout.addSpacing(5)

        body_label = QLabel("메일 본문")
        body_label.setObjectName("releaseNoteFieldLabel")
        self.body_edit = QTextEdit()
        self.body_edit.setObjectName("releaseNoteBody")
        self.body_edit.setAcceptRichText(False)
        self.body_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.body_edit.setPlainText(body)
        editor_layout.addWidget(body_label)
        editor_layout.addWidget(self.body_edit, 1)
        root.addWidget(editor, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.copy_status = QLabel("")
        self.copy_status.setObjectName("releaseNoteCopyStatus")
        footer.addWidget(self.copy_status)
        footer.addStretch(1)
        close_button = QPushButton("닫기")
        close_button.setObjectName("dialogSecondaryButton")
        close_button.setFixedSize(72, 32)
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def mail_text(self) -> str:
        subject = self.subject_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        return f"제목: {subject}\n\n{body}"

    def _copy_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self.mail_text())
        self.copy_status.setText("메일 문안을 복사했습니다.")


__all__ = ["ReleaseNoteDialog"]

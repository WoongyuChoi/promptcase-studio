from __future__ import annotations

from copy import deepcopy
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from promptcase_studio.config import (
    get_secret,
    resolve_project_path,
    save_dotenv_secret,
    save_local_settings,
)


class SettingsDialog(QDialog):
    def __init__(self, settings: dict[str, Any], parent=None):
        super().__init__(parent)
        self.settings = deepcopy(settings)
        self.setWindowTitle("Promptcase Studio 환경설정")
        self.resize(680, 460)
        self.setMinimumSize(620, 420)
        self.setModal(True)

        title = QLabel("연결 및 실행 설정")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("AI 제공자, 응답 대기 시간, 재시도 정책을 관리합니다.")
        subtitle.setObjectName("dialogSubtitle")

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "기본")
        tabs.addTab(self._build_online_tab(), "온라인 Gemini")
        tabs.addTab(self._build_secure_tab(), "중요단말망 Qwen")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(9)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(2)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 17, 18, 17)
        layout.setSpacing(10)

        label = QLabel("기본 AI 연결 환경")
        label.setObjectName("fieldLabel")
        self.online_radio = QRadioButton("온라인 Gemini")
        self.secure_radio = QRadioButton("중요단말망 Qwen")
        default_environment = self.settings.get("defaultEnvironment", "online")
        self.online_radio.setChecked(default_environment == "online")
        self.secure_radio.setChecked(default_environment == "secure")
        radio_row = QHBoxLayout()
        radio_row.addWidget(self.online_radio)
        radio_row.addWidget(self.secure_radio)
        radio_row.addStretch(1)

        self.mock_checkbox = QCheckBox("오프라인 Mock 모드")
        self.mock_checkbox.setChecked(bool(self.settings.get("mockMode", False)))
        mock_hint = QLabel("외부 API를 호출하지 않고 예제 응답으로 전체 흐름을 검증합니다.")
        mock_hint.setObjectName("sectionHint")
        self.quality_review_checkbox = QCheckBox("2차 품질 검토")
        self.quality_review_checkbox.setChecked(
            bool(self.settings.get("qualityReviewEnabled", True))
        )
        quality_hint = QLabel(
            "형식 검증을 통과한 초안을 다시 검토해 누락된 분기와 어색한 문장을 보완합니다."
        )
        quality_hint.setObjectName("sectionHint")
        validation_row = QHBoxLayout()
        validation_label = QLabel("응답 형식 검증")
        validation_label.setObjectName("fieldLabel")
        self.validation_attempts = QSpinBox()
        self.validation_attempts.setRange(1, 5)
        self.validation_attempts.setSuffix(" 회")
        self.validation_attempts.setValue(int(self.settings.get("responseValidationAttempts", 3)))
        validation_row.addWidget(validation_label)
        validation_row.addWidget(self.validation_attempts)
        validation_row.addStretch(1)
        validation_hint = QLabel("AI 응답이 문서 계약을 벗어나면 오류 내용을 반영해 다시 요청합니다.")
        validation_hint.setObjectName("sectionHint")

        layout.addWidget(label)
        layout.addLayout(radio_row)
        layout.addSpacing(5)
        layout.addWidget(self.mock_checkbox)
        layout.addWidget(mock_hint)
        layout.addSpacing(5)
        layout.addWidget(self.quality_review_checkbox)
        layout.addWidget(quality_hint)
        layout.addSpacing(5)
        layout.addLayout(validation_row)
        layout.addWidget(validation_hint)
        layout.addStretch(1)
        return widget

    def _build_online_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(18, 17, 18, 17)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        online = self.settings.get("providers", {}).get("online", {})
        self.gemini_base = QLineEdit(str(online.get("apiBase", "")))
        self.gemini_model = QLineEdit(str(online.get("model", "gemini-flash-latest")))
        self.gemini_key = QLineEdit(get_secret(str(online.get("apiKeyEnv", "GEMINI_API_KEY"))))
        self.gemini_key.setEchoMode(QLineEdit.Normal)
        self.gemini_key.setPlaceholderText("Google AI Studio에서 발급한 API 키")
        self.gemini_timeout = QSpinBox()
        self.gemini_timeout.setRange(30, 3600)
        self.gemini_timeout.setSuffix(" 초")
        self.gemini_timeout.setValue(int(online.get("timeoutSeconds", 300)))
        self.gemini_attempts = QSpinBox()
        self.gemini_attempts.setRange(1, 10)
        self.gemini_attempts.setSuffix(" 회")
        self.gemini_attempts.setValue(int(online.get("maxAttempts", 3)))
        self.gemini_output_tokens = QSpinBox()
        self.gemini_output_tokens.setRange(1024, 262144)
        self.gemini_output_tokens.setSingleStep(1024)
        self.gemini_output_tokens.setSuffix(" 토큰")
        self.gemini_output_tokens.setValue(int(online.get("maxOutputTokens", 32768)))
        form.addRow("API 주소", self.gemini_base)
        form.addRow("모델", self.gemini_model)
        form.addRow("API Key", self.gemini_key)
        form.addRow("응답 대기", self.gemini_timeout)
        form.addRow("최대 호출", self.gemini_attempts)
        form.addRow("최대 출력", self.gemini_output_tokens)
        hint = QLabel("API 키는 현재 PC의 .env에 저장되며 Git 커밋에서 자동 제외됩니다.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        form.addRow("", hint)
        return widget

    def _build_secure_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(18, 17, 18, 17)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        secure = self.settings.get("providers", {}).get("secure", {})
        self.qwen_settings_path = QLineEdit(str(secure.get("settingsPath", "")))
        self.qwen_timeout = QSpinBox()
        self.qwen_timeout.setRange(30, 3600)
        self.qwen_timeout.setSuffix(" 초")
        self.qwen_timeout.setValue(int(secure.get("timeoutSeconds", 300)))
        self.qwen_attempts = QSpinBox()
        self.qwen_attempts.setRange(1, 10)
        self.qwen_attempts.setSuffix(" 회")
        self.qwen_attempts.setValue(int(secure.get("maxAttempts", 3)))
        self.qwen_output_tokens = QSpinBox()
        self.qwen_output_tokens.setRange(1024, 262144)
        self.qwen_output_tokens.setSingleStep(1024)
        self.qwen_output_tokens.setSuffix(" 토큰")
        self.qwen_output_tokens.setValue(int(secure.get("maxOutputTokens", 32768)))
        browse = QPushButton("파일 선택")
        browse.clicked.connect(self._browse_qwen_settings)
        row = QHBoxLayout()
        row.addWidget(self.qwen_settings_path, 1)
        row.addWidget(browse)
        form.addRow("settings.json", row)
        form.addRow("응답 대기", self.qwen_timeout)
        form.addRow("최대 호출", self.qwen_attempts)
        form.addRow("최대 출력", self.qwen_output_tokens)
        hint = QLabel("Qwen settings.json에서 provider, 모델, 환경 변수와 생성 설정을 읽습니다.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        form.addRow("", hint)
        return widget

    def _browse_qwen_settings(self) -> None:
        current = self.qwen_settings_path.text().strip()
        selected_path = resolve_project_path(current or "config/qwen.settings.json")
        initial = str(selected_path.parent)
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Qwen 설정 파일 선택",
            initial,
            "JSON Files (*.json);;All Files (*)",
        )
        if file_name:
            self.qwen_settings_path.setText(file_name)

    def _save(self) -> None:
        # Keep the machine-local override intentionally sparse. Persisting the
        # fully merged settings snapshot would pin scanner and provider defaults
        # from an older EXE, preventing future bundled policy updates from taking
        # effect after a user merely opened and saved this dialog.
        local_overrides = {
            "defaultEnvironment": "online" if self.online_radio.isChecked() else "secure",
            "mockMode": self.mock_checkbox.isChecked(),
            "qualityReviewEnabled": self.quality_review_checkbox.isChecked(),
            "responseValidationAttempts": self.validation_attempts.value(),
            "providers": {
                "online": {
                    "apiBase": self.gemini_base.text().strip(),
                    "model": self.gemini_model.text().strip(),
                    "apiKeyEnv": "GEMINI_API_KEY",
                    "timeoutSeconds": self.gemini_timeout.value(),
                    "maxAttempts": self.gemini_attempts.value(),
                    "maxOutputTokens": self.gemini_output_tokens.value(),
                },
                "secure": {
                    "settingsPath": self.qwen_settings_path.text().strip(),
                    "timeoutSeconds": self.qwen_timeout.value(),
                    "maxAttempts": self.qwen_attempts.value(),
                    "maxOutputTokens": self.qwen_output_tokens.value(),
                },
            },
        }
        save_dotenv_secret("GEMINI_API_KEY", self.gemini_key.text().strip())
        save_local_settings(local_overrides)
        self.accept()

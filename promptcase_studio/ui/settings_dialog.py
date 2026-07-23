from __future__ import annotations

from copy import deepcopy
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from promptcase_studio.config import (
    get_secret,
    resolve_project_path,
    save_dotenv_secret,
    save_local_settings,
)
from promptcase_studio.gemini_models import (
    AUTO_GEMINI_MODEL,
    DEFAULT_GEMINI_FALLBACK_MODELS,
    GEMINI_TEXT_MODELS,
    gemini_model_sequence,
    normalize_gemini_model_id,
)


class StepperSpinBox(QSpinBox):
    """Compact spin box with reliable text controls at every DPI scale."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stepperSpinBox")
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setMinimumWidth(96)
        self.setMaximumWidth(180)
        self.setFixedHeight(32)
        self._increase = QToolButton(self)
        self._increase.setObjectName("spinIncreaseButton")
        self._increase.setText("+")
        self._increase.setAccessibleName("값 증가")
        self._increase.setFocusPolicy(Qt.NoFocus)
        self._increase.setAutoRepeat(True)
        self._increase.setAutoRepeatDelay(350)
        self._increase.setAutoRepeatInterval(80)
        self._increase.clicked.connect(self.stepUp)
        self._decrease = QToolButton(self)
        self._decrease.setObjectName("spinDecreaseButton")
        self._decrease.setText("-")
        self._decrease.setAccessibleName("값 감소")
        self._decrease.setFocusPolicy(Qt.NoFocus)
        self._decrease.setAutoRepeat(True)
        self._decrease.setAutoRepeatDelay(350)
        self._decrease.setAutoRepeatInterval(80)
        self._decrease.clicked.connect(self.stepDown)
        self.valueChanged.connect(self._sync_button_state)
        self._sync_button_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        button_width = 26
        button_height = max(20, self.height() - 2)
        increase_left = self.width() - button_width - 1
        decrease_left = increase_left - button_width
        self._decrease.setGeometry(decrease_left, 1, button_width, button_height)
        self._increase.setGeometry(increase_left, 1, button_width, button_height)

    def _sync_button_state(self) -> None:
        self._decrease.setEnabled(self.value() > self.minimum())
        self._increase.setEnabled(self.value() < self.maximum())


class SettingsDialog(QDialog):
    def __init__(self, settings: dict[str, Any], parent=None):
        super().__init__(parent)
        self.settings = deepcopy(settings)
        self.setWindowTitle("Promptcase Studio 환경설정")
        self.resize(800, 580)
        self.setMinimumSize(720, 540)
        self.setModal(True)

        title = QLabel("연결 및 실행 설정")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("AI 연결, 응답 제한과 문서 품질 정책을 관리합니다.")
        subtitle.setObjectName("dialogSubtitle")

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "기본")
        tabs.addTab(self._build_secure_tab(), "폐쇄망(Qwen)")
        tabs.addTab(self._build_online_tab(), "온라인(Gemini)")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(2)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(9)

        label = QLabel("기본 연결 환경")
        label.setObjectName("fieldLabel")
        self.secure_radio = QRadioButton("폐쇄망(Qwen)")
        self.online_radio = QRadioButton("온라인(Gemini)")
        default_environment = self.settings.get("defaultEnvironment", "secure")
        self.online_radio.setChecked(default_environment == "online")
        self.secure_radio.setChecked(default_environment == "secure")
        radio_row = QHBoxLayout()
        radio_row.addWidget(self.secure_radio)
        radio_row.addWidget(self.online_radio)
        radio_row.addStretch(1)

        self.mock_checkbox = QCheckBox("Mock 모드")
        self.mock_checkbox.setChecked(bool(self.settings.get("mockMode", False)))
        mock_hint = QLabel("외부 API 없이 예제 응답으로 실행 흐름을 확인합니다")
        mock_hint.setObjectName("sectionHint")
        mock_row = QHBoxLayout()
        mock_row.addWidget(self.mock_checkbox)
        mock_row.addWidget(mock_hint)
        mock_row.addStretch(1)
        quality_section = QLabel("문서 품질")
        quality_section.setObjectName("settingsGroupTitle")
        self.quality_review_checkbox = QCheckBox("AI 품질 검토")
        self.quality_review_checkbox.setChecked(
            bool(self.settings.get("qualityReviewEnabled", True))
        )
        quality_hint = QLabel("초안의 누락된 분기와 어색한 문장을 다시 검토합니다")
        quality_hint.setObjectName("sectionHint")
        quality_toggle_row = QHBoxLayout()
        quality_toggle_row.addWidget(self.quality_review_checkbox)
        quality_toggle_row.addWidget(quality_hint)
        quality_toggle_row.addStretch(1)
        quality_count_row = QHBoxLayout()
        quality_count_label = QLabel("품질 검토 횟수")
        quality_count_label.setObjectName("fieldLabel")
        self.quality_review_passes = StepperSpinBox()
        self.quality_review_passes.setRange(1, 3)
        self.quality_review_passes.setSuffix(" 회")
        self.quality_review_passes.setValue(int(self.settings.get("qualityReviewPasses", 2)))
        review_validation_label = QLabel("검토 응답 시도")
        review_validation_label.setObjectName("fieldLabel")
        self.quality_review_validation_attempts = StepperSpinBox()
        self.quality_review_validation_attempts.setRange(1, 3)
        self.quality_review_validation_attempts.setSuffix(" 회")
        self.quality_review_validation_attempts.setValue(
            int(self.settings.get("qualityReviewValidationAttempts", 2))
        )
        quality_count_row.addWidget(quality_count_label)
        quality_count_row.addWidget(self.quality_review_passes)
        quality_count_row.addSpacing(14)
        quality_count_row.addWidget(review_validation_label)
        quality_count_row.addWidget(self.quality_review_validation_attempts)
        quality_count_row.addStretch(1)
        self.quality_request_hint = QLabel()
        self.quality_request_hint.setObjectName("sectionHint")
        self.quality_review_passes.valueChanged.connect(self._update_quality_request_hint)
        self.quality_review_validation_attempts.valueChanged.connect(
            self._update_quality_request_hint
        )
        self._update_quality_request_hint()
        quality_gate_row = QHBoxLayout()
        quality_gate_label = QLabel("완료 정책")
        quality_gate_label.setObjectName("fieldLabel")
        self.quality_gate_mode = QComboBox()
        self.quality_gate_mode.addItem("최선본 다운로드 허용", "best_effort")
        self.quality_gate_mode.addItem("필수 품질 문제 시 다운로드 차단", "strict")
        self.quality_gate_mode.setMaximumWidth(420)
        gate_index = self.quality_gate_mode.findData(
            str(self.settings.get("qualityGateMode", "best_effort"))
        )
        self.quality_gate_mode.setCurrentIndex(max(0, gate_index))
        quality_gate_row.addWidget(quality_gate_label)
        quality_gate_row.addWidget(self.quality_gate_mode, 1)
        validation_row = QHBoxLayout()
        validation_label = QLabel("응답 형식 검증")
        validation_label.setObjectName("fieldLabel")
        self.validation_attempts = StepperSpinBox()
        self.validation_attempts.setRange(1, 5)
        self.validation_attempts.setSuffix(" 회")
        self.validation_attempts.setValue(int(self.settings.get("responseValidationAttempts", 3)))
        validation_row.addWidget(validation_label)
        validation_row.addWidget(self.validation_attempts)
        validation_note = QLabel("계약 오류가 있으면 수정 요청")
        validation_note.setObjectName("sectionHint")
        validation_row.addWidget(validation_note)
        validation_row.addStretch(1)

        layout.addWidget(label)
        layout.addLayout(radio_row)
        layout.addLayout(mock_row)
        layout.addSpacing(3)
        layout.addWidget(quality_section)
        layout.addLayout(quality_toggle_row)
        layout.addLayout(quality_count_row)
        layout.addWidget(self.quality_request_hint)
        layout.addLayout(quality_gate_row)
        layout.addLayout(validation_row)
        layout.addStretch(1)
        return widget

    def _update_quality_request_hint(self) -> None:
        maximum = (
            self.quality_review_passes.value()
            * self.quality_review_validation_attempts.value()
        )
        self.quality_request_hint.setText(
            f"품질 검토 단계에서 최대 {maximum}회의 AI 응답 생성을 시도합니다."
        )

    def _build_online_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(20, 18, 20, 18)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        online = self.settings.get("providers", {}).get("online", {})
        self.gemini_base = QLineEdit(str(online.get("apiBase", "")))
        self.gemini_model = QComboBox()
        self.gemini_model.addItem("Auto", AUTO_GEMINI_MODEL)
        for model in GEMINI_TEXT_MODELS:
            self.gemini_model.addItem(model.choice_label, model.model_id)
        selected_model = normalize_gemini_model_id(online.get("model", AUTO_GEMINI_MODEL))
        selected_index = self.gemini_model.findData(selected_model)
        if selected_index < 0:
            self.gemini_model.addItem(selected_model, selected_model)
            selected_index = self.gemini_model.count() - 1
        self.gemini_model.setCurrentIndex(selected_index)
        self.gemini_fallback_models = tuple(
            gemini_model_sequence(
                AUTO_GEMINI_MODEL,
                online.get("fallbackModels", DEFAULT_GEMINI_FALLBACK_MODELS),
            )[1:]
        )
        self.gemini_fallback_hint = QLabel()
        self.gemini_fallback_hint.setWordWrap(True)
        self.gemini_fallback_hint.setObjectName("sectionHint")
        self.gemini_model.currentIndexChanged.connect(self._update_gemini_fallback_hint)
        self._update_gemini_fallback_hint()
        self.gemini_key = QLineEdit(get_secret(str(online.get("apiKeyEnv", "GEMINI_API_KEY"))))
        self.gemini_key.setEchoMode(QLineEdit.Normal)
        self.gemini_key.setPlaceholderText("Google AI Studio에서 발급한 API 키")
        self.gemini_timeout = StepperSpinBox()
        self.gemini_timeout.setRange(30, 3600)
        self.gemini_timeout.setSuffix(" 초")
        self.gemini_timeout.setValue(int(online.get("timeoutSeconds", 300)))
        self.gemini_attempts = StepperSpinBox()
        self.gemini_attempts.setRange(1, 10)
        self.gemini_attempts.setSuffix(" 회")
        self.gemini_attempts.setValue(int(online.get("maxAttempts", 3)))
        self.gemini_output_tokens = StepperSpinBox()
        self.gemini_output_tokens.setRange(1024, 262144)
        self.gemini_output_tokens.setSingleStep(1024)
        self.gemini_output_tokens.setSuffix(" 토큰")
        self.gemini_output_tokens.setValue(int(online.get("maxOutputTokens", 32768)))
        form.addRow("API 주소", self.gemini_base)
        form.addRow("Gemini 모델", self.gemini_model)
        form.addRow("", self.gemini_fallback_hint)
        form.addRow("API Key", self.gemini_key)
        form.addRow("응답 제한 시간", self.gemini_timeout)
        form.addRow("요청 시도 횟수", self.gemini_attempts)
        form.addRow("최대 응답 토큰", self.gemini_output_tokens)
        hint = QLabel("API 키는 현재 PC의 .env에 저장되며 Git 커밋에서 자동 제외됩니다.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        form.addRow("", hint)
        return widget

    def _selected_gemini_model(self) -> str:
        return normalize_gemini_model_id(self.gemini_model.currentData())

    def _update_gemini_fallback_hint(self) -> None:
        primary = self._selected_gemini_model()
        if primary == AUTO_GEMINI_MODEL:
            sequence = "  →  ".join(
                gemini_model_sequence(primary, self.gemini_fallback_models)
            )
            message = (
                f"자동 전환 순서  {sequence}\n"
                "모델별 요청 한도가 재시도 후에도 지속되면 다음 모델로 전환합니다."
            )
        else:
            message = f"{primary} 모델만 고정 사용하며 다른 모델로 자동 전환하지 않습니다."
        self.gemini_fallback_hint.setText(
            message + " 무료 한도는 Google AI Studio에서 확인합니다."
        )

    def _build_secure_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(20, 18, 20, 18)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        secure = self.settings.get("providers", {}).get("secure", {})
        self.qwen_settings_path = QLineEdit(str(secure.get("settingsPath", "")))
        self.qwen_timeout = StepperSpinBox()
        self.qwen_timeout.setRange(30, 3600)
        self.qwen_timeout.setSuffix(" 초")
        self.qwen_timeout.setValue(int(secure.get("timeoutSeconds", 300)))
        self.qwen_attempts = StepperSpinBox()
        self.qwen_attempts.setRange(1, 10)
        self.qwen_attempts.setSuffix(" 회")
        self.qwen_attempts.setValue(int(secure.get("maxAttempts", 3)))
        self.qwen_output_tokens = StepperSpinBox()
        self.qwen_output_tokens.setRange(1024, 262144)
        self.qwen_output_tokens.setSingleStep(1024)
        self.qwen_output_tokens.setSuffix(" 토큰")
        self.qwen_output_tokens.setValue(int(secure.get("maxOutputTokens", 32768)))
        browse = QPushButton("파일 선택")
        browse.clicked.connect(self._browse_qwen_settings)
        row = QHBoxLayout()
        row.addWidget(self.qwen_settings_path, 1)
        row.addWidget(browse)
        form.addRow("Qwen 설정 파일", row)
        form.addRow("응답 제한 시간", self.qwen_timeout)
        form.addRow("요청 시도 횟수", self.qwen_attempts)
        form.addRow("최대 응답 토큰", self.qwen_output_tokens)
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
            "qualityReviewPasses": self.quality_review_passes.value(),
            "qualityReviewValidationAttempts": self.quality_review_validation_attempts.value(),
            "qualityGateMode": str(self.quality_gate_mode.currentData()),
            "responseValidationAttempts": self.validation_attempts.value(),
            "providers": {
                "online": {
                    "apiBase": self.gemini_base.text().strip(),
                    "model": self._selected_gemini_model(),
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

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
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

from promptcase_studio.config import get_secret, save_dotenv_secret, save_local_settings


class SettingsDialog(QDialog):
    def __init__(self, settings: dict[str, Any], parent=None):
        super().__init__(parent)
        self.settings = deepcopy(settings)
        self.setWindowTitle("Promptcase Studio 환경설정")
        self.resize(720, 510)
        self.setModal(True)

        title = QLabel("환경설정")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #101828;")
        subtitle = QLabel("실행 환경과 provider 연결 정보를 관리합니다. 실제 API 키는 .env에만 저장됩니다.")
        subtitle.setStyleSheet("color: #7B8798;")

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "일반")
        tabs.addTab(self._build_online_tab(), "온라인 · Gemini")
        tabs.addTab(self._build_secure_tab(), "중요단말망 · Qwen")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(4)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(15)

        label = QLabel("기본 실행 환경")
        label.setObjectName("fieldLabel")
        self.online_radio = QRadioButton("온라인 · Gemini")
        self.secure_radio = QRadioButton("중요단말망 · Qwen")
        default_environment = self.settings.get("defaultEnvironment", "online")
        self.online_radio.setChecked(default_environment == "online")
        self.secure_radio.setChecked(default_environment == "secure")
        radio_row = QHBoxLayout()
        radio_row.addWidget(self.online_radio)
        radio_row.addWidget(self.secure_radio)
        radio_row.addStretch(1)

        self.mock_checkbox = QCheckBox("오프라인 Mock provider 사용")
        self.mock_checkbox.setChecked(bool(self.settings.get("mockMode", False)))
        mock_hint = QLabel("개발 및 자동 테스트용입니다. 활성화하면 외부 API를 호출하지 않습니다.")
        mock_hint.setObjectName("sectionHint")

        layout.addWidget(label)
        layout.addLayout(radio_row)
        layout.addSpacing(8)
        layout.addWidget(self.mock_checkbox)
        layout.addWidget(mock_hint)
        layout.addStretch(1)
        return widget

    def _build_online_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(22, 22, 22, 22)
        form.setSpacing(14)
        online = self.settings.get("providers", {}).get("online", {})
        self.gemini_base = QLineEdit(str(online.get("apiBase", "")))
        self.gemini_model = QLineEdit(str(online.get("model", "gemini-flash-latest")))
        self.gemini_key = QLineEdit(get_secret(str(online.get("apiKeyEnv", "GEMINI_API_KEY"))))
        self.gemini_key.setEchoMode(QLineEdit.Password)
        self.gemini_key.setPlaceholderText("새로 발급한 Gemini API 키")
        self.gemini_timeout = QSpinBox()
        self.gemini_timeout.setRange(30, 3600)
        self.gemini_timeout.setSuffix(" 초")
        self.gemini_timeout.setValue(int(online.get("timeoutSeconds", 300)))
        self.gemini_attempts = QSpinBox()
        self.gemini_attempts.setRange(1, 10)
        self.gemini_attempts.setSuffix(" 회")
        self.gemini_attempts.setValue(int(online.get("maxAttempts", 3)))
        form.addRow("API Base", self.gemini_base)
        form.addRow("Model", self.gemini_model)
        form.addRow("API Key", self.gemini_key)
        form.addRow("응답 제한시간", self.gemini_timeout)
        form.addRow("최대 시도", self.gemini_attempts)
        hint = QLabel("키는 config JSON이 아니라 Git에서 제외된 .env의 GEMINI_API_KEY로 저장됩니다.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        form.addRow("", hint)
        return widget

    def _build_secure_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(22, 22, 22, 22)
        form.setSpacing(14)
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
        browse = QPushButton("찾아보기")
        browse.clicked.connect(self._browse_qwen_settings)
        row = QHBoxLayout()
        row.addWidget(self.qwen_settings_path, 1)
        row.addWidget(browse)
        form.addRow("settings.json", row)
        form.addRow("응답 제한시간", self.qwen_timeout)
        form.addRow("최대 시도", self.qwen_attempts)
        hint = QLabel("Qwen Code의 modelProviders, model, envKey와 generationConfig를 읽습니다.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        form.addRow("", hint)
        return widget

    def _browse_qwen_settings(self) -> None:
        current = self.qwen_settings_path.text().strip()
        initial = str(Path(current).parent) if current and "%" not in current else ""
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Qwen settings.json 선택",
            initial,
            "JSON Files (*.json);;All Files (*)",
        )
        if file_name:
            self.qwen_settings_path.setText(file_name)

    def _save(self) -> None:
        self.settings["defaultEnvironment"] = "online" if self.online_radio.isChecked() else "secure"
        self.settings["mockMode"] = self.mock_checkbox.isChecked()
        self.settings.setdefault("providers", {}).setdefault("online", {})["apiBase"] = self.gemini_base.text().strip()
        self.settings["providers"]["online"]["model"] = self.gemini_model.text().strip()
        self.settings["providers"]["online"]["apiKeyEnv"] = "GEMINI_API_KEY"
        self.settings["providers"]["online"]["timeoutSeconds"] = self.gemini_timeout.value()
        self.settings["providers"]["online"]["maxAttempts"] = self.gemini_attempts.value()
        self.settings.setdefault("providers", {}).setdefault("secure", {})["settingsPath"] = self.qwen_settings_path.text().strip()
        self.settings["providers"]["secure"]["timeoutSeconds"] = self.qwen_timeout.value()
        self.settings["providers"]["secure"]["maxAttempts"] = self.qwen_attempts.value()
        save_dotenv_secret("GEMINI_API_KEY", self.gemini_key.text().strip())
        save_local_settings(self.settings)
        self.accept()

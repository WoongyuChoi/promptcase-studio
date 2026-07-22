APP_STYLESHEET = r"""
QMainWindow, QDialog {
    background: #EEF2F8;
    color: #172033;
    font-family: "Pretendard", "맑은 고딕", "Segoe UI";
    font-size: 13px;
}
QWidget#appRoot { background: #EEF2F8; }
QFrame#topBar {
    background: #FFFFFF;
    border-bottom: 1px solid #DDE5EF;
}
QLabel#brandMark {
    background: #EAF0F8;
    color: #23367F;
    border: 1px solid #D7E0EC;
    border-radius: 9px;
    font-size: 15px;
    font-weight: 800;
}
QLabel#brandTitle { color: #101828; font-size: 18px; font-weight: 800; }
QLabel#brandSub { color: #7B8798; font-size: 11px; }
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #DFE7F0;
    border-radius: 12px;
}
QLabel#sectionTitle { color: #162033; font-size: 14px; font-weight: 750; }
QLabel#sectionHint { color: #8792A4; font-size: 11px; }
QLabel#fieldLabel { color: #49566A; font-size: 12px; font-weight: 650; }
QLineEdit, QDateEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {
    background: #FFFFFF;
    border: 1px solid #D8E0EA;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: #D7F4DC;
    selection-color: #142018;
}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QListWidget:focus {
    border: 2px solid #08A51F;
    padding: 6px 9px;
}
QLineEdit:disabled, QTextEdit:disabled { background: #F3F5F8; color: #9BA5B3; }
QListWidget { padding: 4px; }
QListWidget::item { padding: 7px; border-radius: 6px; }
QListWidget::item:selected { background: #E5F7E8; color: #126B20; }
QPushButton {
    min-height: 34px;
    padding: 0 13px;
    border: 1px solid #CFD9E6;
    border-radius: 8px;
    background: #FFFFFF;
    color: #344054;
    font-weight: 650;
}
QPushButton:hover { background: #F6F9FC; border-color: #B8C6D8; }
QPushButton:pressed { background: #EDF2F7; }
QPushButton:disabled { background: #EFF2F5; color: #A1AAB6; border-color: #E1E6EC; }
QPushButton#primaryButton {
    min-height: 44px;
    background: #23367F;
    color: #FFFFFF;
    border: 1px solid #23367F;
    font-size: 14px;
    font-weight: 750;
}
QPushButton#primaryButton:hover { background: #2D469B; }
QPushButton#greenButton { background: #08A51F; color: #FFFFFF; border-color: #08A51F; }
QPushButton#greenButton:hover { background: #07901B; }
QRadioButton, QCheckBox { color: #344054; spacing: 7px; }
QRadioButton::indicator, QCheckBox::indicator { width: 17px; height: 17px; }
QRadioButton::indicator:checked { image: none; border: 5px solid #08A51F; border-radius: 9px; background: #FFFFFF; }
QRadioButton::indicator:unchecked { border: 1px solid #BFC9D6; border-radius: 9px; background: #FFFFFF; }
QCheckBox::indicator:checked { image: none; background: #08A51F; border: 1px solid #08A51F; border-radius: 4px; }
QCheckBox::indicator:unchecked { border: 1px solid #BFC9D6; border-radius: 4px; background: #FFFFFF; }
QSplitter::handle { background: transparent; width: 8px; }
QProgressBar {
    height: 7px;
    border: 0;
    border-radius: 3px;
    background: #DDE5EE;
    text-align: center;
}
QProgressBar::chunk { background: #08A51F; border-radius: 3px; }
QTabWidget::pane { border: 1px solid #DFE7F0; background: #FFFFFF; border-radius: 8px; }
QTabBar::tab { background: #E9EEF5; color: #667085; padding: 9px 16px; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #FFFFFF; color: #172033; font-weight: 700; }
"""


TERMINAL_STYLE = r"""
QFrame#terminalFrame {
    background: #0B1120;
    border: 1px solid #1D2A3D;
    border-radius: 14px;
}
QFrame#terminalHeader {
    background: #101827;
    border-bottom: 1px solid #1E2B40;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}
QLabel#terminalTitle { color: #D8E4F2; font-size: 12px; font-weight: 750; }
QLabel#terminalSub { color: #64748B; font-size: 10px; }
QLabel#terminalStatus {
    background: #132A20;
    border: 1px solid #245C3C;
    border-radius: 9px;
    color: #8DF0A5;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
}
QTextEdit#terminalOutput {
    background: #0B1120;
    color: #C8D7E7;
    border: 0;
    padding: 14px 16px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: #26476A;
}
QPushButton#terminalButton {
    min-height: 26px;
    padding: 0 9px;
    border: 1px solid #27364C;
    background: #162033;
    color: #8FA3BA;
    font-size: 10px;
}
QPushButton#terminalButton:hover { background: #1B2A40; color: #D6E1ED; }
"""

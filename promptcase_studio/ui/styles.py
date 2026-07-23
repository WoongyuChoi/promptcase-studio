APP_STYLESHEET = r"""
QMainWindow, QDialog {
    background: #EEF2F8;
    color: #172033;
    font-family: "Pretendard", "맑은 고딕", "Segoe UI";
    font-size: 12px;
}
QWidget#appRoot { background: #EEF2F8; }
QWidget#controlPanel { background: #EEF2F8; }
QFrame#topBar {
    background: #FFFFFF;
    border-bottom: 1px solid #DDE5EF;
}
QLabel#brandMark {
    background: #EAF0F8;
    color: #23367F;
    border: 1px solid #D7E0EC;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 800;
}
QLabel#brandTitle { color: #101828; font-size: 16px; font-weight: 800; }
QLabel#brandSub { color: #7B8798; font-size: 9px; }
QLabel#dialogTitle { color: #101828; font-size: 17px; font-weight: 800; }
QLabel#dialogSubtitle { color: #7B8798; font-size: 11px; }
QLabel#environmentBadge {
    min-width: 112px;
    padding: 0 10px;
    background: #EFF6F0;
    color: #176425;
    border: 1px solid #C9E6CE;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 700;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #DFE7F0;
    border-radius: 10px;
}
QLabel#sectionTitle { color: #162033; font-size: 13px; font-weight: 750; }
QLabel#sectionHint { color: #7D899B; font-size: 10px; }
QLabel#fieldLabel { color: #49566A; font-size: 11px; font-weight: 650; }
QLabel#dateRangeLabel { color: #667085; font-size: 10px; font-weight: 650; }
QLineEdit, QDateEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {
    background: #FFFFFF;
    border: 1px solid #D8E0EA;
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: #D7F4DC;
    selection-color: #142018;
}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QListWidget:focus {
    border: 1px solid #08A51F;
}
QLineEdit:disabled, QTextEdit:disabled { background: #F3F5F8; color: #9BA5B3; }
QDateEdit#rangeDate { min-width: 90px; max-width: 100px; padding-left: 6px; padding-right: 4px; }
QDateEdit#rangeDate:disabled { background: #F3F5F8; color: #9BA5B3; }
QListWidget { padding: 3px; }
QListWidget::item { padding: 5px 6px; border-radius: 5px; }
QListWidget::item:selected { background: #E5F7E8; color: #126B20; }
QPushButton {
    min-height: 30px;
    padding: 0 11px;
    border: 1px solid #CFD9E6;
    border-radius: 7px;
    background: #FFFFFF;
    color: #344054;
    font-weight: 650;
}
QPushButton:hover { background: #F6F9FC; border-color: #B8C6D8; }
QPushButton:pressed { background: #EDF2F7; }
QPushButton:disabled { background: #EFF2F5; color: #A1AAB6; border-color: #E1E6EC; }
QPushButton#topActionButton {
    min-height: 30px;
    padding: 0 12px;
    background: #FFFFFF;
    border-color: #D6DFEA;
    font-size: 11px;
}
QPushButton#primaryButton {
    min-height: 38px;
    background: #23367F;
    color: #FFFFFF;
    border: 1px solid #23367F;
    font-size: 13px;
    font-weight: 750;
}
QPushButton#primaryButton:hover { background: #2D469B; }
QPushButton#greenButton { background: #08A51F; color: #FFFFFF; border-color: #08A51F; }
QPushButton#greenButton:hover { background: #07901B; }
QRadioButton, QCheckBox { color: #344054; spacing: 6px; }
QRadioButton:checked, QCheckBox:checked { color: #176425; font-weight: 650; }
QSplitter::handle { background: transparent; width: 8px; }
QProgressBar {
    height: 5px;
    border: 0;
    border-radius: 2px;
    background: #DDE5EE;
    text-align: center;
}
QProgressBar::chunk { background: #08A51F; border-radius: 2px; }
QTabWidget::pane { border: 1px solid #DFE7F0; background: #FFFFFF; border-radius: 7px; }
QTabBar::tab { background: #E9EEF5; color: #667085; padding: 7px 14px; margin-right: 3px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #FFFFFF; color: #172033; font-weight: 700; }
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical {
    width: 8px;
    margin: 2px 0;
    border: 0;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 30px;
    background: #C9D4E1;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: #AEBCCC; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


TERMINAL_STYLE = r"""
QFrame#terminalFrame {
    background: #0B1120;
    border: 1px solid #1D2A3D;
    border-radius: 12px;
}
QFrame#terminalHeader {
    background: #101827;
    border-bottom: 1px solid #1E2B40;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}
QLabel#terminalDots { color: #475569; font-size: 9px; }
QLabel#terminalTitle { color: #D8E4F2; font-size: 11px; font-weight: 750; }
QLabel#terminalSub { color: #64748B; font-size: 8px; }
QLabel#terminalStatus {
    background: #132A20;
    border: 1px solid #245C3C;
    border-radius: 8px;
    color: #8DF0A5;
    padding: 2px 7px;
    font-size: 9px;
    font-weight: 700;
}
QTextEdit#terminalOutput {
    background: #0B1120;
    color: #C8D7E7;
    border: 0;
    padding: 11px 13px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
    selection-background-color: #26476A;
}
QPushButton#terminalButton {
    min-height: 24px;
    padding: 0 8px;
    border: 1px solid #27364C;
    background: #162033;
    color: #8FA3BA;
    font-size: 9px;
}
QPushButton#terminalButton:hover { background: #1B2A40; color: #D6E1ED; }
"""

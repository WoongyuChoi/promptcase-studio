APP_STYLESHEET = r"""
QMainWindow, QDialog {
    background: #EEF2F8;
    color: #172033;
    font-family: "Pretendard", "맑은 고딕", "Segoe UI";
    font-size: 14px;
}
QDialog { font-size: 13px; }
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
    border-radius: 7px;
    font-size: 16px;
    font-weight: 800;
}
QLabel#brandTitle { color: #101828; font-size: 18px; font-weight: 800; }
QLabel#brandSub { color: #7B8798; font-size: 12px; }
QLabel#dialogTitle { color: #101828; font-size: 18px; font-weight: 800; }
QLabel#dialogSubtitle { color: #7B8798; font-size: 12px; }
QWidget#settingsPage { background: transparent; }
QFrame#settingsSection {
    background: #F8FAFC;
    border: 1px solid #DFE7F0;
    border-radius: 10px;
}
QFrame#settingsInfoSection {
    background: #F2F6FB;
    border: 1px solid #D8E2EE;
    border-radius: 10px;
}
QLabel#settingsSectionTitle {
    color: #26354B;
    font-size: 14px;
    font-weight: 750;
}
QLabel#settingsInfoText {
    color: #66758A;
    font-size: 13px;
}
QWidget#settingsInlineRow { background: transparent; }
QLabel#environmentBadge {
    min-width: 108px;
    padding: 0 10px;
    background: #EFF6F0;
    color: #176425;
    border: 1px solid #C9E6CE;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #DFE7F0;
    border-radius: 10px;
}
QLabel#sectionTitle { color: #162033; font-size: 13px; font-weight: 750; }
QLabel#sectionHint { color: #7D899B; font-size: 13px; }
QLabel#fieldLabel { color: #49566A; font-size: 14px; font-weight: 650; }
QLabel#settingsFieldLabel {
    color: #344054;
    font-size: 12px;
    font-weight: 400;
}
QLabel#settingsGroupTitle { color: #26354B; font-size: 14px; font-weight: 750; }
QLabel#dateRangeLabel { color: #667085; font-size: 12px; font-weight: 650; }
QToolButton#helpBadge {
    color: #718096;
    background: #F4F7FA;
    border: 1px solid #CDD7E3;
    border-radius: 6px;
    font-size: 8px;
    font-weight: 800;
    padding: 0;
}
QToolButton#helpBadge:hover { color: #23367F; background: #E9EEF8; border-color: #AAB8CA; }
QToolButton#helpBadge:focus { border-color: #7386A4; background: #EEF3F9; }
QFrame#tooltipCard {
    background-color: #FFFFFF;
    border: 1px solid #1F2937;
    border-radius: 10px;
}
QWidget#tooltipSeam {
    background-color: #FFFFFF;
    border: 0;
}
QLabel#tooltipTitle {
    background: transparent;
    color: #111111;
    font-size: 14px;
    font-weight: 700;
}
QLabel#tooltipBody {
    background: transparent;
    color: #666666;
    font-size: 12px;
    font-weight: 600;
}
QLabel#progressLabel {
    color: #7B8798;
    font-size: 10px;
    font-weight: 700;
}
QFrame#progressCluster {
    background: #F7F9FC;
    border: 1px solid #DFE7F0;
    border-radius: 8px;
}
QWidget#controlPanel QRadioButton,
QWidget#controlPanel QCheckBox {
    font-size: 12px;
    min-height: 21px;
    padding: 0;
}
QWidget#controlPanel QRadioButton::indicator,
QWidget#controlPanel QCheckBox::indicator {
    width: 12px;
    height: 12px;
}
QWidget#controlPanel QLineEdit,
QWidget#controlPanel QDateEdit,
QWidget#controlPanel QTextEdit,
QWidget#controlPanel QListWidget,
QWidget#controlPanel QPushButton {
    font-size: 12px;
    min-height: 27px;
    padding: 0 9px;
}
QLineEdit, QDateEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {
    background: #FFFFFF;
    border: 1px solid #D8E0EA;
    border-radius: 6px;
    padding: 5px 9px;
    selection-background-color: #D7F4DC;
    selection-color: #142018;
}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QListWidget:focus {
    border: 1px solid #08A51F;
}
QLineEdit:disabled, QTextEdit:disabled { background: #F3F5F8; color: #9BA5B3; }
QWidget#controlPanel QDateEdit#rangeDate {
    min-width: 96px;
    max-width: 110px;
    min-height: 21px;
    max-height: 21px;
    padding: 0 4px;
    font-size: 11px;
}
QDateEdit#rangeDate:disabled { background: #F3F5F8; color: #9BA5B3; }
QListWidget { padding: 2px; }
QListWidget::item { padding: 3px; border-radius: 5px; }
QListWidget::item:selected { background: #E5F7E8; color: #126B20; }
QListWidget#projectPathList { background: #F8FAFC; }
QWidget#pathRow { background: transparent; }
QLineEdit#pathEditor { background: #FFFFFF; padding: 4px 9px; }
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
QPushButton#releaseNoteButton {
    background: #FFFFFF;
    border-color: #BFCBDD;
    color: #33466A;
    font-size: 12px;
}
QPushButton#releaseNoteButton:hover {
    background: #F3F6FC;
    border-color: #92A4C1;
}
QPushButton#releaseNoteButton:disabled {
    background: #EFF2F5;
    color: #A1AAB6;
    border-color: #E1E6EC;
}
QDialog#releaseNoteDialog {
    background: #EEF2F8;
}
QWidget#releaseNoteEditor {
    background: #FFFFFF;
    border: 1px solid #D8E2EE;
    border-radius: 10px;
}
QLabel#releaseNoteFieldLabel {
    color: #344054;
    font-size: 13px;
    font-weight: 700;
}
QLineEdit#releaseNoteSubject {
    min-height: 34px;
    padding: 0 10px;
    font-family: "Cascadia Mono", "Consolas", "D2Coding", "맑은 고딕", monospace;
    font-size: 13px;
}
QTextEdit#releaseNoteBody {
    padding: 10px 12px;
    font-family: "Cascadia Mono", "Consolas", "D2Coding", "맑은 고딕", monospace;
    font-size: 13px;
    selection-background-color: #D7E4F7;
    selection-color: #172033;
}
QPushButton#releaseNoteCopyButton {
    background: #23367F;
    border-color: #23367F;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 750;
}
QPushButton#releaseNoteCopyButton:hover {
    background: #2D469B;
    border-color: #2D469B;
}
QPushButton#releaseNoteCloseButton {
    background: #FFFFFF;
    border-color: #CFD9E6;
    color: #344054;
    font-size: 13px;
    font-weight: 650;
}
QLabel#releaseNoteCopyStatus {
    color: #176425;
    font-size: 12px;
}
QDialog#settingsDialog QPushButton {
    min-height: 30px;
    max-height: 32px;
    padding: 0 12px;
    border-radius: 7px;
    font-size: 13px;
}
QDialog#settingsDialog QLineEdit {
    padding: 2px 7px;
    font-size: 12px;
}
QDialog#settingsDialog QComboBox {
    padding: 0 8px;
    font-size: 11px;
}
QDialog#settingsDialog QComboBox QAbstractItemView {
    padding: 2px;
    border: 1px solid #C9D4E1;
    background: #FFFFFF;
    color: #344054;
    selection-background-color: #E5F7E8;
    selection-color: #126B20;
    outline: 0;
    font-size: 12px;
}
QDialog#settingsDialog QComboBox QAbstractItemView::item {
    min-height: 20px;
    padding: 2px 7px;
}
QDialog#settingsDialog QRadioButton,
QDialog#settingsDialog QCheckBox {
    min-height: 21px;
    padding: 0;
    font-size: 12px;
}
QDialog#settingsDialog QRadioButton::indicator,
QDialog#settingsDialog QCheckBox::indicator {
    width: 12px;
    height: 12px;
}
QPushButton#dialogPrimaryButton {
    background: #23367F;
    border-color: #23367F;
    color: #FFFFFF;
    font-weight: 750;
}
QPushButton#dialogPrimaryButton:hover {
    background: #2D469B;
    border-color: #2D469B;
}
QPushButton#dialogPrimaryButton:pressed {
    background: #1D2E6D;
    border-color: #1D2E6D;
}
QPushButton#dialogSecondaryButton,
QPushButton#dialogBrowseButton {
    background: #FFFFFF;
    border-color: #CFD9E6;
    color: #344054;
}
QDialog#settingsDialog QPushButton#dialogBrowseButton {
    min-height: 26px;
    max-height: 28px;
    font-size: 12px;
}
QPushButton#topActionButton {
    min-height: 28px;
    max-height: 30px;
    padding: 0 10px;
    background: #FFFFFF;
    border-color: #D6DFEA;
    font-size: 13px;
}
QPushButton#primaryButton {
    min-height: 32px;
    background: #23367F;
    color: #FFFFFF;
    border: 1px solid #23367F;
    font-size: 13px;
    font-weight: 750;
}
QPushButton#primaryButton:hover { background: #2D469B; }
QWidget#controlPanel QPushButton#primaryButton {
    min-height: 30px;
    max-height: 30px;
    font-size: 13px;
}
QPushButton#greenButton { background: #08A51F; color: #FFFFFF; border-color: #08A51F; }
QPushButton#greenButton:hover { background: #07901B; }
QPushButton#compactActionButton {
    min-height: 28px;
    padding: 0 9px;
    border-radius: 5px;
    color: #4A5A70;
    font-size: 13px;
}
QPushButton#pathBrowseButton {
    min-height: 28px;
    padding: 0;
    border-radius: 5px;
    background: #F3F6FA;
}
QRadioButton, QCheckBox { color: #344054; spacing: 6px; }
QRadioButton:checked, QCheckBox:checked { color: #176425; font-weight: 650; }
QSplitter::handle { background: transparent; width: 8px; }
QProgressBar, QProgressBar#miniProgress {
    min-height: 8px;
    max-height: 8px;
    border: 0;
    border-radius: 3px;
    background: #DDE5EE;
    text-align: center;
}
QProgressBar::chunk { background: #16B53A; border-radius: 3px; }
QSpinBox#stepperSpinBox {
    min-height: 20px;
    max-height: 20px;
    padding: 1px 47px 1px 6px;
    font-size: 11px;
}
QToolButton#spinIncreaseButton, QToolButton#spinDecreaseButton {
    min-width: 21px;
    max-width: 21px;
    min-height: 0;
    padding: 0;
    margin: 0;
    background: #F5F7FA;
    color: #526174;
    border: 0;
    border-left: 1px solid #D8E0EA;
    font-family: "Segoe UI", sans-serif;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#spinIncreaseButton {
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}
QToolButton#spinDecreaseButton { border-radius: 0; }
QToolButton#spinIncreaseButton:hover, QToolButton#spinDecreaseButton:hover {
    background: #E9EEF5;
    color: #1F3A70;
}
QToolButton#spinIncreaseButton:pressed, QToolButton#spinDecreaseButton:pressed {
    background: #DCE4EE;
}
QToolButton#spinIncreaseButton:disabled, QToolButton#spinDecreaseButton:disabled {
    background: #F7F8FA;
    color: #C3CBD5;
}
QTabWidget#settingsTabs::pane {
    top: -1px;
    border: 1px solid #DFE7F0;
    background: #FFFFFF;
    border-radius: 10px;
}
QTabWidget#settingsTabs QTabBar::tab {
    min-height: 30px;
    padding: 0 16px;
    margin-right: 4px;
    background: #E9EEF5;
    color: #667085;
    border: 1px solid transparent;
    border-bottom: 0;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    font-size: 13px;
}
QTabWidget#settingsTabs QTabBar::tab:first {
    min-width: 60px;
}
QTabWidget#settingsTabs QTabBar::tab:middle {
    min-width: 120px;
}
QTabWidget#settingsTabs QTabBar::tab:last {
    min-width: 120px;
}
QTabWidget#settingsTabs QTabBar::tab:selected {
    background: #FFFFFF;
    color: #172033;
    border-color: #DFE7F0;
    font-weight: 700;
}
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical {
    width: 10px;
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
QMessageBox {
    font-size: 14px;
}
QMessageBox QLabel#qt_msgbox_label {
    min-width: 440px;
    font-size: 16px;
}
QMessageBox QPushButton {
    min-width: 80px;
    min-height: 28px;
    max-height: 28px;
    margin-bottom: 6px;
    padding: 0 12px;
    font-size: 16px;
}
QToolTip {
    background: #172033;
    color: #F8FAFC;
    border: 1px solid #334155;
    padding: 6px 8px;
    font-size: 12px;
}
"""


TERMINAL_STYLE = r"""
QFrame#terminalFrame {
    background: #0B1120;
    border: 1px solid #1D2A3D;
    border-radius: 10px;
}
QFrame#terminalHeader {
    background: #101827;
    border-bottom: 1px solid #1E2B40;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QFrame#trafficRed { background: #FF5F57; border-radius: 4px; }
QFrame#trafficYellow { background: #FEBC2E; border-radius: 4px; }
QFrame#trafficGreen { background: #28C840; border-radius: 4px; }
QLabel#terminalTitle { color: #D8E4F2; font-size: 14px; font-weight: 750; }
QLabel#terminalStatus {
    border-radius: 8px;
    padding: 2px 6px;
    font-size: 12px;
    font-weight: 700;
}
QLabel#terminalStatus[state="ready"] {
    background: #132A20;
    border: 1px solid #245C3C;
    color: #8DF0A5;
}
QLabel#terminalStatus[state="running"] {
    background: #332A14;
    border: 1px solid #735B1A;
    color: #FFD66B;
}
QLabel#terminalStatus[state="error"] {
    background: #351A1F;
    border: 1px solid #7A2D39;
    color: #FF9CAA;
}
QTextEdit#terminalOutput {
    background: #0B1120;
    color: #C8D7E7;
    border: 0;
    padding: 10px 12px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 13px;
    selection-background-color: #26476A;
}
QPushButton#terminalButton {
    min-height: 28px;
    padding: 0 10px;
    border: 1px solid #27364C;
    background: #162033;
    color: #8FA3BA;
    font-size: 13px;
}
QPushButton#terminalButton:hover { background: #1B2A40; color: #D6E1ED; }
"""

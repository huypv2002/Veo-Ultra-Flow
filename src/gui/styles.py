"""
Stylesheet chung cho toàn bộ ứng dụng.
"""


def get_app_stylesheet() -> str:
    """Return stylesheet chính cho QMainWindow."""
    return """
        /* === GENERAL === */
        QMainWindow {
            background-color: #F2F2F2;
        }

        QWidget {
            color: #333333;
            font-family: "Segoe UI", Arial;
            font-size: 11px;
        }

        /* === HEADER === */
        #appHeader {
            background-color: #FFFFFF;
            border-bottom: 1px solid #D9D9D9;
        }

        /* === ACCOUNT BAR === */
        #accountBar {
            background-color: #F2F2F2;
            border-bottom: 1px solid #D9D9D9;
        }

        #expireLabel {
            background-color: #E6F4FF;
            color: #1E88E5;
            font-weight: normal;
            padding: 4px 12px;
            border: 1px solid #90CAF9;
            border-radius: 3px;
        }

        #logoutButton {
            background-color: #D9534F;
            color: white;
            border: 1px solid #C9302C;
            padding: 5px 14px;
            border-radius: 3px;
            font-weight: normal;
        }

        #logoutButton:hover {
            background-color: #C9302C;
        }

        /* === MAIN TOOLBAR === */
        #mainToolbar {
            background-color: #FFFFFF;
            border-bottom: 1px solid #D9D9D9;
        }

        #mainTab {
            background-color: #F8F8F8;
            color: #333333;
            border: 1px solid #D9D9D9;
            padding: 8px 18px;
            font-size: 12px;
            font-weight: normal;
        }

        #mainTab:hover {
            background-color: #EEEEEE;
        }

        #mainTab:checked {
            background-color: #FFFFFF;
            border-bottom: 2px solid #D9D9D9;
            font-weight: normal;
        }

        /* === SUB TOOLBAR === */
        #subToolbar {
            background-color: #FFFFFF;
            border-bottom: 1px solid #D9D9D9;
        }

        #subTab, #reportTab {
            background-color: #FFFFFF;
            color: #333333;
            border: 1px solid #D9D9D9;
            padding: 6px 12px;
            font-size: 11px;
            font-weight: normal;
        }

        #subTab:hover, #reportTab:hover {
            background-color: #F8F8F8;
        }

        #subTab:checked, #reportTab:checked {
            background-color: #F8F8F8;
            border-bottom: 2px solid #D9D9D9;
        }

        /* === INFO PANEL === */
        #infoPanel {
            background-color: #E6F4FF;
            border: 1px solid #B3D9FF;
            border-radius: 4px;
        }

        /* === GROUPBOX === */
        QGroupBox {
            font-weight: bold;
            font-size: 11px;
            color: #333333;
            border: 1px solid #D9D9D9;
            border-radius: 4px;
            margin-top: 12px;
            padding-top: 8px;
            background-color: #FFFFFF;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }

        /* === INPUT FIELDS === */
        QComboBox, QSpinBox, QLineEdit {
            padding: 4px 6px;
            border: 1px solid #D9D9D9;
            border-radius: 2px;
            background-color: #FFFFFF;
            font-size: 11px;
            color: #333333;
        }

        QComboBox:focus, QSpinBox:focus, QLineEdit:focus {
            border: 1px solid #66AFE9;
        }

        /* === TABLES === */
        QTableWidget {
            background-color: #FFFFFF;
            gridline-color: #E0E0E0;
            border: 1px solid #D9D9D9;
            border-radius: 0px;
        }

        QTableWidget::item {
            padding: 4px;
            color: #333333;
        }

        QTableWidget::item:selected {
            background-color: #D9EDF7;
        }

        QHeaderView::section {
            background-color: #EFEFEF;
            padding: 6px 4px;
            border: none;
            border-bottom: 1px solid #D9D9D9;
            border-right: 1px solid #E0E0E0;
            font-weight: bold;
            font-size: 10px;
            color: #333333;
        }

        /* === BUTTONS IN TABLE === */
        #retryBtn {
            background-color: #F8F8F8;
            color: #333333;
            border: 1px solid #D9D9D9;
            border-radius: 2px;
            padding: 2px 8px;
            font-size: 10px;
        }

        #retryBtn:hover:enabled {
            background-color: #EEEEEE;
        }

        #retryBtn:disabled {
            color: #999999;
        }

        #reviewLink {
            background-color: transparent;
            color: #1E88E5;
            border: none;
            padding: 2px 8px;
            font-size: 10px;
            text-decoration: underline;
        }

        #reviewLink:hover {
            color: #1565C0;
        }

        /* === CONTROL BUTTONS === */
        #startButton, #pauseButton, #continueButton, #fixButton, #retryButton {
            background-color: #F8F8F8;
            color: #333333;
            border: 1px solid #D9D9D9;
            border-radius: 3px;
            padding: 8px 16px;
            font-size: 11px;
            font-weight: normal;
        }

        #startButton:hover, #pauseButton:hover, #continueButton:hover,
        #fixButton:hover, #retryButton:hover {
            background-color: #EEEEEE;
            border: 1px solid #BEBEBE;
        }

        #startButton:pressed, #pauseButton:pressed, #continueButton:pressed,
        #fixButton:pressed, #retryButton:pressed {
            background-color: #E0E0E0;
        }

        #startButton:disabled, #pauseButton:disabled, #continueButton:disabled,
        #fixButton:disabled, #retryButton:disabled {
            background-color: #cccccc !important;
            color: #666666 !important;
            border: 1px solid #aaaaaa !important;
        }

        /* === GUIDE TEXT === */
        #guideText {
            background-color: #FFFFFF;
            border: 1px solid #D9D9D9;
            font-size: 10px;
            color: #333333;
        }

        /* === LOGS === */
        #logsDisplay {
            background-color: #FFFFFF;
            color: #333333;
            border: 1px solid #D9D9D9;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 9px;
        }

        /* === SMALL BROWSE BUTTONS === */
        QPushButton[text="..."] {
            background-color: #F8F8F8;
            color: #333333;
            border: 1px solid #D9D9D9;
            border-radius: 2px;
            padding: 2px 6px;
        }

        QPushButton[text="..."]:hover {
            background-color: #EEEEEE;
        }

        /* === COOKIE BUTTON === */
        #appHeader QPushButton {
            background-color: #F8F8F8;
            color: #333333;
            border: 1px solid #D9D9D9;
            border-radius: 3px;
            padding: 6px 14px;
            font-size: 11px;
        }

        #appHeader QPushButton:hover {
            background-color: #EEEEEE;
        }

        /* === RADIO BUTTONS === */
        QRadioButton {
            font-size: 13px;
            color: #495057;
            spacing: 8px;
        }

        QRadioButton::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #dee2e6;
            border-radius: 9px;
            background: #ffffff;
        }

        QRadioButton::indicator:checked {
            background: #007bff;
            border: 2px solid #007bff;
        }
    """

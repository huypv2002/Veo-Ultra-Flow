"""
Update Dialog - UI cho việc cập nhật ứng dụng từ GitHub Releases
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextBrowser,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from src.core.version import APP_VERSION


class UpdateDialog(QDialog):
    """Dialog hiển thị thông tin cập nhật và tiến trình tải."""

    update_requested = Signal()
    dismissed = Signal()

    def __init__(self, new_version: str = "", release_notes: str = "", parent=None):
        super().__init__(parent)
        self.new_version = new_version.lstrip("v")
        self.release_notes = release_notes
        self.setWindowTitle("Cập nhật ứng dụng")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("🔄 Cập nhật mới!")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Version info
        self.version_label = QLabel(
            f"Phiên bản hiện tại: <b>v{APP_VERSION}</b> → <b>v{self.new_version}</b>"
        )
        self.version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.version_label)
        layout.addSpacing(10)

        # Release notes
        if self.release_notes:
            layout.addWidget(QLabel("Nội dung cập nhật:"))
            self.notes_browser = QTextBrowser()
            self.notes_browser.setMarkdown(self.release_notes)
            self.notes_browser.setMaximumHeight(150)
            layout.addWidget(self.notes_browser)
        layout.addSpacing(10)

        # Progress bar (ẩn mặc định)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addSpacing(10)

        # Buttons
        btn_layout = QHBoxLayout()
        self.skip_button = QPushButton("Bỏ qua")
        self.skip_button.clicked.connect(self._on_skip)
        btn_layout.addWidget(self.skip_button)
        btn_layout.addStretch()
        self.update_button = QPushButton("Cập nhật ngay")
        self.update_button.setDefault(True)
        self.update_button.clicked.connect(self._on_update)
        btn_layout.addWidget(self.update_button)
        layout.addLayout(btn_layout)

    def _on_skip(self):
        self.dismissed.emit()
        self.close()

    def _on_update(self):
        self.update_requested.emit()

    def set_downloading(self, downloading: bool):
        if downloading:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.status_label.setText("Đang tải bản cập nhật...")
            self.update_button.setEnabled(False)
            self.skip_button.setEnabled(False)
        else:
            self.progress_bar.setVisible(False)

    def set_progress(self, percent: int, downloaded_mb: float, total_mb: float):
        self.progress_bar.setValue(percent)
        if total_mb > 0:
            self.status_label.setText(
                f"Đang tải: {percent}% ({downloaded_mb:.1f}MB / {total_mb:.1f}MB)"
            )
        else:
            self.status_label.setText(f"Đang tải: {percent}%")

    def set_ready_to_install(self):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("✅ Đã tải xong! Đang cập nhật...")
        self.update_button.setEnabled(False)
        self.skip_button.setEnabled(False)

    def set_error(self, error: str):
        self.status_label.setText(f"❌ Lỗi: {error}")
        self.status_label.setStyleSheet("color: red;")
        self.update_button.setEnabled(True)
        self.skip_button.setEnabled(True)


class UpdateButton(QPushButton):
    """Nút hiển thị trên toolbar khi có bản cập nhật mới."""

    clicked_with_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.update_version = ""
        self.setText("🔄")
        self.setToolTip("Kiểm tra cập nhật")
        self.setVisible(False)
        self.clicked.connect(self._on_clicked)

    def set_update_available(self, version: str):
        self.update_version = version.lstrip("v")
        self.setText(f"🔄 v{self.update_version}")
        self.setVisible(True)
        self.setToolTip(f"Có bản cập nhật mới v{self.update_version}")

    def _on_clicked(self):
        if self.update_version:
            self.clicked_with_update.emit(self.update_version)

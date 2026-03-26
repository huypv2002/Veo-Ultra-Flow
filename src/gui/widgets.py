"""
Reusable custom widgets dùng chung trong toàn bộ ứng dụng.
"""

from typing import List, Optional
from dataclasses import dataclass, field

from PySide6.QtWidgets import (
    QComboBox, QSpinBox, QDoubleSpinBox, QWidget, QHBoxLayout,
    QPushButton, QLabel, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap


# ==================== NO SCROLL WIDGETS ====================

class NoScrollComboBox(QComboBox):
    """ComboBox không thay đổi giá trị khi lăn chuột"""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollSpinBox(QSpinBox):
    """SpinBox không thay đổi giá trị khi lăn chuột"""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """DoubleSpinBox không thay đổi giá trị khi lăn chuột"""
    def wheelEvent(self, event):
        event.ignore()


# ==================== CLICKABLE LABEL ====================

class ClickableLabel(QLabel):
    """Label có thể click để đổi tên nhân vật"""
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ==================== FLOW TASK DATA ====================

@dataclass
class FlowTaskData:
    """Data model cho mỗi task row trong Task_Grid."""
    index: int
    prompt: str
    model_code: str
    aspect_ratio: str
    seed: int
    reference_images: List[str] = field(default_factory=list)
    status: str = "pending"
    error_message: Optional[str] = None
    output_path: Optional[str] = None


# ==================== THUMBNAIL GRID WIDGET ====================

class ThumbnailGridWidget(QWidget):
    """Widget hiển thị grid thumbnail + nút "+" trong cell của QTableWidget."""

    images_changed = Signal(int, list)  # (row_index, image_paths)

    def __init__(self, row_index: int, max_images: int = 3, parent=None):
        super().__init__(parent)
        self.row_index = row_index
        self.max_images = max_images
        self.image_paths: List[str] = []
        self.thumbnail_size = 48
        self._locked = False

        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(2, 2, 2, 2)

        self._add_btn = QPushButton("+")
        self._add_btn.setFixedSize(self.thumbnail_size, self.thumbnail_size)
        self._add_btn.setStyleSheet(
            "background: #f0f9ff; border: 1px dashed #93c5fd; border-radius: 8px; "
            "font-size: 18px; font-weight: 600; color: #3b82f6;"
        )
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._layout.addWidget(self._add_btn)
        self._layout.addStretch()

    def add_images(self, paths: List[str]) -> None:
        remaining = self.max_images - len(self.image_paths)
        if remaining <= 0:
            return
        self.image_paths.extend(paths[:remaining])
        self._rebuild_layout()
        self.images_changed.emit(self.row_index, list(self.image_paths))

    def _rebuild_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        for path in self.image_paths:
            lbl = QLabel()
            lbl.setFixedSize(self.thumbnail_size, self.thumbnail_size)
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    self.thumbnail_size, self.thumbnail_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            lbl.setPixmap(pixmap)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("border: 1px solid #e2e8f0; border-radius: 6px; background: #f8fafc;")
            self._layout.addWidget(lbl)

        if len(self.image_paths) < self.max_images:
            self._add_btn = QPushButton("+")
            self._add_btn.setFixedSize(self.thumbnail_size, self.thumbnail_size)
            locked = self._locked
            self._add_btn.setEnabled(not locked)
            self._add_btn.setStyleSheet(
                f"background: {'#e2e8f0' if locked else '#f0f9ff'}; "
                f"border: 1px {'solid #cbd5e1' if locked else 'dashed #93c5fd'}; "
                f"border-radius: 8px; font-size: 18px; font-weight: 600; "
                f"color: {'#94a3b8' if locked else '#3b82f6'};"
            )
            self._add_btn.clicked.connect(self._on_add_clicked)
            self._layout.addWidget(self._add_btn)

        self._layout.addStretch()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        for i in range(self._layout.count()):
            w = self._layout.itemAt(i).widget()
            if isinstance(w, QPushButton) and w.text() == "+":
                w.setEnabled(not locked)
                w.setStyleSheet(
                    f"background: {'#e2e8f0' if locked else '#f0f9ff'}; "
                    f"border: 1px {'solid #cbd5e1' if locked else 'dashed #93c5fd'}; "
                    f"border-radius: 8px; font-size: 18px; font-weight: 600; "
                    f"color: {'#94a3b8' if locked else '#3b82f6'};"
                )

    def _on_add_clicked(self) -> None:
        if self._locked:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh tham chiếu", "",
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if files:
            self.add_images(files)

"""
Flow Tab Builder - Builds Flow (Banana Pro) tab UI components
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter
)
from PySide6.QtCore import Qt


def build_flow_tab_content(main_app):
    """Build Flow Image tab content - delegates to main_app for now"""
    # The Flow tab has complex dependencies on main_app methods
    # For now, we delegate to main_app's existing method
    flow_widget = QWidget()
    layout = QVBoxLayout(flow_widget)
    layout.setContentsMargins(5, 5, 5, 5)
    layout.setSpacing(5)

    splitter = QSplitter(Qt.Horizontal)
    splitter.setChildrenCollapsible(False)

    # Use main_app's existing methods
    left_panel = main_app.build_flow_left_panel()
    right_panel = main_app.build_flow_right_panel()
    splitter.addWidget(left_panel)
    splitter.addWidget(right_panel)
    splitter.setSizes([550, 870])

    layout.addWidget(splitter)
    return flow_widget

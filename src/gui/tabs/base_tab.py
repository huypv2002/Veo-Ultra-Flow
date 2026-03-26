"""
Base Tab Class - Base class for all tab modules
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QObject


class BaseTab(QWidget):
    """Base class for all tab modules"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = None
        
    def build_tab_content(self, parent_app):
        """Build and return the tab content widget"""
        raise NotImplementedError("Subclasses must implement build_tab_content")
    
    def on_tab_selected(self):
        """Called when tab is selected"""
        pass
    
    def on_tab_deselected(self):
        """Called when tab is deselected"""
        pass
    
    def cleanup(self):
        """Cleanup resources when tab is destroyed"""
        pass

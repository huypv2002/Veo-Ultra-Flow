"""
GUI Tabs Package - Tab UI builders

This package contains modular UI builders for each tab in the application.
Each builder function creates the UI components and sets up event handlers.
"""

from .video_tab import build_video_tab_content, build_left_panel, build_center_panel, build_logs_panel
from .image_tab import build_image_tab_content
from .flow_tab import build_flow_tab_content

__all__ = [
    'build_video_tab_content',
    'build_left_panel', 
    'build_center_panel',
    'build_logs_panel',
    'build_image_tab_content',
    'build_flow_tab_content'
]

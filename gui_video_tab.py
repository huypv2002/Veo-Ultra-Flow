"""Video tab UI/runtime logic extracted from gui_app_mac.py."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import platform
import queue
import random
import re
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from gui_app import (
    DEFAULT_GEMINI_KEYS,
    DownloadTask,
    ImageTask,
    PromptTask,
    _alphanum_key,
    _extract_file_urls,
    _extract_strings_recursive,
    _safe_json,
    natural_sort_paths,
)
from complete_flow import LabsFlowClient, _parse_cookie_string
from gui_ui_shared import ThumbnailGridWidget


class VideoTabMixin:
    def build_video_tab_content(self):
        """Build Video tab content with a compact web-like layout."""
        video_widget = QWidget()
        video_widget.setObjectName("videoTabRoot")
        video_widget.setStyleSheet("""
            QWidget#videoTabRoot {
                background: #f6f8fb;
            }
            QWidget#videoTabRoot QScrollArea {
                border: none;
                background: transparent;
            }
            QWidget#videoTabRoot QGroupBox {
                background: #ffffff;
                border: 1px solid #dbe3ef;
                border-radius: 14px;
                margin-top: 12px;
                padding-top: 10px;
                font-size: 13px;
                font-weight: 600;
                color: #0f172a;
            }
            QWidget#videoTabRoot QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #0f172a;
            }
            QWidget#videoTabRoot QLineEdit,
            QWidget#videoTabRoot QComboBox,
            QWidget#videoTabRoot QSpinBox,
            QWidget#videoTabRoot QTextEdit,
            QWidget#videoTabRoot QListWidget,
            QWidget#videoTabRoot QTableWidget {
                background: #ffffff;
                border: 1px solid #d7dfeb;
                border-radius: 10px;
                padding: 6px 8px;
                color: #0f172a;
                selection-background-color: #dbeafe;
            }
            QWidget#videoTabRoot QLineEdit:focus,
            QWidget#videoTabRoot QComboBox:focus,
            QWidget#videoTabRoot QSpinBox:focus,
            QWidget#videoTabRoot QTextEdit:focus {
                border: 1px solid #60a5fa;
            }
            QWidget#videoTabRoot QPushButton {
                background: #eef4ff;
                border: 1px solid #c7d6f7;
                border-radius: 10px;
                color: #1d4ed8;
                font-weight: 600;
                padding: 7px 12px;
            }
            QWidget#videoTabRoot QPushButton:hover {
                background: #dbeafe;
            }
            QWidget#videoTabRoot QPushButton#startButton {
                background: #1d4ed8;
                border-color: #1d4ed8;
                color: white;
            }
            QWidget#videoTabRoot QPushButton#pauseButton,
            QWidget#videoTabRoot QPushButton#continueButton {
                background: #ffffff;
                color: #334155;
                border-color: #cbd5e1;
            }
            QWidget#videoTabRoot QPushButton#fixButton {
                background: #fff7ed;
                border-color: #fdba74;
                color: #c2410c;
            }
            QWidget#videoTabRoot QHeaderView::section {
                background: #f8fafc;
                color: #475569;
                border: none;
                border-bottom: 1px solid #e2e8f0;
                padding: 8px;
                font-weight: 600;
            }
            QWidget#videoTabRoot QLabel {
                color: #334155;
            }
        """)
        layout = QVBoxLayout(video_widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        
        top_splitter = QSplitter(Qt.Horizontal)
        
        left = self.build_left_panel()
        top_splitter.addWidget(left)
        
        center = self.build_center_panel()
        top_splitter.addWidget(center)
        
        top_splitter.setSizes([430, 980])
        top_splitter.setChildrenCollapsible(False)
        
        layout.addWidget(top_splitter)
        
        self.video_logs_panel = self.build_logs_panel()
        self.video_logs_panel.setVisible(False)
        
        self.tab_stack.addWidget(video_widget)

    def build_left_panel(self):
        """LEFT: compact web-like sidebar for all video modes."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setMinimumWidth(420)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        
        # ===== PROMPT INPUT (cho I2V/Start+End/Integrate/Extend) =====
        # T2V không cần section này (chỉ dùng Batch Job)
        self.input_group = QGroupBox("Nguồn dữ liệu")
        input_layout = QVBoxLayout()
        input_layout.setSpacing(6)
        
        # Text to Video inputs (CHỈ nhập 1 prompt, file nhiều prompt dùng Batch Job)
        self.txt_t2v_frame = QWidget()
        self.txt_t2v_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        t2v_layout = QVBoxLayout(self.txt_t2v_frame)
        t2v_layout.setContentsMargins(0, 0, 0, 0)
        t2v_layout.setSpacing(0)
        
        # ❌ XÓA PHẦN PROMPT 1 DÒNG - CHỈ DÙNG BATCH JOB
        # Note: Bắt buộc sử dụng Batch Job (file .txt) - Không hỗ trợ nhập trực tiếp
        
        
        # Image to Video inputs (CHỈ hỗ trợ batch theo file .txt / folder)
        self.txt_i2v_frame = QWidget()
        self.txt_i2v_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        i2v_layout = QVBoxLayout(self.txt_i2v_frame)
        i2v_layout.setContentsMargins(0, 0, 0, 0)
        i2v_layout.setSpacing(6)
        
        # Chế độ I2V: chọn cách map ảnh ↔ txt (mỗi radio một hàng)
        i2v_mode_col = QVBoxLayout()
        self.rb_i2v_mode_folder_file = QRadioButton("Thư mục ảnh + 1 file .txt")
        self.rb_i2v_mode_folder_file.setChecked(True)
        self.rb_i2v_mode_folder_txt = QRadioButton("Thư mục ảnh + thư mục .txt")
        self.rb_i2v_mode_root_match = QRadioButton("Folder gốc: file .txt + folder ảnh trùng tên")
        i2v_mode_col.addWidget(self.rb_i2v_mode_folder_file)
        i2v_mode_col.addWidget(self.rb_i2v_mode_folder_txt)
        i2v_mode_col.addWidget(self.rb_i2v_mode_root_match)
        i2v_layout.addLayout(i2v_mode_col)

        self.i2v_media_box, self.i2v_preview_label, self.i2v_preview_info = self._create_video_media_card(
            "Ảnh ref",
            "Chưa có ảnh ref"
        )
        i2v_layout.addWidget(self.i2v_media_box)
        
        # Thư mục ảnh (nhiều files)
        self.lbl_i2v_img_folder = QLabel("Thư mục ảnh (nhiều files):")
        i2v_layout.addWidget(self.lbl_i2v_img_folder)
        img_folder_row = QHBoxLayout()
        self.txt_image_folder = QLineEdit()
        self.txt_image_folder.setPlaceholderText("Chọn thư mục chứa ảnh...")
        img_folder_row.addWidget(self.txt_image_folder)
        self.btn_img_folder = QPushButton("Chọn thư mục")
        self.btn_img_folder.setFixedSize(100, 25)
        self.btn_img_folder.clicked.connect(self.browse_image_folder)
        img_folder_row.addWidget(self.btn_img_folder)
        i2v_layout.addLayout(img_folder_row)
        
        # File prompt tương ứng (có thể chọn 1 file hoặc 1 thư mục)
        self.lbl_i2v_prompt_file = QLabel("File prompt (1 dòng = 1 ảnh):")
        i2v_layout.addWidget(self.lbl_i2v_prompt_file)
        img_prompt_row = QHBoxLayout()
        self.txt_image_prompt_file = QLineEdit()
        self.txt_image_prompt_file.setPlaceholderText("Chọn file .txt...")
        img_prompt_row.addWidget(self.txt_image_prompt_file)
        self.btn_img_prompt = QPushButton("Chọn file")
        self.btn_img_prompt.setFixedSize(80, 25)
        self.btn_img_prompt.clicked.connect(self.browse_image_prompt_file)
        img_prompt_row.addWidget(self.btn_img_prompt)
        i2v_layout.addLayout(img_prompt_row)
        
        # Thư mục chứa file .txt (tùy chọn - giống Text to Video)
        self.lbl_i2v_prompt_folder = QLabel("Thư mục .txt (nhiều files):")
        i2v_layout.addWidget(self.lbl_i2v_prompt_folder)
        img_prompt_folder_row = QHBoxLayout()
        self.txt_image_prompt_folder = QLineEdit()
        self.txt_image_prompt_folder.setPlaceholderText("Chọn thư mục chứa nhiều file .txt...")
        img_prompt_folder_row.addWidget(self.txt_image_prompt_folder)
        self.btn_img_prompt_folder = QPushButton("Chọn thư mục")
        self.btn_img_prompt_folder.setFixedSize(100, 25)
        self.btn_img_prompt_folder.clicked.connect(self.browse_image_prompt_folder)
        img_prompt_folder_row.addWidget(self.btn_img_prompt_folder)
        i2v_layout.addLayout(img_prompt_folder_row)
        
        # Folder gốc (file .txt + folder ảnh trùng tên)
        self.lbl_i2v_root_folder = QLabel("Folder gốc (file .txt + folder ảnh trùng tên):")
        i2v_layout.addWidget(self.lbl_i2v_root_folder)
        img_root_folder_row = QHBoxLayout()
        self.txt_image_root_folder = QLineEdit()
        self.txt_image_root_folder.setPlaceholderText("Chọn folder gốc chứa nhiều file .txt và folder ảnh trùng tên với file .txt...")
        img_root_folder_row.addWidget(self.txt_image_root_folder)
        self.btn_img_root_folder = QPushButton("Chọn folder")
        self.btn_img_root_folder.setFixedSize(100, 25)
        self.btn_img_root_folder.clicked.connect(self.browse_image_root_folder)
        img_root_folder_row.addWidget(self.btn_img_root_folder)
        i2v_layout.addLayout(img_root_folder_row)
        
        # Tip: Giải thích logic
        self.lbl_i2v_tip = QLabel(
            "💡 Logic:\n"
            "- Mode 1: Thư mục ảnh + 1 file .txt (1 ảnh ↔ 1 dòng theo STT)\n"
            "- Mode 2: Thư mục ảnh + thư mục .txt (nhiều file .txt, map theo STT)\n"
            "- Mode 3: Folder gốc: 1.txt + folder '1', 2.txt + folder '2', ..."
        )
        self.lbl_i2v_tip.setStyleSheet("color: #666666; font-size: 10px; font-style: italic;")
        i2v_layout.addWidget(self.lbl_i2v_tip)
        
        # Kết nối sự kiện đổi mode để ẩn/hiện input phù hợp
        self.rb_i2v_mode_folder_file.toggled.connect(self.update_i2v_mode_ui)
        self.rb_i2v_mode_folder_txt.toggled.connect(self.update_i2v_mode_ui)
        self.rb_i2v_mode_root_match.toggled.connect(self.update_i2v_mode_ui)
        # Gọi 1 lần để set trạng thái ban đầu
        self.update_i2v_mode_ui()
        
        
        # Start+End to Video inputs
        self.txt_start_end_frame = QWidget()
        self.txt_start_end_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        se_layout = QVBoxLayout(self.txt_start_end_frame)
        se_layout.setContentsMargins(0, 0, 0, 0)
        se_layout.setSpacing(6)

        se_media_row = QHBoxLayout()
        se_media_row.setSpacing(10)
        self.start_media_box, self.start_preview_label, self.start_preview_info = self._create_video_media_card(
            "Ảnh start",
            "Chưa có ảnh start"
        )
        self.end_media_box, self.end_preview_label, self.end_preview_info = self._create_video_media_card(
            "Ảnh end",
            "Chưa có ảnh end"
        )
        se_media_row.addWidget(self.start_media_box)
        se_media_row.addWidget(self.end_media_box)
        se_layout.addLayout(se_media_row)
        
        # Thư mục ảnh Start-End
        se_layout.addWidget(QLabel("Thư mục ảnh (Start + End):"))
        se_folder_row = QHBoxLayout()
        self.txt_start_end_folder = QLineEdit()
        self.txt_start_end_folder.setPlaceholderText("Chọn thư mục chứa ảnh start-end...")
        se_folder_row.addWidget(self.txt_start_end_folder)
        btn_se_folder = QPushButton("Chọn thư mục")
        btn_se_folder.setFixedSize(100, 25)
        btn_se_folder.clicked.connect(self.browse_start_end_folder)
        se_folder_row.addWidget(btn_se_folder)
        se_layout.addLayout(se_folder_row)
        
        # File prompt
        se_layout.addWidget(QLabel("File prompt (1 dòng = 2 ảnh hoặc 1 cặp frame)"))
        se_prompt_row = QHBoxLayout()
        self.txt_start_end_prompt = QLineEdit()
        self.txt_start_end_prompt.setPlaceholderText("File prompt...")
        se_prompt_row.addWidget(self.txt_start_end_prompt)
        btn_se_prompt = QPushButton("Chọn file")
        btn_se_prompt.setFixedSize(80, 25)
        btn_se_prompt.clicked.connect(self.browse_start_end_prompt)
        se_prompt_row.addWidget(btn_se_prompt)
        se_layout.addLayout(se_prompt_row)

        # Mode chọn cách ghép ảnh: 2 ảnh 1 prompt hoặc nối frame 1-2, 2-3, 3-4...
        mode_row = QHBoxLayout()
        mode_label = QLabel("Chế độ Start+End:")
        mode_row.addWidget(mode_label)
        self.rb_start_end_pair = QRadioButton("2 ảnh / 1 prompt")
        self.rb_start_end_pair.setChecked(True)
        self.rb_start_end_chain = QRadioButton("Nối frame 1-2, 2-3, 3-4...")
        mode_row.addWidget(self.rb_start_end_pair)
        mode_row.addWidget(self.rb_start_end_chain)
        mode_row.addStretch()
        se_layout.addLayout(mode_row)
        
        # Tip
        se_tip = QLabel("💡 Logic:\n- 2 ảnh / 1 prompt: Ảnh 1+2 → Dòng 1, Ảnh 3+4 → Dòng 2...\n- Nối frame: Folder 1-2-3-4-5 → (1,2), (2,3), (3,4), (4,5)")
        se_tip.setStyleSheet("color: #666666; font-size: 10px; font-style: italic;")
        se_layout.addWidget(se_tip)
        
        
        # Extend Video inputs
        self.txt_extend_frame = QWidget()
        self.txt_extend_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        ext_layout = QVBoxLayout(self.txt_extend_frame)
        ext_layout.setContentsMargins(0, 0, 0, 0)
        ext_layout.setSpacing(6)
        
        # File TXT input
        ext_layout.addWidget(QLabel("File TXT (mỗi dòng = 1 đoạn video 8s):"))
        file_row = QHBoxLayout()
        self.txt_extend_txt_file = QLineEdit()
        self.txt_extend_txt_file.setPlaceholderText("Chọn file .txt...")
        file_row.addWidget(self.txt_extend_txt_file)
        btn_ext_file = QPushButton("Chọn file")
        btn_ext_file.setFixedSize(100, 25)
        btn_ext_file.clicked.connect(self.browse_extend_txt_file)
        file_row.addWidget(btn_ext_file)
        ext_layout.addLayout(file_row)
        
        # Folder TXT import (mỗi file = 1 project, validate ≤ 5 dòng)
        ext_layout.addWidget(QLabel("Folder TXT (mỗi file = 1 project, ≤ 5 dòng/file):"))
        folder_row = QHBoxLayout()
        self.txt_extend_txt_folder = QLineEdit()
        self.txt_extend_txt_folder.setPlaceholderText("Chọn thư mục chứa các file .txt...")
        folder_row.addWidget(self.txt_extend_txt_folder)
        btn_ext_folder = QPushButton("Chọn thư mục")
        btn_ext_folder.setFixedSize(120, 25)
        btn_ext_folder.clicked.connect(self.browse_extend_txt_folder)
        folder_row.addWidget(btn_ext_folder)
        ext_layout.addLayout(folder_row)
        
        # Group size
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("Mỗi project chứa:"))
        self.combo_extend_group_size = QComboBox()
        # ✅ Sẽ được cập nhật trong _apply_extend_group_limit() dựa trên gói user
        self.combo_extend_group_size.addItems([str(i) for i in range(1, 6)])  # Default: Max 5 prompts/project
        self.combo_extend_group_size.setCurrentText("5")
        self.combo_extend_group_size.setFixedWidth(60)
        group_row.addWidget(self.combo_extend_group_size)
        self.lbl_extend_max_prompts = QLabel("đoạn (max 5)")  # ✅ Label sẽ được cập nhật động
        group_row.addWidget(self.lbl_extend_max_prompts)
        group_row.addStretch()
        ext_layout.addLayout(group_row)
        
        # Output folder
        ext_layout.addWidget(QLabel("Thư mục xuất video:"))
        output_row = QHBoxLayout()
        self.txt_extend_output = QLineEdit()
        self.txt_extend_output.setText(str(Path.home() / "Downloads" / "Extended_Videos"))
        output_row.addWidget(self.txt_extend_output)
        btn_ext_output = QPushButton("Chọn")
        btn_ext_output.setFixedSize(80, 25)
        btn_ext_output.clicked.connect(self.browse_extend_output)
        output_row.addWidget(btn_ext_output)
        ext_layout.addLayout(output_row)
        
        
        # Integrate to Video inputs
        self.txt_integrate_frame = QWidget()
        self.txt_integrate_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        int_layout = QVBoxLayout(self.txt_integrate_frame)
        int_layout.setContentsMargins(0, 0, 0, 0)
        int_layout.setSpacing(6)
        
        # ✅ RADIO BUTTONS: Mặc Định / Tùy Chỉnh (chỉ hiện khi device_info > 1)
        self.integrate_mode_group = QButtonGroup()
        mode_radio_layout = QHBoxLayout()
        mode_radio_layout.setSpacing(15)
        
        self.rb_integrate_default = QRadioButton("Mặc Định")
        self.rb_integrate_default.setChecked(True)
        self.rb_integrate_default.toggled.connect(self.on_integrate_mode_changed)
        self.integrate_mode_group.addButton(self.rb_integrate_default, 0)
        mode_radio_layout.addWidget(self.rb_integrate_default)
        
        self.rb_integrate_custom = QRadioButton("Tùy Chỉnh (Trả Phí)")
        self.rb_integrate_custom.toggled.connect(self.on_integrate_mode_changed)
        self.integrate_mode_group.addButton(self.rb_integrate_custom, 1)
        mode_radio_layout.addWidget(self.rb_integrate_custom)
        
        mode_radio_layout.addStretch()
        int_layout.addLayout(mode_radio_layout)
        
        # ✅ MẶC ĐỊNH MODE (giữ nguyên logic cũ)
        self.integrate_default_frame = QWidget()
        default_layout = QVBoxLayout(self.integrate_default_frame)
        default_layout.setContentsMargins(0, 0, 0, 0)
        default_layout.setSpacing(6)

        self.integrate_media_box, self.integrate_preview_label, self.integrate_preview_info = self._create_video_media_card(
            "Ảnh ref",
            "Chưa có ảnh ref"
        )
        default_layout.addWidget(self.integrate_media_box)
        
        # Folder ảnh
        default_layout.addWidget(QLabel("Thư mục ảnh tham chiếu:"))
        img_folder_row = QHBoxLayout()
        self.txt_integrate_images_folder = QLineEdit()
        self.txt_integrate_images_folder.setPlaceholderText("Chọn thư mục ảnh...")
        img_folder_row.addWidget(self.txt_integrate_images_folder)
        btn_int_folder = QPushButton("Chọn thư mục")
        btn_int_folder.setFixedSize(100, 25)
        btn_int_folder.clicked.connect(self.browse_integrate_images_folder)
        img_folder_row.addWidget(btn_int_folder)
        default_layout.addLayout(img_folder_row)
        
        # File prompt
        default_layout.addWidget(QLabel("File prompt (.txt):"))
        prompt_row = QHBoxLayout()
        self.txt_integrate_prompt_file = QLineEdit()
        self.txt_integrate_prompt_file.setPlaceholderText("Chọn file prompt...")
        prompt_row.addWidget(self.txt_integrate_prompt_file)
        btn_int_prompt = QPushButton("Chọn file")
        btn_int_prompt.setFixedSize(80, 25)
        btn_int_prompt.clicked.connect(self.browse_integrate_prompt_file)
        prompt_row.addWidget(btn_int_prompt)
        default_layout.addLayout(prompt_row)
        
        # Số ảnh mỗi nhóm
        group_size_row = QHBoxLayout()
        group_size_row.addWidget(QLabel("Số ảnh / nhóm:"))
        self.combo_integrate_images_per_group = QComboBox()
        self.combo_integrate_images_per_group.addItems(["1", "2", "3"])
        self.combo_integrate_images_per_group.setCurrentText("1")
        self.combo_integrate_images_per_group.setFixedWidth(60)
        group_size_row.addWidget(self.combo_integrate_images_per_group)
        group_size_row.addStretch()
        default_layout.addLayout(group_size_row)
        
        # ✅ SEPARATOR LINE
        separator_line = QFrame()
        separator_line.setFrameShape(QFrame.HLine)
        separator_line.setFrameShadow(QFrame.Sunken)
        separator_line.setStyleSheet("background-color: #e0e0e0; margin: 10px 0;")
        default_layout.addWidget(separator_line)
        
        # ✅ FOLDER PROMPTS + NHÂN VẬT CỐ ĐỊNH MODE
        folder_fixed_label = QLabel("📁 Folder prompts + nhân vật cố định")
        folder_fixed_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #1976D2; margin-top: 5px;")
        default_layout.addWidget(folder_fixed_label)
        
        folder_fixed_tip = QLabel("Chọn một folder prompt và áp dụng cùng bộ ảnh cố định cho toàn bộ prompt.")
        folder_fixed_tip.setStyleSheet("font-size: 11px; color: #666; margin-bottom: 5px;")
        folder_fixed_tip.setWordWrap(True)
        default_layout.addWidget(folder_fixed_tip)
        
        # Folder prompts
        default_layout.addWidget(QLabel("Thư mục chứa các file prompts (.txt):"))
        folder_prompts_row = QHBoxLayout()
        self.txt_expand_ref_folder_prompts = QLineEdit()
        self.txt_expand_ref_folder_prompts.setPlaceholderText("Chọn thư mục chứa các file .txt...")
        folder_prompts_row.addWidget(self.txt_expand_ref_folder_prompts)
        btn_folder_prompts = QPushButton("Chọn thư mục")
        btn_folder_prompts.setFixedSize(100, 25)
        btn_folder_prompts.clicked.connect(self.browse_expand_ref_folder_prompts)
        folder_prompts_row.addWidget(btn_folder_prompts)
        default_layout.addLayout(folder_prompts_row)
        
        # Nhân vật cố định - ListWidget hiển thị ảnh đã chọn
        default_layout.addWidget(QLabel("Ảnh nhân vật cố định:"))
        self.expand_ref_fixed_images_grid = ThumbnailGridWidget(-1, max_images=3)
        self.expand_ref_fixed_images_grid.images_changed.connect(self._on_expand_ref_fixed_images_grid_changed)
        default_layout.addWidget(self.expand_ref_fixed_images_grid)

        self.expand_ref_fixed_images_list = QListWidget()
        self.expand_ref_fixed_images_list.setVisible(False)
        default_layout.addWidget(self.expand_ref_fixed_images_list)
        
        # Buttons thêm/xóa ảnh
        fixed_images_btn_row = QHBoxLayout()
        btn_add_fixed_images = QPushButton("➕ Thêm ảnh")
        btn_add_fixed_images.setFixedSize(100, 28)
        btn_add_fixed_images.clicked.connect(self.add_expand_ref_fixed_images)
        fixed_images_btn_row.addWidget(btn_add_fixed_images)
        
        btn_clear_fixed_images = QPushButton("🗑️ Xóa tất cả")
        btn_clear_fixed_images.setFixedSize(100, 28)
        btn_clear_fixed_images.clicked.connect(self.clear_expand_ref_fixed_images)
        fixed_images_btn_row.addWidget(btn_clear_fixed_images)
        fixed_images_btn_row.addStretch()
        default_layout.addLayout(fixed_images_btn_row)
        
        # ✅ Lưu danh sách ảnh cố định
        self.expand_ref_fixed_images_paths: List[str] = []
        
        # Tip
        # Ẩn UI hướng dẫn để giao diện gọn hơn
        
        int_layout.addWidget(self.integrate_default_frame)
        
        # ✅ TÙY CHỈNH MODE (chức năng mới) - Dùng popup dialog
        # Chỉ hiển thị nút mở popup
        custom_btn_layout = QHBoxLayout()
        custom_btn_layout.addStretch()
        self.btn_open_custom = QPushButton("⚙️ Mở Cấu Hình Tùy Chỉnh")
        self.btn_open_custom.setFixedSize(200, 35)
        self.btn_open_custom.setObjectName("btn_open_custom")  # ✅ Đặt objectName để dễ dàng nhận biết và bảo vệ
        self.btn_open_custom.clicked.connect(self.open_custom_integrate_dialog)
        custom_btn_layout.addWidget(self.btn_open_custom)
        custom_btn_layout.addStretch()
        
        self.integrate_custom_frame = QWidget()  # Giữ lại để tương thích với code cũ
        custom_frame_layout = QVBoxLayout(self.integrate_custom_frame)
        custom_frame_layout.setContentsMargins(0, 0, 0, 0)
        custom_frame_layout.addLayout(custom_btn_layout)
        
        int_layout.addWidget(self.integrate_custom_frame)
        self.integrate_custom_frame.setVisible(False)  # Ẩn ban đầu
        
        # ✅ Initialize character storage
        self.custom_characters = {}  # {name: image_path}
        self.character_matching_results = {}  # {prompt_index: [character_names]}
        
        # ✅ Tạo widget ẩn để lưu prompt file path (cho dialog)
        self.txt_integrate_custom_prompt_file = QLineEdit()
        self.txt_integrate_custom_prompt_file.setVisible(False)  # Ẩn widget
        
        # ✅ Check device_info để hiển thị radio buttons
        device_info = self.get_device_info()
        # ✅ LUÔN HIỂN THỊ radio buttons và custom frame để user có thể truy cập nút "Mở Cấu Hình Tùy Chỉnh"
        self.rb_integrate_default.setVisible(True)
        self.rb_integrate_custom.setVisible(True)
        # Default: hiển thị default frame, ẩn custom frame (user có thể chuyển bằng radio button)
        self.integrate_default_frame.setVisible(True)
        self.integrate_custom_frame.setVisible(False)

        # ===== SIMPLE MODE PAGES (giống web: chỉ giữ nhập txt/folder ở panel dưới) =====
        def _build_simple_video_mode_page(title: str, action_row: Optional[QHBoxLayout] = None) -> QWidget:
            page = QWidget()
            page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(6)
            if action_row is not None:
                page_layout.addLayout(action_row)
            return page

        self.txt_i2v_simple_frame = _build_simple_video_mode_page("Ảnh thành Video")
        self.txt_start_end_simple_frame = _build_simple_video_mode_page("Đầu+Cuối thành Video")
        self.txt_integrate_simple_frame = _build_simple_video_mode_page("Tham chiếu thành Video")
        

        self.video_mode_form_stack = QStackedWidget()
        self.video_mode_form_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.video_mode_form_stack.addWidget(self.txt_t2v_frame)
        self.video_mode_form_stack.addWidget(self.txt_i2v_simple_frame)
        self.video_mode_form_stack.addWidget(self.txt_start_end_simple_frame)
        self.video_mode_form_stack.addWidget(self.txt_integrate_simple_frame)
        self.video_mode_form_stack.addWidget(self.txt_extend_frame)
        self.video_mode_form_stack.setCurrentWidget(self.txt_t2v_frame)
        input_layout.addWidget(self.video_mode_form_stack)
        
        self.input_group.setLayout(input_layout)
        self.input_group.setVisible(True)
        layout.addWidget(self.input_group)
        
        # ===== THIẾT LẬP TẠO VIDEO =====
        self.settings_box = QGroupBox("Thiết lập")
        settings_layout = QGridLayout()
        settings_layout.setSpacing(8)
        settings_layout.setColumnStretch(1, 1)
        settings_layout.setColumnStretch(2, 0)
        
        row = 0
        
        # Model
        settings_layout.addWidget(QLabel("Model"), row, 0)
        self.combo_model = QComboBox()
        # Sắp xếp theo credits: Low Fast (0) < Fast (10) < Quality (100)
        # Bao gồm cả Portrait (9:16) và Landscape (16:9) variants
        self.combo_model.addItems([
            # Landscape (16:9)
            "Veo 3.1 - Lite (16:9) - 0 credits",
            "Veo 3.1 - Fast (16:9) - 10 credits",
            "Veo 3.1 - Quality (16:9) - 100 credits",
            "Veo 3.1 - Lite [Lower Priority] (16:9) - 0 credits",
            "Veo 3.1 - Fast [Lower Priority] (16:9) - 0 credits",
            # Portrait (9:16)
            "Veo 3.1 - Lite (9:16) - 0 credits",
            "Veo 3.1 - Fast (9:16) - 10 credits",
            "Veo 3.1 - Quality (9:16) - 100 credits",
            "Veo 3.1 - Lite [Lower Priority] (9:16) - 0 credits",
            "Veo 3.1 - Fast [Lower Priority] (9:16) - 0 credits",
        ])
        self.combo_model.setCurrentIndex(1)  # Default = Veo 3.1 - Fast (16:9) (10 credits)
        settings_layout.addWidget(self.combo_model, row, 1)
        self.combo_model.currentIndexChanged.connect(self.update_model_credit_hint)
        
        # Model credit hint - Ẩn vì đã có trong combo box
        self.model_credit_label = QLabel("")
        self.model_credit_label.setStyleSheet("font-size: 11px; color: #616161;")
        self.model_credit_label.setVisible(True)  # Luôn hiển thị credits rõ ràng dưới dropdown
        settings_layout.addWidget(self.model_credit_label, row + 1, 0, 1, 2)
        self.update_model_credit_hint()
        
        # Tăng row để Upscale đứng ngay bên dưới Model
        row += 1    
        
        # Số video mỗi prompt - ẨN UI (mặc định = 1, không cho phép thay đổi)
        self.spin_num_videos = QSpinBox()
        self.spin_num_videos.setRange(1, 1)  # Min=1, Max=1 (cố định)
        self.spin_num_videos.setValue(1)
        self.spin_num_videos.setVisible(False)  # Ẩn UI
        # Không thêm vào layout để ẩn hoàn toàn - KHÔNG TĂNG row
        
        # ✅ Tỷ lệ Video - ĐÃ BỎ, dùng model có ratio trong tên
        # Model sẽ tự động chọn đúng ratio dựa trên tên model
        # 16:9 = Landscape, 9:16 = Portrait
        
        # ✅ Ẩn số công việc - tự động = số cookie (1 cookie = 1 công việc tuần tự)
        # Số công việc đồng thời sẽ tự động = số lượng cookie
        self.spin_concurrent = QSpinBox()  # Vẫn tạo để dùng trong code nhưng ẩn UI
        self.spin_concurrent.setRange(1, 10)
        self.spin_concurrent.setValue(1)
        self.spin_concurrent.valueChanged.connect(self.on_concurrent_changed)
        self.spin_concurrent.setVisible(False)  # Ẩn khỏi UI
        
        # ✅ ẨN DELAY UI - Không còn delay giữa các prompt (nối đuôi liên tục)
        # Delay mỗi cookie (ẨN - không dùng nữa)
        # settings_layout.addWidget(QLabel("Delay mỗi cookie (giây):"), row, 0)
        self.spin_cookie_delay = QSpinBox()
        self.spin_cookie_delay.setRange(20, 120)  # ✅ Min = 20s, Max = 120s
        self.spin_cookie_delay.setValue(45)  # ✅ Default = 45s
        self.spin_cookie_delay.setToolTip("Khoảng cách giữa hai prompt liên tiếp trên cùng 1 cookie (20-120s)")
        # settings_layout.addWidget(self.spin_cookie_delay, row, 1)
        self.spin_cookie_delay.setVisible(False)  # Ẩn khỏi UI
        # row += 1
        # Load persisted delay preference if available
        # self._load_video_delay_setting()  # Comment lại vì không dùng nữa
        
        # Upscale
        settings_layout.addWidget(QLabel("Upscale"), row, 0)
        self.combo_upscale = QComboBox()
        self.combo_upscale.addItems(["720P", "1080P", "4K"])  # 720P (mặc định, 5 task/cookie), 1080P/4K (upscale, 3 task/cookie)
        self.combo_upscale.setCurrentText("720P")  # Mặc định 720P = không upscale
        self.combo_upscale.currentIndexChanged.connect(self.on_upscale_changed)
        settings_layout.addWidget(self.combo_upscale, row, 1)
        
        # Tăng row để info panel ở row tiếp theo
        row += 1
        
        # **Cung Cấp Tool** info panel - Dạng ngang, mỗi dòng 4 dịch vụ
        info_panel = QFrame()
        info_panel.setObjectName("infoPanel")
        info_layout = QGridLayout(info_panel)  # Dùng Grid để xuống dòng tự động
        info_layout.setContentsMargins(12, 8, 12, 8)
        info_layout.setHorizontalSpacing(20)
        info_layout.setVerticalSpacing(5)
        
        # Danh sách các dịch vụ
        tools = [
            "Tool Veo 3 Unlimited",
            "Acc Veo 3 Ultra",
            "Elevenlabs +",
            "API Key Elevenlabs",
            "Gmail Cổ & News",
            "Liên Hệ Admin"
        ]
        
        # Thêm vào grid, mỗi dòng 3 items
        cols_per_row = 3
        for i, tool in enumerate(tools):
            lbl = QLabel(f"• {tool}")
            lbl.setStyleSheet("font-size: 9px; color: #424242;")
            info_layout.addWidget(lbl, i // cols_per_row, i % cols_per_row)
        
        settings_layout.addWidget(info_panel, row, 0, 1, 2)  # Span 2 cột
        
        self.settings_box.setLayout(settings_layout)
        layout.addWidget(self.settings_box)
        
        # ===== BATCH JOB (CHỈ cho T2V) =====
        self.batch_job_group = QGroupBox("Batch Job")
        batch_layout = QVBoxLayout()
        batch_layout.setSpacing(8)
        
        # File TXT (chỉ chấp nhận file .txt)
        txt_label = QLabel("File prompt (.txt)")
        txt_label.setStyleSheet("font-weight: bold;")
        batch_layout.addWidget(txt_label)
        
        txt_row = QHBoxLayout()
        self.txt_file = QLineEdit()
        self.txt_file.setPlaceholderText("Chọn file .txt chứa prompts (1 prompt/dòng)...")
        self.txt_file.setReadOnly(True)  # Không cho người dùng nhập, chỉ chọn file
        txt_row.addWidget(self.txt_file)
        btn_txt = QPushButton("Chọn file")
        btn_txt.setFixedSize(80, 25)
        btn_txt.clicked.connect(self.browse_txt_file)
        txt_row.addWidget(btn_txt)
        batch_layout.addLayout(txt_row)
        
        # Thư mục
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Thư mục"))
        self.batch_folder = QLineEdit()
        self.batch_folder.setPlaceholderText("C:\\Users\\PC Viettest")
        folder_row.addWidget(self.batch_folder)
        btn_folder = QPushButton("...")
        btn_folder.setFixedSize(30, 25)
        btn_folder.clicked.connect(self.browse_batch_folder)
        folder_row.addWidget(btn_folder)
        batch_layout.addLayout(folder_row)
        
        # Folder Lưu (DÙNG CHUNG cho tất cả modes: T2V, I2V, Start+End)
        folder_luu_label = QLabel("Folder lưu")
        folder_luu_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        batch_layout.addWidget(folder_luu_label)
        
        output_row = QHBoxLayout()
        self.output_folder = QLineEdit()
        self.output_folder.setPlaceholderText("Chọn thư mục lưu video...")
        output_row.addWidget(self.output_folder)
        btn_output = QPushButton("...")
        btn_output.setFixedSize(30, 25)
        btn_output.clicked.connect(self.browse_output_folder)
        output_row.addWidget(btn_output)
        batch_layout.addLayout(output_row)
        
        # Note: Output folder dùng chung cho TẤT CẢ modes
        output_note = QLabel("📁 Thư mục này dùng chung cho T2V/I2V/Start+End")
        output_note.setStyleSheet("color: #666666; font-size: 9px; font-style: italic;")
        batch_layout.addWidget(output_note)
        
        # Danh sách file batch table (label)
        self.batch_table_label = QLabel("📋 Danh sách batch")
        self.batch_table_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #1976D2;")
        batch_layout.addWidget(self.batch_table_label)
        
        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(3)
        self.batch_table.setHorizontalHeaderLabels(["Id", "FileName", "Status"])
        self.batch_table.setMinimumHeight(180)  # Tăng từ 150 → 180 (minimum thay vì maximum)
        self.batch_table.setMaximumHeight(300)  # Cho phép kéo lên tối đa 300px
        self.batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.batch_table.verticalHeader().setVisible(False)
        
        # Không populate sample data - sẽ load khi chọn file/folder thật
        
        self.batch_table.setColumnWidth(0, 40)
        self.batch_table.setColumnWidth(1, 150)
        self.batch_table.horizontalHeader().setStretchLastSection(True)
        
        batch_layout.addWidget(self.batch_table)
        self.batch_job_group.setLayout(batch_layout)
        layout.addWidget(self.batch_job_group)
        
        # Batch Job mặc định HIỆN (vì mode mặc định là Text to Video)
        # NHƯNG phần "File TXT" và "Thư mục" sẽ ẩn với I2V/Start+End
        # Ẩn hoàn toàn nhóm Batch Job cũ để tăng diện tích cho phần trên
        self.batch_job_group.setVisible(False)
        
        # Store references để có thể ẩn/hiện file/folder fields (không còn dùng)
        self.batch_file_widgets = [txt_row.itemAt(i).widget() for i in range(txt_row.count())]
        self.batch_folder_widgets = [folder_row.itemAt(i).widget() for i in range(folder_row.count())]
        
        # BỎ phần "Hướng dẫn sử dụng" (giữ giao diện gọn)
        
        layout.addStretch()
        
        # ✅ Set widget vào scroll area
        scroll_area.setWidget(widget)
        
        return scroll_area

    def build_center_panel(self):
        """CENTER: prompts table and actions, styled like a web admin grid."""
        widget = QWidget()
        widget.setObjectName("videoCenterPanel")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        
        # ✅ Pagination Controls cho Prompts Table
        pagination_row = QHBoxLayout()
        
        self.lbl_prompts_page_info = QLabel("Trang 1/1 (0 prompts)")
        self.lbl_prompts_page_info.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 12px;")
        pagination_row.addWidget(self.lbl_prompts_page_info)
        
        pagination_row.addStretch()
        
        self.btn_prompts_prev_page = QPushButton("◀ Trước")
        self.btn_prompts_prev_page.setFixedSize(96, 32)
        self.btn_prompts_prev_page.clicked.connect(self.go_to_prev_prompts_page)
        self.btn_prompts_prev_page.setEnabled(False)
        pagination_row.addWidget(self.btn_prompts_prev_page)
        
        self.lbl_prompts_current_page = QLabel("1/1")
        self.lbl_prompts_current_page.setStyleSheet("font-weight: bold; font-size: 13px; margin: 0 10px;")
        pagination_row.addWidget(self.lbl_prompts_current_page)
        
        self.btn_prompts_next_page = QPushButton("Sau ▶")
        self.btn_prompts_next_page.setFixedSize(96, 32)
        self.btn_prompts_next_page.clicked.connect(self.go_to_next_prompts_page)
        self.btn_prompts_next_page.setEnabled(False)
        pagination_row.addWidget(self.btn_prompts_next_page)

        self.btn_open_video_logs = QPushButton("Xem logs")
        self.btn_open_video_logs.setFixedSize(102, 32)
        self.btn_open_video_logs.clicked.connect(self.open_video_logs_dialog)
        pagination_row.addSpacing(8)
        pagination_row.addWidget(self.btn_open_video_logs)
        
        layout.addLayout(pagination_row)
        
        # ✅ Pagination variables
        self.prompts_per_page = 200  # 200 rows per page
        self.current_prompts_page = 1
        self.total_prompts_pages = 1
        self.all_prompts_data = []  # Store all prompts data for pagination
        
        # ✅ BUG FIX: Global progress storage để preserve khi filter
        self.global_task_progress = {}  # {task_index: progress_percent}
        
        # ===== PROMPTS TABLE =====
        self.prompts_table = QTableWidget()
        self.prompts_table.setColumnCount(6)  # Thêm cột Action
        self.prompts_table.setHorizontalHeaderLabels([
            "STT", "Prompt (Lời nhắc)", "Tiến độ", "Trạng thái", "Review", "Chạy lại"
        ])
        
        # Column widths
        self.prompts_table.setColumnWidth(0, 52)   # STT
        self.prompts_table.setColumnWidth(2, 180)
        self.prompts_table.setColumnWidth(3, 80)   # Trạng thái
        self.prompts_table.setColumnWidth(4, 80)   # Review
        self.prompts_table.setColumnWidth(5, 100)   # Chạy lại
        self.prompts_table.setColumnHidden(0, True)
        self.prompts_table.setColumnHidden(3, True)
        self.prompts_table.setColumnHidden(5, True)
        
        self.prompts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.prompts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Hiển thị STT bằng vertical header
        self.prompts_table.verticalHeader().setVisible(True)
        self.prompts_table.verticalHeader().setDefaultSectionSize(24)
        self.prompts_table.verticalHeader().setStyleSheet("QHeaderView::section { background: #F5F7FA; color: #333; }")
        
        # Click header STT để chọn/bỏ chọn toàn bộ dòng
        self.prompts_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        
        # Disable word wrap để giữ UI gọn
        self.prompts_table.setWordWrap(False)
        
        # KHÔNG populate dữ liệu mẫu - để trống, chỉ hiển thị khi xử lý thật
        # Bảng sẽ được populate khi user nhấn "Bắt đầu"
        
        # Stretch column 1 (Prompt)
        self.prompts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._sync_video_prompt_table_columns()
        
        layout.addWidget(self.prompts_table)

        self.video_batch_image_actions_frame = QWidget()
        batch_image_actions_layout = QHBoxLayout(self.video_batch_image_actions_frame)
        batch_image_actions_layout.setContentsMargins(0, 0, 0, 0)
        batch_image_actions_layout.setSpacing(8)

        self.btn_video_add_all_images = QPushButton("Thêm tất cả ảnh")
        self.btn_video_add_all_images.setFixedHeight(30)
        self.btn_video_add_all_images.clicked.connect(self.add_all_images_to_video_rows)
        batch_image_actions_layout.addWidget(self.btn_video_add_all_images)

        self.btn_video_add_all_start_images = QPushButton("Thêm tất cả ảnh start")
        self.btn_video_add_all_start_images.setFixedHeight(30)
        self.btn_video_add_all_start_images.clicked.connect(self.add_all_start_images_to_video_rows)
        batch_image_actions_layout.addWidget(self.btn_video_add_all_start_images)

        self.btn_video_add_all_end_images = QPushButton("Thêm tất cả ảnh end")
        self.btn_video_add_all_end_images.setFixedHeight(30)
        self.btn_video_add_all_end_images.clicked.connect(self.add_all_end_images_to_video_rows)
        batch_image_actions_layout.addWidget(self.btn_video_add_all_end_images)

        self.btn_video_add_all_reference_images = QPushButton("Thêm tất cả ảnh tham chiếu")
        self.btn_video_add_all_reference_images.setFixedHeight(30)
        self.btn_video_add_all_reference_images.clicked.connect(self.add_all_reference_images_to_video_rows)
        batch_image_actions_layout.addWidget(self.btn_video_add_all_reference_images)

        batch_image_actions_layout.addStretch()
        self.video_batch_image_actions_frame.setVisible(False)
        layout.addWidget(self.video_batch_image_actions_frame)
        
        # ===== CONTROL BUTTONS (Normal modes) =====
        self.normal_control_frame = QWidget()
        btn_layout = QHBoxLayout(self.normal_control_frame)
        btn_layout.setAlignment(Qt.AlignCenter)
        btn_layout.setSpacing(10)
        
        # Bắt đầu
        self.btn_start = QPushButton("Chạy")
        self.btn_start.setFixedSize(108, 38)
        self.btn_start.setObjectName("startButton")
        self.btn_start.clicked.connect(self.on_start)
        btn_layout.addWidget(self.btn_start)
        
        # Tạm dừng
        self.btn_pause = QPushButton("Dừng")
        self.btn_pause.setFixedSize(96, 38)
        self.btn_pause.setObjectName("pauseButton")
        self.btn_pause.clicked.connect(self.on_pause)
        btn_layout.addWidget(self.btn_pause)
        
        # Tiếp tục
        self.btn_continue = QPushButton("Tiếp")
        self.btn_continue.setFixedSize(96, 38)
        self.btn_continue.setObjectName("continueButton")
        self.btn_continue.clicked.connect(self.on_continue)
        btn_layout.addWidget(self.btn_continue)
        
        # Sửa All File Lỗi - CHỈ ENABLE KHI CÓ FAILED TASKS
        self.btn_fix_all = QPushButton("Sửa file lỗi")
        self.btn_fix_all.setFixedSize(118, 38)
        self.btn_fix_all.setObjectName("fixButton")
        self.btn_fix_all.setEnabled(False)  # Disable by default
        self.btn_fix_all.clicked.connect(self.on_fix_all_failed)
        btn_layout.addWidget(self.btn_fix_all)
        
        # ✅ BỎ NÚT "Chạy Lại" - chỉ giữ "Sửa All File Lỗi"
        
        # Xóa All Prompt
        self.btn_clear_prompts = QPushButton("Xóa prompt")
        self.btn_clear_prompts.setFixedSize(108, 38)
        self.btn_clear_prompts.clicked.connect(self.on_clear_all_prompts)
        btn_layout.addWidget(self.btn_clear_prompts)
        
        # Mở Folder Video
        self.btn_open_folder = QPushButton("Mở thư mục")
        self.btn_open_folder.setFixedSize(110, 38)
        self.btn_open_folder.clicked.connect(self.on_open_output_folder)
        btn_layout.addWidget(self.btn_open_folder)
        
        
        
        layout.addWidget(self.normal_control_frame)
        
        # ===== EXTEND VIDEO CONTROLS =====
        self.extend_control_frame = QWidget()
        ext_btn_layout = QHBoxLayout(self.extend_control_frame)
        ext_btn_layout.setAlignment(Qt.AlignCenter)
        ext_btn_layout.setSpacing(10)
        
        # Bắt đầu Extend
        self.btn_extend_start = QPushButton("Chạy Extend")
        self.btn_extend_start.setFixedSize(118, 38)
        self.btn_extend_start.setObjectName("startButton")
        self.btn_extend_start.clicked.connect(self.on_extend_start)
        ext_btn_layout.addWidget(self.btn_extend_start)
        
        # Dừng Extend
        self.btn_extend_stop = QPushButton("Dừng")
        self.btn_extend_stop.setFixedSize(96, 38)
        self.btn_extend_stop.setObjectName("pauseButton")
        self.btn_extend_stop.setEnabled(False)
        self.btn_extend_stop.clicked.connect(self.on_extend_stop)
        ext_btn_layout.addWidget(self.btn_extend_stop)
        
        # Status label
        self.lbl_extend_status = QLabel("Sẵn sàng")
        self.lbl_extend_status.setStyleSheet("color: green; font-weight: bold;")
        ext_btn_layout.addWidget(self.lbl_extend_status)
        
        self.extend_control_frame.setVisible(False)
        layout.addWidget(self.extend_control_frame)
        
        # ===== EXTEND VIDEO PROJECT TABLE =====
        self.extend_projects_table = QTableWidget()
        self.extend_projects_table.setColumnCount(5)
        self.extend_projects_table.setHorizontalHeaderLabels([
            "Project", "Segments", "Trạng thái", "Tiến độ", "Thao tác"
        ])
        
        # Responsive column widths
        self.extend_projects_table.setColumnWidth(0, 120)
        self.extend_projects_table.setColumnWidth(1, 80)
        self.extend_projects_table.setColumnWidth(3, 100)  # Tiến độ: hiển thị "5/17"
        self.extend_projects_table.setColumnWidth(4, 100)
        
        # Stretch column 2 (Trạng thái) để fill width
        self.extend_projects_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        
        self.extend_projects_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.extend_projects_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.extend_projects_table.verticalHeader().setVisible(False)
        self.extend_projects_table.setVisible(False)
        self.extend_projects_table.setMaximumHeight(200)
        
        # Add click handler để hiển thị prompts của project được chọn
        self.extend_projects_table.itemClicked.connect(self.on_extend_project_clicked)
        
        layout.addWidget(self.extend_projects_table)
        
        # Info label (nếu chưa có)
        if not hasattr(self, 'lbl_extend_info'):
            self.lbl_extend_info = QLabel("📝 Chọn file TXT để bắt đầu")
            self.lbl_extend_info.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(self.lbl_extend_info)
        
        return widget

    def build_logs_panel(self):
        """BOTTOM: compact log panel."""
        widget = QWidget()
        widget.setMaximumHeight(156)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        logs_box = QGroupBox("Logs")
        logs_layout = QVBoxLayout()
        
        self.logs_display = QTextEdit()
        self.logs_display.setReadOnly(True)
        self.logs_display.setFont(QFont("Segoe UI", 10))
        self.logs_display.setObjectName("logsDisplay")
        self.logs_display.setMaximumHeight(132)
        self.logs_display.setPlaceholderText("Logs xử lý video sẽ hiển thị tại đây...")
        
        logs_layout.addWidget(self.logs_display)
        logs_box.setLayout(logs_layout)
        layout.addWidget(logs_box)
        
        return widget

    def switch_video_mode(self, mode):
        # ✅ FIX: So sánh đúng - mode là logic mode, cần convert button text sang logic mode để so sánh
        for btn in self.video_modes:
            btn_display_text = btn.text()
            btn_logic_mode = self.video_mode_display_to_logic.get(btn_display_text, btn_display_text)
            btn.setChecked(btn_logic_mode == mode)

        previous_mode = getattr(self, 'current_video_mode', None)
        if previous_mode:
            self.video_mode_grid_states[previous_mode] = self._capture_current_video_grid_state()
        
        self.current_video_mode = mode
        self._sync_video_prompt_table_columns(mode)
        
        # Show/hide input panels based on mode
        is_exp_ref = (mode == "Expand + Reference")
        is_t2v = (mode == "Text to Video")
        is_i2v = (mode == "Image to Video")
        is_se = (mode == "Start+End to Video")
        is_int = (mode == "Integrate to Video")
        is_ext = (mode == "Extend Video")
        
        if hasattr(self, 'input_group'):
            self.input_group.setVisible(True)
            title_map = {
                "Text to Video": "Văn bản thành Video",
                "Image to Video": "Ảnh thành Video",
                "Start+End to Video": "Đầu+Cuối thành Video",
                "Integrate to Video": "Tham chiếu thành Video",
                "Expand + Reference": "Tham chiếu thành Video",
                "Extend Video": "Nối Video",
            }
            self.input_group.setTitle(title_map.get(mode, "Nguồn dữ liệu"))

        if hasattr(self, 'video_mode_form_stack'):
            if is_t2v:
                self.video_mode_form_stack.setCurrentWidget(self.txt_t2v_frame)
            elif is_i2v:
                self.video_mode_form_stack.setCurrentWidget(self.txt_i2v_simple_frame)
            elif is_se:
                self.video_mode_form_stack.setCurrentWidget(self.txt_start_end_simple_frame)
            elif is_ext:
                self.video_mode_form_stack.setCurrentWidget(self.txt_extend_frame)
            else:
                self.video_mode_form_stack.setCurrentWidget(self.txt_integrate_simple_frame)
            current_page = self.video_mode_form_stack.currentWidget()
            if current_page is not None:
                page_hint = current_page.layout().sizeHint().height() if current_page.layout() else current_page.sizeHint().height()
                target_height = max(0, page_hint)
                self.video_mode_form_stack.setMaximumHeight(target_height)
                self.video_mode_form_stack.updateGeometry()

        if hasattr(self, 'video_batch_image_actions_frame'):
            show_any_image_actions = is_i2v or is_se or is_int or is_exp_ref
            self.video_batch_image_actions_frame.setVisible(show_any_image_actions)
            if hasattr(self, 'btn_video_add_all_images'):
                self.btn_video_add_all_images.setVisible(is_i2v)
            if hasattr(self, 'btn_video_add_all_start_images'):
                self.btn_video_add_all_start_images.setVisible(is_se)
            if hasattr(self, 'btn_video_add_all_end_images'):
                self.btn_video_add_all_end_images.setVisible(is_se)
            if hasattr(self, 'btn_video_add_all_reference_images'):
                self.btn_video_add_all_reference_images.setVisible(is_int or is_exp_ref)

        if hasattr(self, 'txt_integrate_frame') and (is_int or is_exp_ref) and hasattr(self, 'rb_integrate_default'):
            try:
                if self.rb_integrate_custom.isChecked():
                    self.integrate_default_frame.setVisible(False)
                    self.integrate_custom_frame.setVisible(True)
                else:
                    self.integrate_default_frame.setVisible(True)
                    self.integrate_custom_frame.setVisible(False)
            except Exception:
                if hasattr(self, 'integrate_default_frame'):
                    self.integrate_default_frame.setVisible(True)
                if hasattr(self, 'integrate_custom_frame'):
                    self.integrate_custom_frame.setVisible(False)
        
        # Show/hide Batch Job widgets
        if hasattr(self, 'batch_job_group'):
            uses_batch_sources = is_t2v or is_i2v or is_se or is_int or is_exp_ref
            self.batch_job_group.setVisible(uses_batch_sources)

            if hasattr(self, 'batch_file_widgets'):
                for widget in self.batch_file_widgets:
                    if widget:
                        widget.setVisible(uses_batch_sources)

            if hasattr(self, 'batch_folder_widgets'):
                for widget in self.batch_folder_widgets:
                    if widget:
                        widget.setVisible(uses_batch_sources)

            if hasattr(self, 'batch_table'):
                self.batch_table.setVisible(uses_batch_sources)

            if hasattr(self, 'batch_table_label'):
                self.batch_table_label.setVisible(uses_batch_sources)
        
        # Show/hide Extend Video controls và table
        if hasattr(self, 'extend_control_frame'):
            self.extend_control_frame.setVisible(is_ext)
            
        if hasattr(self, 'extend_projects_table'):
            # Chỉ show table nếu có data, ngược lại ẩn
            if is_ext and hasattr(self, 'extend_projects_data') and self.extend_projects_data:
                self.extend_projects_table.setVisible(True)
                self.log(f"📊 Hiển thị {len(self.extend_projects_data)} projects")
            else:
                # Ẩn table khi chưa có data hoặc không phải Extend mode
                if not is_ext:
                    self.extend_projects_table.setVisible(False)
        
        # Di chuyển hộp Thiết lập xuống dưới khi ở Extend mode để tăng không gian phần trên
        try:
            if hasattr(self, 'settings_box') and self.settings_box and hasattr(self, 'extend_control_frame'):
                parent_layout = self.settings_box.parent().layout()
                if parent_layout and is_ext:
                    parent_layout.removeWidget(self.settings_box)
                    parent_layout.addWidget(self.settings_box)
        except Exception:
            pass
        
        # Hide normal control buttons when in Extend mode
        if hasattr(self, 'normal_control_frame'):
            self.normal_control_frame.setVisible(not is_ext)
        
        # KHÔNG clear bảng - giữ nguyên data khi chuyển tab
        # User có thể chuyển qua lại giữa các mode
        self._restore_video_grid_state(self.video_mode_grid_states.get(mode))
        self._refresh_video_mode_media_previews()
        
        self.log(f"Mode: {mode}")

    def collect_tasks_for_current_mode(self):
        """Thu thập tasks dựa trên video mode hiện tại"""
        mode = self.current_video_mode
        tasks = []
        
        try:
            if mode == "Text to Video":
                # Removed DEBUG log
                
                # Text-to-Video: Ưu tiên Batch Job, fallback là single prompt
                
                # Check Batch Job table
                if self.batch_table.rowCount() > 0:
                    # Removed DEBUG log
                    self.log("📊 Đọc prompts từ Batch Job...")
                    
                    # Nếu có file TXT trong batch
                    txt_file_path = self.txt_file.text().strip()
                    batch_folder = self.batch_folder.text().strip()
                    
                    if txt_file_path and Path(txt_file_path).exists():
                        # Removed DEBUG log
                        
                        # ✅ Khởi tạo mappings nếu chưa có
                        if not hasattr(self, 'video_prompt_file_mapping'):
                            self.video_prompt_file_mapping = {}
                        if not hasattr(self, 'video_prompt_local_mapping'):
                            self.video_prompt_local_mapping = {}
                        
                        # Single file mode
                        txt_file = Path(txt_file_path)
                        file_stem = txt_file.stem
                        
                        with open(txt_file_path, 'r', encoding='utf-8') as f:
                            lines = [line.strip() for line in f if line.strip()]
                        
                        # Removed DEBUG log
                        
                        # ✅ Tạo mapping cho single file
                        for local_idx, line in enumerate(lines, 1):  # Local index bắt đầu từ 1
                            global_index = len(tasks) + 1
                            tasks.append(PromptTask(
                                prompt_text=line,
                                prompt_index=global_index,
                                output_folder=None
                            ))
                            
                            # ✅ Tạo mapping cho từng prompt
                            self.video_prompt_file_mapping[global_index] = file_stem
                            self.video_prompt_local_mapping[global_index] = local_idx
                            
                            # Set attributes cho task
                            tasks[-1].source_file = file_stem
                            tasks[-1].local_index = local_idx
                        
                        # Removed DEBUG log
                        self.log(f"✅ {len(lines)} prompts từ file: {txt_file.name}")
                        self.log(f"  📋 Đã tạo mapping: {len(self.video_prompt_file_mapping)} entries")
                    
                    elif batch_folder and Path(batch_folder).exists():
                        # ✅ Khởi tạo mappings nếu chưa có
                        if not hasattr(self, 'video_prompt_file_mapping'):
                            self.video_prompt_file_mapping = {}
                        if not hasattr(self, 'video_prompt_local_mapping'):
                            self.video_prompt_local_mapping = {}
                        
                        # Folder mode - đọc TẤT CẢ file .txt
                        txt_files = list(Path(batch_folder).glob("*.txt"))
                        txt_files = sorted(txt_files, key=lambda p: _alphanum_key(p.stem))
                        
                        self.log(f"📁 Xử lý {len(txt_files)} file .txt từ folder")
                        
                        global_index = 1
                        for file_idx, txt_file in enumerate(txt_files):
                            with open(txt_file, 'r', encoding='utf-8') as f:
                                lines = [line.strip() for line in f if line.strip()]
                            
                            file_stem = txt_file.stem
                            
                            # ✅ BUG FIX: DÙNG GLOBAL INDEX cho prompt_index để consistent với UI
                            for local_idx, line in enumerate(lines, 1):  # Local index bắt đầu từ 1
                                task = PromptTask(
                                    prompt_text=line,
                                    prompt_index=global_index,  # ✅ DÙNG GLOBAL INDEX để match với UI
                                    output_folder=file_stem  # Tên file làm folder
                                )
                                # ✅ Thêm attributes động để không break class definition
                                task.source_file = file_stem  # Thông tin file gốc
                                task.local_index = local_idx  # Lưu local index để display
                                tasks.append(task)
                                
                                # ✅ Tạo mapping cho từng prompt
                                self.video_prompt_file_mapping[global_index] = file_stem
                                self.video_prompt_local_mapping[global_index] = local_idx
                                
                                global_index += 1
                            
                            self.log(f"  ✅ {txt_file.name}: {len(lines)} prompts")
                        
                        self.log(f"  📋 Đã tạo mapping: {len(self.video_prompt_file_mapping)} entries cho {len(txt_files)} files")
                
                else:
                    # ❌ KHÔNG HỖ TRỢ SINGLE PROMPT - BẮT BUỘC DÙNG BATCH JOB
                    print("DEBUG: No batch data - User must use Batch Job")
                    self.log("⚠️ Vui lòng sử dụng Batch Job (file .txt hoặc folder)")
            
            elif mode == "Image to Video":
                # Image-to-Video tasks
                image_folder = self.txt_image_folder.text().strip()
                prompt_file = self.txt_image_prompt_file.text().strip()
                prompt_folder = self.txt_image_prompt_folder.text().strip()
                root_folder = self.txt_image_root_folder.text().strip()
                
                # Lấy output folder từ UI
                output_folder = self.output_folder.text().strip() if self.output_folder.text().strip() else str(Path.home() / "Downloads")
                row_tasks = self._build_i2v_tasks_from_row_images(output_folder)
                if row_tasks and any(isinstance(t, ImageTask) for t in row_tasks):
                    self.log(f"✅ {len(row_tasks)} Image-to-Video tasks từ ảnh theo từng dòng trong bảng")
                    return row_tasks
                
                # ✅ MODE 3: Folder gốc (file .txt + folder ảnh trùng tên)
                if root_folder and Path(root_folder).exists() and hasattr(self, "rb_i2v_mode_root_match") and self.rb_i2v_mode_root_match.isChecked():
                    root_path = Path(root_folder)
                    txt_files = sorted(root_path.glob("*.txt"), key=lambda p: _alphanum_key(p.stem))
                    if not txt_files:
                        QMessageBox.warning(self, "Cảnh báo", f"Folder '{root_folder}' không chứa file .txt nào!")
                        return []
                    
                    self.log(f"📁 I2V Root Mode: {len(txt_files)} file .txt trong folder gốc")
                    
                    if not hasattr(self, 'i2v_task_mapping'):
                        self.i2v_task_mapping = {}
                    else:
                        self.i2v_task_mapping.clear()
                    
                    global_task_idx = 1
                    for txt_file in txt_files:
                        file_stem = txt_file.stem
                        img_folder = root_path / file_stem
                        if not img_folder.is_dir():
                            self.log(f"⚠️ Bỏ qua '{txt_file.name}': không tìm thấy folder ảnh '{file_stem}'")
                            continue
                        
                        # Collect images trong folder trùng tên
                        image_paths = []
                        for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']:
                            image_paths.extend(img_folder.glob(ext))
                        image_paths = natural_sort_paths(image_paths)
                        if not image_paths:
                            self.log(f"⚠️ Bỏ qua '{txt_file.name}': folder '{file_stem}' không có ảnh")
                            continue
                        
                        # Load prompts từ file txt
                        try:
                            with open(txt_file, 'r', encoding='utf-8') as f:
                                prompts = [line.strip() for line in f if line.strip()]
                        except Exception as e:
                            self.log(f"⚠️ Lỗi đọc {txt_file.name}: {e}")
                            continue
                        
                        if not prompts:
                            self.log(f"⚠️ Bỏ qua '{txt_file.name}': không có prompt hợp lệ")
                            continue
                        
                        # Output folder cho từng txt = output_folder / stem
                        file_output_folder = Path(output_folder) / file_stem
                        file_output_folder.mkdir(parents=True, exist_ok=True)
                        
                        num_tasks = min(len(image_paths), len(prompts))
                        for local_idx in range(num_tasks):
                            img_path = image_paths[local_idx]
                            prompt_text = prompts[local_idx] if local_idx < len(prompts) else prompts[-1]
                            
                            task = ImageTask(
                                image_path=str(img_path),
                                prompt_text=prompt_text,
                                task_index=global_task_idx
                            )
                            tasks.append(task)
                            
                            # Lưu mapping cho retry
                            self.i2v_task_mapping[global_task_idx] = {
                                "image_path": str(img_path),
                                "prompt": prompt_text,
                                "source_file": file_stem,
                                "local_index": local_idx + 1,
                                "output_folder": str(file_output_folder)
                            }
                            
                            global_task_idx += 1
                        
                        self.log(f"  ✅ {txt_file.name}: {num_tasks} tasks (ảnh: {len(image_paths)}, prompts: {len(prompts)}, output: {file_output_folder})")
                    
                    self.log(f"✅ {len(tasks)} Image-to-Video tasks từ {len(txt_files)} cặp txt + folder ảnh trùng tên")
                    return tasks
                
                # Collect images (Mode 1 & 2)
                image_paths = []
                if image_folder and Path(image_folder).exists():
                    folder_path = Path(image_folder)
                    for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']:
                        image_paths.extend(folder_path.glob(ext))
                    image_paths = natural_sort_paths(image_paths)
                
                if not image_paths:
                    QMessageBox.warning(self, "Cảnh báo", "Cần chọn thư mục ảnh cho Image-to-Video!")
                    return []
                
                # ✅ Hỗ trợ cả file txt đơn lẻ và thư mục chứa nhiều file txt
                if prompt_folder and Path(prompt_folder).exists():
                    # Folder mode - xử lý nhiều file .txt
                    txt_files = list(Path(prompt_folder).glob("*.txt"))
                    txt_files = sorted(txt_files, key=lambda p: _alphanum_key(p.stem))
                    
                    if not txt_files:
                        QMessageBox.warning(self, "Cảnh báo", f"Thư mục '{prompt_folder}' không chứa file .txt nào!")
                        return []
                    
                    self.log(f"📁 Xử lý {len(txt_files)} file .txt từ folder cho I2V")
                    
                    # Xử lý từng file .txt
                    global_task_idx = 1
                    for txt_file in txt_files:
                        file_stem = txt_file.stem
                        
                        # Load prompts từ file này
                        with open(txt_file, 'r', encoding='utf-8') as f:
                            prompts = [line.strip() for line in f if line.strip()]
                        
                        if not prompts:
                            self.log(f"⚠️ File {txt_file.name} không có prompt hợp lệ, bỏ qua")
                            continue
                        
                        # Tạo tasks cho file này (mỗi ảnh = 1 prompt theo thứ tự)
                        # Output folder cho file này = output_folder / file_stem
                        file_output_folder = Path(output_folder) / file_stem
                        file_output_folder.mkdir(parents=True, exist_ok=True)
                        
                        # Số ảnh cho file này = số prompts (hoặc tất cả ảnh nếu prompts ít hơn)
                        num_images_for_file = min(len(image_paths), len(prompts))
                        
                        for local_idx in range(num_images_for_file):
                            img_path = image_paths[local_idx]
                            prompt_text = prompts[local_idx] if local_idx < len(prompts) else prompts[-1]
                            
                            task = ImageTask(
                                image_path=str(img_path),
                                prompt_text=prompt_text,
                                task_index=global_task_idx
                            )
                            tasks.append(task)
                            
                            # Lưu mapping cho retry
                            self.i2v_task_mapping[global_task_idx] = {
                                "image_path": str(img_path),
                                "prompt": prompt_text,
                                "source_file": file_stem,
                                "local_index": local_idx + 1,
                                "output_folder": str(file_output_folder)
                            }
                            
                            global_task_idx += 1
                        
                        # Lưu output folder mapping
                        self.i2v_file_output_mapping[file_stem] = file_output_folder
                        
                        self.log(f"  ✅ {txt_file.name}: {num_images_for_file} tasks (output: {file_output_folder})")
                    
                    self.log(f"✅ {len(tasks)} Image-to-Video tasks từ {len(txt_files)} file .txt")
                
                elif prompt_file and Path(prompt_file).exists():
                    # Single file mode
                    prompt_file_stem = Path(prompt_file).stem
                    
                    # Load prompts
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        prompts = [line.strip() for line in f if line.strip()]
                    
                    if not prompts:
                        QMessageBox.warning(self, "Cảnh báo", "File prompt không có nội dung hợp lệ!")
                        return []
                    
                    # Create tasks (1 ảnh = 1 prompt theo thứ tự)
                    for idx, img_path in enumerate(image_paths, 1):
                        prompt_idx = (idx - 1) % len(prompts) if prompts else 0
                        prompt_text = prompts[prompt_idx] if prompts else "Default"
                        task = ImageTask(
                            image_path=str(img_path),
                            prompt_text=prompt_text,
                            task_index=idx
                        )
                        tasks.append(task)
                    
                        # Lưu mapping cho retry
                        self.i2v_task_mapping[idx] = {
                            "image_path": str(img_path),
                            "prompt": prompt_text,
                            "source_file": prompt_file_stem,
                            "local_index": prompt_idx + 1,
                            "output_folder": output_folder  # Lưu output folder từ UI
                        }
                    # Lưu output folder mapping
                    self.i2v_file_output_mapping[prompt_file_stem] = Path(output_folder)
                
                    self.log(f"✅ {len(tasks)} Image-to-Video tasks từ 1 file .txt (output: {output_folder})")
                    
                else:
                    QMessageBox.warning(self, "Cảnh báo", "Cần chọn file prompt hoặc thư mục chứa file .txt cho Image-to-Video!")
                    return []
            
            elif mode == "Start+End to Video":
                # Start+End tasks: hỗ trợ 2 mode
                # - 2 ảnh / 1 prompt (cũ)
                # - Nối frame: (1,2), (2,3), (3,4), ...
                row_tasks = self._build_start_end_tasks_from_row_images()
                if row_tasks and any(isinstance(t, ImageTask) for t in row_tasks):
                    self.log(f"✅ {len(row_tasks)} Start+End tasks từ ảnh theo từng dòng trong bảng")
                    return row_tasks

                se_folder = self.txt_start_end_folder.text().strip()
                prompt_file = self.txt_start_end_prompt.text().strip()
                
                if not se_folder or not Path(se_folder).exists():
                    QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn thư mục ảnh Start+End!")
                    return []
                
                if not prompt_file or not Path(prompt_file).exists():
                    QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn file prompt!")
                    return []
                
                # Load prompts
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    prompts = [line.strip() for line in f if line.strip()]
                
                # Collect images
                image_paths = []
                for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']:
                    image_paths.extend(Path(se_folder).glob(ext))
                image_paths = natural_sort_paths(image_paths)
                
                if len(image_paths) < 2:
                    QMessageBox.warning(self, "Cảnh báo", "Cần ít nhất 2 ảnh (start + end)!")
                    return []
                
                # Xác định mode: pair (1+2, 3+4, ...) hay chain (1-2, 2-3, ...)
                use_chain_mode = hasattr(self, "rb_start_end_chain") and self.rb_start_end_chain.isChecked()
                
                if not prompts:
                    QMessageBox.warning(self, "Cảnh báo", "File prompt trống!")
                    return []
                
                if use_chain_mode:
                    # Nối frame: (1,2), (2,3), (3,4), ...
                    task_idx = len(tasks) + 1
                    for i in range(0, len(image_paths) - 1):
                        start_img = image_paths[i]
                        end_img = image_paths[i + 1]
                        prompt_idx = (task_idx - 1) % len(prompts)
                        prompt_text = prompts[prompt_idx]
                        
                        tasks.append(ImageTask(
                            image_path=str(start_img),
                            prompt_text=prompt_text,
                            task_index=task_idx,
                            end_image_path=str(end_img)  # End image
                        ))
                        task_idx += 1
                    
                    self.log(f"✅ {len(tasks)} Start+End tasks (mode NỐI FRAME, {len(image_paths)} ảnh)")
                else:
                    # Mode cũ: 2 ảnh / 1 prompt: (1,2) → dòng 1, (3,4) → dòng 2...
                    for i in range(0, len(image_paths) - 1, 2):
                        if i + 1 < len(image_paths):
                            start_img = image_paths[i]
                            end_img = image_paths[i + 1]
                            prompt_idx = len(tasks) % len(prompts) if prompts else 0
                            prompt_text = prompts[prompt_idx] if prompts else "Default"
                            
                            tasks.append(ImageTask(
                                image_path=str(start_img),
                                prompt_text=prompt_text,
                                task_index=len(tasks) + 1,
                                end_image_path=str(end_img)  # End image
                            ))
                    
                    self.log(f"✅ {len(tasks)} Start+End tasks (mode 2 ẢNH/1 PROMPT, {len(image_paths)} ảnh)")
            
            elif mode == "Integrate to Video":
                row_tasks = self._build_integrate_tasks_from_row_images("Integrate to Video")
                if row_tasks and any(getattr(task, 'integrate_images', None) for task in row_tasks):
                    self.log(f"✅ {len(row_tasks)} Integrate tasks từ ảnh tham chiếu theo từng dòng trong bảng")
                    return row_tasks

                # ✅ Kiểm tra chế độ: Mặc Định hoặc Tùy Chỉnh
                is_custom_mode = False
                try:
                    if hasattr(self, 'rb_integrate_custom') and self.rb_integrate_custom.isChecked():
                        is_custom_mode = True
                except:
                    pass
                
                if is_custom_mode:
                    # ✅ TÙY CHỈNH MODE: Dùng AI matching results
                    prompt_file = self.txt_integrate_custom_prompt_file.text().strip()
                    
                    if not prompt_file or not Path(prompt_file).exists():
                        QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn file prompt!")
                        return []
                    
                    # ✅ Cho phép chạy dù chưa có AI matching (có thể chỉnh thủ công)
                    if not self.character_matching_results:
                        self.log("ℹ️ Chưa có kết quả AI Phân Tích, sẽ dùng danh sách nhân vật trống (chỉnh thủ công).")
                        self.character_matching_results = {}
                    
                    # Load prompts (dùng prompts đã chỉnh sửa nếu có)
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        prompts = [line.strip() for line in f if line.strip()]
                    
                    if not prompts:
                        QMessageBox.warning(self, "Cảnh báo", "File prompt trống!")
                        return []
                    
                    # Dùng prompts đã chỉnh sửa nếu có
                    if hasattr(self, 'custom_prompts') and self.custom_prompts:
                        for idx, original_prompt in enumerate(prompts, 1):
                            if idx in self.custom_prompts:
                                prompts[idx - 1] = self.custom_prompts[idx]
                    
                    # Validate custom_characters (cho phép trống nhưng cảnh báo nhẹ)
                    if not self.custom_characters:
                        self.log("ℹ️ Chưa import nhân vật, sẽ không gán ảnh tự động. Bạn có thể chỉnh thủ công trong dialog.")
                        self.custom_characters = {}
                    
                    self.log(f"📊 Custom Mode: {len(prompts)} prompts, {len(self.custom_characters)} nhân vật")
                    
                    # ✅ BUG FIX: Tạo task cho TẤT CẢ prompts, không bỏ qua prompt nào
                    # Nếu prompt có matching → tạo task với integrate_images (Integrate mode)
                    # Nếu prompt không có matching → tạo task không có integrate_images (sẽ tự động chuyển sang Text-to-Video)
                    task_idx = 1
                    for prompt_idx, prompt_text in enumerate(prompts, 1):
                        # Lấy danh sách characters được match (chỉ lấy những nhân vật đã được check trong dialog)
                        matched_chars = self.character_matching_results.get(prompt_idx, [])
                        
                        # Đảm bảo matched_chars là list
                        if not isinstance(matched_chars, list):
                            matched_chars = list(matched_chars) if matched_chars else []
                        
                        # Tạo task cho prompt này (luôn tạo, không bỏ qua)
                        task = PromptTask(
                            prompt_text=prompt_text,
                            prompt_index=task_idx,
                            output_folder=None
                        )
                        # Đánh dấu là custom mode
                        task.is_custom_integrate = True
                        
                        # Nếu có matching characters → thêm integrate_images
                        if matched_chars and len(matched_chars) > 0:
                            # Validation: tối đa 3 ảnh mỗi prompt
                            if len(matched_chars) > 3:
                                self.log(f"⚠️ Prompt {prompt_idx}: Có {len(matched_chars)} characters, chỉ lấy 3 đầu tiên")
                                matched_chars = matched_chars[:3]
                            
                            # Lấy đường dẫn ảnh của các characters được match
                            group_images = []
                            for char_name in matched_chars:
                                if char_name in self.custom_characters:
                                    img_path = self.custom_characters[char_name]
                                    if Path(img_path).exists():
                                        group_images.append(Path(img_path))
                                    else:
                                        self.log(f"⚠️ Ảnh không tồn tại: {img_path}")
                            
                            if group_images:
                                # Có ảnh hợp lệ → thêm integrate_images (sẽ dùng Integrate mode)
                                task.integrate_images = [str(img) for img in group_images]
                                tasks.append(task)
                                
                                # ✅ Lưu vào integrate_task_mapping để dùng lại khi retry
                                if not hasattr(self, 'integrate_task_mapping'):
                                    self.integrate_task_mapping = {}
                                self.integrate_task_mapping[task_idx] = {
                                    'prompt': prompt_text,
                                    'integrate_images': list(task.integrate_images),
                                    'output_folder': None,
                                    'is_custom_integrate': True
                                }
                                
                                task_idx += 1
                                self.log(f"✅ Prompt {prompt_idx}: {len(group_images)} nhân vật ({', '.join(matched_chars)}) - Integrate mode")
                            else:
                                # Không có ảnh hợp lệ → không thêm integrate_images (sẽ tự động chuyển sang Text-to-Video)
                                tasks.append(task)
                                task_idx += 1
                                self.log(f"📝 Prompt {prompt_idx}: Không có ảnh hợp lệ - sẽ dùng Text-to-Video")
                        else:
                            # Không có matching → không thêm integrate_images (sẽ tự động chuyển sang Text-to-Video)
                            tasks.append(task)
                            task_idx += 1
                            self.log(f"📝 Prompt {prompt_idx}: Không có nhân vật được check - sẽ dùng Text-to-Video")
                    
                    self.log(f"✅ {len(tasks)} Custom Integrate tasks (bao gồm cả prompts không có matching)")
                    
                else:
                    # ✅ MẶC ĐỊNH MODE: Logic cũ (giữ nguyên)
                    int_folder = self.txt_integrate_images_folder.text().strip()
                    prompt_file = self.txt_integrate_prompt_file.text().strip()
                    
                    if not int_folder or not Path(int_folder).exists():
                        QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn thư mục ảnh!")
                        return []
                    
                    if not prompt_file or not Path(prompt_file).exists():
                        QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn file prompt!")
                        return []
                    
                    # Load prompts
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        prompts = [line.strip() for line in f if line.strip()]
                    
                    # Get images per group
                    try:
                        images_per_group = int(self.combo_integrate_images_per_group.currentText())
                    except:
                        images_per_group = 1
                    
                    # Collect images (sorted by number prefix)
                    image_paths = []
                    for file in sorted(Path(int_folder).iterdir()):
                        if file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp']:
                            image_paths.append(file)
                    
                    # Natural sort
                    image_paths = natural_sort_paths(image_paths)
                    
                    self.log(f"📊 {len(image_paths)} ảnh, {images_per_group} ảnh/nhóm, {len(prompts)} prompts")
                    
                    # Create tasks: nhóm ảnh theo images_per_group
                    task_idx = 1
                    for prompt_idx, prompt_text in enumerate(prompts):
                        # Tính ảnh nào thuộc nhóm này
                        start_img_idx = prompt_idx * images_per_group
                        end_img_idx = start_img_idx + images_per_group
                        
                        group_images = image_paths[start_img_idx:end_img_idx]
                        
                        if group_images:
                            # Store nhóm ảnh trong task (dùng list paths)
                            task = PromptTask(
                                prompt_text=prompt_text,
                                prompt_index=task_idx,
                                output_folder=None
                            )
                            # Thêm thông tin nhóm ảnh
                            task.integrate_images = [str(img) for img in group_images]
                            tasks.append(task)
                            
                            # ✅ Lưu vào integrate_task_mapping để dùng lại khi retry
                            if not hasattr(self, 'integrate_task_mapping'):
                                self.integrate_task_mapping = {}
                            self.integrate_task_mapping[task_idx] = {
                                'prompt': prompt_text,
                                'integrate_images': list(task.integrate_images),
                                'output_folder': None,
                                'is_custom_integrate': False
                            }
                            
                            task_idx += 1
                    
                    self.log(f"✅ {len(tasks)} Integrate tasks")
            
            elif mode == "Expand + Reference":
                row_tasks = self._build_integrate_tasks_from_row_images("Expand + Reference")
                if row_tasks and any(getattr(task, 'integrate_images', None) for task in row_tasks):
                    self.log(f"✅ {len(row_tasks)} Expand + Reference tasks từ ảnh tham chiếu theo từng dòng trong bảng")
                    return row_tasks

                # ✅ Expand + Reference mode: Dùng logic tương tự Integrate to Video
                # Nhưng sẽ tạo nhiều video bằng integrate to video, lấy mediaGenerationId, concat và download
                
                # ✅ Kiểm tra chế độ: Mặc Định hoặc Tùy Chỉnh
                is_custom_mode = False
                try:
                    if hasattr(self, 'rb_integrate_custom') and self.rb_integrate_custom.isChecked():
                        is_custom_mode = True
                except:
                    pass
                
                if is_custom_mode:
                    # ✅ TÙY CHỈNH MODE: Dùng matching results (có thể từ AI hoặc chỉnh tay)
                    prompt_file = self.txt_integrate_custom_prompt_file.text().strip()
                    
                    if not prompt_file or not Path(prompt_file).exists():
                        QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn file prompt trong cấu hình tùy chỉnh!")
                        return []
                    
                    # Không bắt buộc phải có kết quả AI trước; nếu chưa có thì khởi tạo rỗng
                    if not hasattr(self, 'character_matching_results') or self.character_matching_results is None:
                        self.character_matching_results = {}
                    
                    # Load prompts (dùng prompts đã chỉnh sửa nếu có)
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        prompts = [line.strip() for line in f if line.strip()]
                    
                    if not prompts:
                        QMessageBox.warning(self, "Cảnh báo", "File prompt trống!")
                        return []
                    
                    # Dùng prompts đã chỉnh sửa nếu có
                    if hasattr(self, 'custom_prompts') and self.custom_prompts:
                        for idx, original_prompt in enumerate(prompts, 1):
                            if idx in self.custom_prompts:
                                prompts[idx - 1] = self.custom_prompts[idx]
                    
                    # Validate custom_characters
                    if not self.custom_characters:
                        QMessageBox.warning(self, "Cảnh báo", "Vui lòng import nhân vật!")
                        return []
                    
                    self.log(f"📊 Expand + Reference Custom Mode: {len(prompts)} prompts, {len(self.custom_characters)} nhân vật")
                    
                    # Tạo task cho TẤT CẢ prompts
                    task_idx = 1
                    for prompt_idx, prompt_text in enumerate(prompts, 1):
                        # Lấy danh sách characters được match
                        matched_chars = self.character_matching_results.get(prompt_idx, [])
                        
                        # Đảm bảo matched_chars là list
                        if not isinstance(matched_chars, list):
                            matched_chars = list(matched_chars) if matched_chars else []
                        
                        # Tạo task cho prompt này
                        task = PromptTask(
                            prompt_text=prompt_text,
                            prompt_index=task_idx,
                            output_folder=None
                        )
                        # Đánh dấu là custom mode và expand + reference
                        task.is_custom_integrate = True
                        task.is_expand_reference = True
                        
                        # Nếu có matching characters → thêm integrate_images
                        if matched_chars and len(matched_chars) > 0:
                            # Validation: tối đa 3 ảnh mỗi prompt
                            if len(matched_chars) > 3:
                                self.log(f"⚠️ Prompt {prompt_idx}: Có {len(matched_chars)} characters, chỉ lấy 3 đầu tiên")
                                matched_chars = matched_chars[:3]
                            
                            # Lấy đường dẫn ảnh của các characters được match
                            group_images = []
                            for char_name in matched_chars:
                                if char_name in self.custom_characters:
                                    img_path = self.custom_characters[char_name]
                                    if Path(img_path).exists():
                                        group_images.append(Path(img_path))
                                    else:
                                        self.log(f"⚠️ Ảnh không tồn tại: {img_path}")
                            
                            if group_images:
                                # Có ảnh hợp lệ → thêm integrate_images
                                task.integrate_images = [str(img) for img in group_images]
                                tasks.append(task)
                                
                                # ✅ LƯU NGAY VÀO expand_reference_task_mapping để không bị mất khi retry
                                if not hasattr(self, 'expand_reference_task_mapping'):
                                    self.expand_reference_task_mapping = {}
                                self.expand_reference_task_mapping[task_idx] = {
                                    'prompt': prompt_text,
                                    'integrate_images': list(task.integrate_images),
                                    'is_expand_reference': True,
                                    'is_custom_integrate': True
                                }
                                
                                task_idx += 1
                                self.log(f"✅ Prompt {prompt_idx}: {len(group_images)} nhân vật ({', '.join(matched_chars)}) - Expand + Reference")
                            else:
                                # Không có ảnh hợp lệ → không thêm integrate_images (sẽ tự động chuyển sang Text-to-Video)
                                tasks.append(task)
                                task_idx += 1
                                self.log(f"📝 Prompt {prompt_idx}: Không có ảnh hợp lệ - sẽ dùng Text-to-Video")
                        else:
                            # Không có matching → không thêm integrate_images (sẽ tự động chuyển sang Text-to-Video)
                            tasks.append(task)
                            task_idx += 1
                            self.log(f"📝 Prompt {prompt_idx}: Không có nhân vật được check - sẽ dùng Text-to-Video")
                    
                    self.log(f"✅ {len(tasks)} Expand + Reference Custom tasks")
                    
                else:
                    # ✅ MẶC ĐỊNH MODE: Logic cũ + mode mới (Folder Prompts + Nhân vật cố định)
                    int_folder = self.txt_integrate_images_folder.text().strip()
                    prompt_file = self.txt_integrate_prompt_file.text().strip()
                    
                    # ✅ CHECK MODE MỚI: Folder Prompts + Nhân vật cố định
                    expand_ref_folder = ""
                    expand_ref_fixed_images = []
                    if hasattr(self, 'txt_expand_ref_folder_prompts'):
                        expand_ref_folder = self.txt_expand_ref_folder_prompts.text().strip()
                    if hasattr(self, 'expand_ref_fixed_images_paths'):
                        expand_ref_fixed_images = list(self.expand_ref_fixed_images_paths)
                    
                    # ✅ MODE MỚI: Folder Prompts + Nhân vật cố định
                    if expand_ref_folder and Path(expand_ref_folder).exists() and len(expand_ref_fixed_images) > 0:
                        # Validate ảnh
                        valid_fixed_images = [img for img in expand_ref_fixed_images if Path(img).exists()]
                        if not valid_fixed_images:
                            QMessageBox.warning(self, "Cảnh báo", "Không có ảnh nhân vật hợp lệ!")
                            return []
                        
                        # Đọc tất cả file .txt trong folder
                        txt_files = list(Path(expand_ref_folder).glob("*.txt"))
                        txt_files = sorted(txt_files, key=lambda p: _alphanum_key(p.stem))
                        
                        if not txt_files:
                            QMessageBox.warning(self, "Cảnh báo", f"Không tìm thấy file .txt nào trong: {expand_ref_folder}")
                            return []
                        
                        global_index = 1
                        for txt_file in txt_files:
                            with open(txt_file, 'r', encoding='utf-8') as f:
                                lines = [line.strip() for line in f if line.strip()]
                            
                            file_stem = txt_file.stem
                            
                            for local_idx, line in enumerate(lines, 1):
                                task = PromptTask(
                                    prompt_text=line,
                                    prompt_index=global_index,
                                    output_folder=file_stem
                                )
                                task.source_file = file_stem
                                task.local_index = local_idx
                                task.is_expand_reference = True
                                # ✅ GÁN ẢNH CỐ ĐỊNH CHO TẤT CẢ PROMPTS
                                task.integrate_images = valid_fixed_images[:3]  # Tối đa 3 ảnh
                                tasks.append(task)
                                
                                # ✅ LƯU NGAY VÀO expand_reference_task_mapping để không bị mất khi retry
                                if not hasattr(self, 'expand_reference_task_mapping'):
                                    self.expand_reference_task_mapping = {}
                                self.expand_reference_task_mapping[global_index] = {
                                    'prompt': line,
                                    'integrate_images': list(task.integrate_images),
                                    'is_expand_reference': True
                                }
                                
                                global_index += 1
                        
                        self.log(f"✅ {len(tasks)} Expand + Reference tasks từ {len(txt_files)} files với {len(valid_fixed_images)} ảnh nhân vật cố định")
                    
                    # ✅ LOGIC CŨ: Nếu không có integrate folder, thử dùng batch job (file TXT)
                    elif not int_folder or not Path(int_folder).exists():
                        # Fallback: dùng batch job như Text to Video
                        txt_file_path = self.txt_file.text().strip()
                        batch_folder = self.batch_folder.text().strip()
                        
                        if txt_file_path and Path(txt_file_path).exists():
                            txt_file = Path(txt_file_path)
                            file_stem = txt_file.stem
                            
                            with open(txt_file_path, 'r', encoding='utf-8') as f:
                                lines = [line.strip() for line in f if line.strip()]
                            
                            for local_idx, line in enumerate(lines, 1):
                                global_index = len(tasks) + 1
                                task = PromptTask(
                                    prompt_text=line,
                                    prompt_index=global_index,
                                    output_folder=None
                                )
                                task.source_file = file_stem
                                task.local_index = local_idx
                                task.is_expand_reference = True  # Đánh dấu là expand + reference mode
                                tasks.append(task)
                            
                            self.log(f"✅ {len(tasks)} Expand + Reference tasks từ file: {txt_file.name}")
                        elif batch_folder and Path(batch_folder).exists():
                            txt_files = list(Path(batch_folder).glob("*.txt"))
                            txt_files = sorted(txt_files, key=lambda p: _alphanum_key(p.stem))
                            
                            global_index = 1
                            for txt_file in txt_files:
                                with open(txt_file, 'r', encoding='utf-8') as f:
                                    lines = [line.strip() for line in f if line.strip()]
                                
                                file_stem = txt_file.stem
                                
                                for local_idx, line in enumerate(lines, 1):
                                    task = PromptTask(
                                        prompt_text=line,
                                        prompt_index=global_index,
                                        output_folder=file_stem
                                    )
                                    task.source_file = file_stem
                                    task.local_index = local_idx
                                    task.is_expand_reference = True
                                    tasks.append(task)
                                    global_index += 1
                            
                            self.log(f"✅ {len(tasks)} Expand + Reference tasks từ {len(txt_files)} files")
                        else:
                            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn thư mục ảnh hoặc file/folder batch job!")
                            return []
                    else:
                        # Có integrate folder - dùng logic integrate to video
                        if not prompt_file or not Path(prompt_file).exists():
                            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn file prompt!")
                            return []
                        
                        with open(prompt_file, 'r', encoding='utf-8') as f:
                            prompts = [line.strip() for line in f if line.strip()]
                        
                        try:
                            images_per_group = int(self.combo_integrate_images_per_group.currentText())
                        except:
                            images_per_group = 1
                        
                        image_paths = []
                        for file in sorted(Path(int_folder).iterdir()):
                            if file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp']:
                                image_paths.append(file)
                        
                        image_paths = natural_sort_paths(image_paths)
                        
                        task_idx = 1
                        for prompt_idx, prompt_text in enumerate(prompts):
                            start_img_idx = prompt_idx * images_per_group
                            end_img_idx = start_img_idx + images_per_group
                            group_images = image_paths[start_img_idx:end_img_idx]
                            
                            if group_images:
                                task = PromptTask(
                                    prompt_text=prompt_text,
                                    prompt_index=task_idx,
                                    output_folder=None
                                )
                                task.integrate_images = [str(img) for img in group_images]
                                task.is_expand_reference = True
                                tasks.append(task)
                                
                                # ✅ LƯU NGAY VÀO expand_reference_task_mapping để không bị mất khi retry
                                if not hasattr(self, 'expand_reference_task_mapping'):
                                    self.expand_reference_task_mapping = {}
                                self.expand_reference_task_mapping[task_idx] = {
                                    'prompt': prompt_text,
                                    'integrate_images': list(task.integrate_images),
                                    'is_expand_reference': True
                                }
                                
                                task_idx += 1
                        
                        self.log(f"✅ {len(tasks)} Expand + Reference tasks")
        
        except Exception as e:
            print(f"DEBUG: Exception in collect_tasks: {e}")
            import traceback
            traceback.print_exc()
            self.log(f"❌ Lỗi collect tasks: {e}")
            QMessageBox.critical(self, "Lỗi", f"Lỗi thu thập tasks: {e}")
            return []
        
        print(f"DEBUG: Returning {len(tasks)} tasks")
        return tasks

    def run_processing_worker(self, tasks, model, num_videos, aspect, output_folder):
        """Worker thread xử lý tasks - NỐI ĐUÔI với max concurrent = số cookie × 1 (✅ Đã sửa từ ×3 → ×1)
        
        ═══════════════════════════════════════════════════════════════
        🎯 QUY TRÌNH MỚI: Nối đuôi với ThreadPoolExecutor
        ═══════════════════════════════════════════════════════════════
        
        1️⃣ MAX CONCURRENT = SỐ COOKIE × 1 (✅ Đã sửa từ ×3 → ×1):
           - Ví dụ: 3 cookies → 3 công việc đồng thời
           - ThreadPoolExecutor với max_workers = num_cookies × 1
        
        2️⃣ NỐI ĐUÔI (Queue-based):
           - Đưa max prompts vào hàng đợi
           - Cứ 1 prompt chạy xong → bổ sung 1 prompt khác vào
           - Không vượt quá số cookie × 3
        
        3️⃣ COOKIE MANAGEMENT:
           - Chọn cookie available (không còn round-robin cố định)
           - Nếu cookie bị 429 → đợi 6s → chuyển cookie khác
           - Nếu lỗi khác → retry 6 lần với cùng cookie
        
        4️⃣ KHÔNG DELAY:
           - Bỏ delay giữa các prompt (nối đuôi liên tục)
        ═══════════════════════════════════════════════════════════════
        """
        print(f"DEBUG: Worker thread STARTED with {len(tasks)} tasks")
        
        try:
            self.log(f"🔄 Bắt đầu xử lý {len(tasks)} tasks...")
            self._reset_delay_state()
            
            # ✅ Lấy mode từ current_video_mode
            mode = getattr(self, "current_video_mode", "Text to Video")
            
            # ✅ Số công việc đồng thời:
            #    - Text to Video  = 720P: 3/cookie, 1080P/4K: 1/cookie
            #    - Các mode khác  = số cookie × 1 (nặng, tránh overload)
            num_cookies = len(self.cookies_list) if self.cookies_list else 1
            if mode == "Text to Video":
                per_cookie_concurrent = self._get_t2v_concurrency_per_cookie()
                max_concurrent = max(1, num_cookies * per_cookie_concurrent)
                upscale_label = self.combo_upscale.currentText() if hasattr(self, "combo_upscale") and self.combo_upscale else "720P"
                self.log(
                    f"⚙️ Chế độ: Nối đuôi với {max_concurrent} công việc đồng thời "
                    f"({num_cookies} cookie(s) × {per_cookie_concurrent} - Text to Video {upscale_label})"
                )
            else:
                max_concurrent = num_cookies * 1
                self.log(f"⚙️ Chế độ: Nối đuôi với {max_concurrent} công việc đồng thời ({num_cookies} cookie(s) × 1 - {mode})")
            self.log(f"🔑 Sử dụng {num_cookies} cookie(s)")
            # ✅ BỎ DELAY - Không còn delay giữa các prompt
            # self.log(f"⏱️ Delay giữa các prompt: {delay_value}s")  # Comment lại
            
            # Build clients cho tất cả cookies (chỉ để validate, không dùng trực tiếp)
            # Clients sẽ được build lại trong process_single_text_task khi cần
            self._init_cookie_status()
            for cookie_idx in range(num_cookies):
                cookie_client = self.build_client(cookie_idx)
                if cookie_client and cookie_client.fetch_access_token():
                    self.log(f"✅ Cookie #{cookie_idx + 1} sẵn sàng")
                else:
                    self.log(f"⚠️ Cookie #{cookie_idx + 1} không thể khởi tạo")
                
            mode = self.current_video_mode
            
            # ✅ Thread-safe cookie counter cho round-robin (SHARED giữa tất cả tasks)
            import threading
            from collections import Counter
            if not hasattr(self, '_text_video_cookie_lock'):
                self._text_video_cookie_lock = threading.Lock()
            if not hasattr(self, '_text_video_cookie_counter'):
                self._text_video_cookie_counter = Counter()
            
            # ✅ CHỈ XỬ LÝ TEXT TO VIDEO TRƯỚC
            if mode == "Text to Video":
                # Dùng ThreadPoolExecutor với max_workers theo upscale hiện tại
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                upscale_label = self.combo_upscale.currentText() if hasattr(self, "combo_upscale") and self.combo_upscale else "720P"
                self.log(
                    f"🚀 Bắt đầu xử lý {len(tasks)} Text to Video tasks với {max_concurrent} "
                    f"công việc đồng thời ({upscale_label})"
                )
                self.log(f"🔑 Round-robin cookie distribution: {num_cookies} cookie(s) sẽ được phân phối đều")
                
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    # Submit tất cả tasks vào executor (sẽ tự động giới hạn concurrent)
                    future_to_task = {}
                    for task in tasks:
                        if self.stop_event.is_set():
                                    break
                        future = executor.submit(
                            self.process_single_text_task_new,
                            task, model, num_videos, aspect, output_folder, len(tasks)
                        )
                        future_to_task[future] = task
                    
                    # Xử lý kết quả khi task hoàn thành
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            task_idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None) or '?'
                            if result:
                                self.log(f"✅ Task {task_idx} hoàn thành")
                            else:
                                self.log(f"❌ Task {task_idx} thất bại")
                        except Exception as e:
                            task_idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None) or '?'
                            self.log(f"❌ Task {task_idx} exception: {e}")
                        
                        if self.stop_event.is_set():
                            break
                
                self.log(f"🏁 Hoàn thành xử lý Text to Video tasks")
            elif mode == "Integrate to Video":
                # ✅ XỬ LÝ INTEGRATE TO VIDEO VỚI QUY TRÌNH MỚI
                from concurrent.futures import ThreadPoolExecutor, as_completed
            
                self.log(f"🚀 Bắt đầu xử lý {len(tasks)} Integrate to Video tasks với {max_concurrent} công việc đồng thời")
                
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    # Submit tất cả tasks vào executor (sẽ tự động giới hạn concurrent)
                    future_to_task = {}
                    for task in tasks:
                        if self.stop_event.is_set():
                            break
                        future = executor.submit(
                            self.process_single_integrate_task_new,
                            task, model, num_videos, aspect, output_folder, len(tasks)
                        )
                        future_to_task[future] = task
                    
                    # Xử lý kết quả khi task hoàn thành
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            task_idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None) or '?'
                            if result:
                                self.log(f"✅ Task {task_idx} hoàn thành")
                            else:
                                self.log(f"❌ Task {task_idx} thất bại")
                        except Exception as e:
                            task_idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None) or '?'
                            self.log(f"❌ Task {task_idx} exception: {e}")
                            import traceback
                            self.log(traceback.format_exc())
                        
                        if self.stop_event.is_set():
                            break
                
                self.log(f"🏁 Hoàn thành xử lý Integrate to Video tasks")
            elif mode == "Image to Video":
                # ✅ XỬ LÝ IMAGE TO VIDEO VỚI QUY TRÌNH MỚI
                from concurrent.futures import ThreadPoolExecutor, as_completed
            
                self.log(f"🚀 Bắt đầu xử lý {len(tasks)} Image to Video tasks với {max_concurrent} công việc đồng thời")
                
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    # Submit tất cả tasks vào executor (sẽ tự động giới hạn concurrent)
                    future_to_task = {}
                    for task in tasks:
                        if self.stop_event.is_set():
                            break
                        future = executor.submit(
                            self.process_single_image_task_new,
                            task, model, num_videos, aspect, output_folder, len(tasks)
                        )
                        future_to_task[future] = task
                    
                    # Xử lý kết quả khi task hoàn thành
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            if result:
                                self.log(f"✅ Task {task.task_index if hasattr(task, 'task_index') else task.prompt_index} hoàn thành")
                            else:
                                self.log(f"❌ Task {task.task_index if hasattr(task, 'task_index') else task.prompt_index} thất bại")
                        except Exception as e:
                            task_idx = task.task_index if hasattr(task, 'task_index') else task.prompt_index
                            self.log(f"❌ Task {task_idx} exception: {e}")
                            import traceback
                            self.log(traceback.format_exc())
                    
                self.log(f"🏁 Hoàn thành xử lý Image to Video tasks")
            elif mode == "Start+End to Video":
                # ✅ XỬ LÝ START+END TO VIDEO VỚI QUY TRÌNH MỚI (Round-robin cookie distribution)
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                self.log(f"🚀 Bắt đầu xử lý {len(tasks)} Start+End to Video tasks với {max_concurrent} công việc đồng thời")
                self.log(f"🔑 Round-robin cookie distribution: {num_cookies} cookie(s) sẽ được phân phối đều cho {len(tasks)} tasks")
                
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    # Submit tất cả tasks vào executor (sẽ tự động giới hạn concurrent)
                    future_to_task = {}
                    for task in tasks:
                        if self.stop_event.is_set():
                            break
                        future = executor.submit(
                            self.process_single_start_end_task_new,
                            task, model, num_videos, aspect, output_folder, len(tasks)
                        )
                        future_to_task[future] = task
                    
                    # Xử lý kết quả khi task hoàn thành
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            if result:
                                self.log(f"✅ Task {task.task_index} hoàn thành")
                            else:
                                self.log(f"❌ Task {task.task_index} thất bại")
                        except Exception as e:
                            self.log(f"❌ Task {task.task_index} exception: {e}")
                            import traceback
                            self.log(traceback.format_exc())
                        
                        if self.stop_event.is_set():
                            break
                
                self.log(f"🏁 Hoàn thành xử lý Start+End to Video tasks")
            elif mode == "Expand + Reference":
                # ✅ XỬ LÝ EXPAND + REFERENCE: Tạo video bằng integrate to video, lấy mediaGenerationId, concat và download
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                self.log(f"🚀 Bắt đầu xử lý {len(tasks)} Expand + Reference tasks với {max_concurrent} công việc đồng thời")
                
                # Bước 1: Tạo tất cả video trước (lưu mediaGenerationIds)
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    # Submit tất cả tasks vào executor
                    future_to_task = {}
                    for task in tasks:
                        if self.stop_event.is_set():
                            break
                        future = executor.submit(
                            self.process_single_expand_reference_task,
                            task, model, num_videos, aspect, output_folder, len(tasks)
                        )
                        future_to_task[future] = task
                    
                    # Xử lý kết quả khi task hoàn thành
                    successful_tasks = []
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            task_idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None) or '?'
                            if result:
                                self.log(f"✅ Task {task_idx} hoàn thành")
                                successful_tasks.append(task)
                            else:
                                self.log(f"❌ Task {task_idx} thất bại")
                        except Exception as e:
                            task_idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None) or '?'
                            self.log(f"❌ Task {task_idx} exception: {e}")
                            import traceback
                            self.log(traceback.format_exc())
                        
                        if self.stop_event.is_set():
                            break
                
                # Bước 2: Sau khi tất cả video hoàn thành, concat tất cả lại
                if successful_tasks and not self.stop_event.is_set():
                    self.log(f"🔗 Bước 2: Nối tất cả video bằng concat API ({len(successful_tasks)} video(s))")
                    
                    # Thu thập tất cả mediaGenerationIds
                    all_media_ids = []
                    concat_client = None
                    for task in successful_tasks:
                        if hasattr(task, '_expand_reference_media_ids'):
                            all_media_ids.extend(task._expand_reference_media_ids)
                            if concat_client is None and hasattr(task, '_expand_reference_client'):
                                concat_client = task._expand_reference_client
                    
                    if len(all_media_ids) < 2:
                        self.log(f"⚠️ Cần ít nhất 2 video để concat, hiện có {len(all_media_ids)}")
                        self.log(f"🏁 Hoàn thành xử lý Expand + Reference tasks (không đủ video để concat)")
                    else:
                        # Dùng client từ task đầu tiên để concat
                        if concat_client is None:
                            # Nếu không có client, tạo client mới
                            num_cookies = len(self.cookies_list) if self.cookies_list else 1
                            self._init_cookie_status()
                            for cookie_idx in range(num_cookies):
                                if self._is_cookie_active(cookie_idx):
                                    concat_client = self.build_client(cookie_idx)
                                    if concat_client and concat_client.fetch_access_token():
                                        break
                        
                        if concat_client:
                            # ✅ Nếu > 5 media_ids: chia thành batch 5, mỗi batch dùng API concat Google, sau đó dùng FFmpeg nối lại
                            if len(all_media_ids) > 5:
                                self.log(f"📦 Số video ({len(all_media_ids)}) > 5, chia thành batch và dùng FFmpeg để nối lại")
                                concat_result = self._concat_large_expand_reference_project(concat_client, all_media_ids, output_folder)
                            else:
                                # ≤ 5 media_ids: dùng API concat Google như bình thường
                                concat_result = self._concat_videos_expand_reference(concat_client, all_media_ids, 0)
                            
                            if concat_result:
                                # Extract URL từ concat result
                                concat_urls = self._extract_file_urls_from_concat(concat_result)
                                
                                if concat_urls:
                                    # Download hoặc copy video đã concat
                                    self.log(f"📥 Bước 3: Download/Copy video đã concat")
                                    base_output_folder = Path(output_folder).resolve()
                                    base_output_folder.mkdir(parents=True, exist_ok=True)
                                    
                                    import shutil
                                    for url_idx, url in enumerate(concat_urls, 1):
                                        filename = base_output_folder / f"expand_reference_concat_{url_idx}.mp4"
                                        
                                        # ✅ Xử lý file:// URLs (file local) - copy trực tiếp
                                        if url.startswith("file://"):
                                            try:
                                                # Lấy file path từ file:// URL
                                                file_path = url.replace("file://", "").replace("\\", "/")
                                                # Xử lý Windows path
                                                if file_path.startswith("/") and ":" in file_path:
                                                    # Windows absolute path: /C:/Users/... -> C:/Users/...
                                                    file_path = file_path[1:]
                                                source_path = Path(file_path)
                                                
                                                if source_path.exists():
                                                    # Copy file trực tiếp
                                                    shutil.copy2(source_path, filename)
                                                    self.log(f"✅ Đã copy video: {filename.name}")
                                                else:
                                                    self.log(f"❌ File không tồn tại: {source_path}")
                                            except Exception as e:
                                                self.log(f"❌ Lỗi copy file: {e}")
                                        else:
                                            # HTTP/HTTPS URL - dùng download queue
                                            self.download_queue.put(DownloadTask(
                                                url=url,
                                                target_path=filename,
                                                method="Nội bộ",
                                                downloads_dir=base_output_folder,
                                                profile_name=None
                                            ))
                                    
                                    self.log(f"✅ Đã xử lý {len(concat_urls)} video đã concat")
                                else:
                                    self.log(f"❌ Không có URL để download")
                            else:
                                self.log(f"❌ Concat video thất bại")
                        else:
                            self.log(f"❌ Không có client để concat")
                
                self.log(f"🏁 Hoàn thành xử lý Expand + Reference tasks")
            else:
                # ✅ Các mode khác giữ nguyên logic cũ (nếu có)
                self.log(f"⚠️ Mode {mode} chưa được refactor, dùng logic cũ")
                
        except Exception as e:
            self.log(f"❌ Lỗi worker: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.signals.finished.emit()

    def process_single_text_task_new(self, task, model, num_videos, aspect, output_folder, total_tasks):
        """Process 1 Text-to-Video task - QUY TRÌNH MỚI: Chọn cookie available, xử lý 429 đổi cookie, lỗi khác retry 6 lần
        
        QUY TRÌNH MỚI:
        - Chọn cookie available (không round-robin cố định)
        - Nếu 429/high traffic → đợi 6s → chuyển cookie khác
        - Nếu lỗi khác → retry 6 lần với cùng cookie (không đổi cookie)
        - Không delay giữa các prompt
        """
        try:
            # ✅ Check app_closing, stop_event và pause_event ngay đầu hàm
            if getattr(self, "app_closing", False):
                self.log(f"🛑 App đang đóng, dừng task ngay lập tức")
                return False
            if self.stop_event.is_set():
                self.log(f"🛑 stop_event set, dừng task ngay lập tức")
                return False
            if self.pause_event.is_set():
                self.log(f"⏸️ PAUSED - Dừng task ngay lập tức")
                return False
            
            # ✅ Xử lý cả ImageTask và PromptTask (ImageTask có task_index, PromptTask có prompt_index)
            if hasattr(task, 'task_index'):
                idx = task.task_index
            elif hasattr(task, 'prompt_index'):
                idx = task.prompt_index
            else:
                self.log(f"❌ Task không có task_index hoặc prompt_index: {type(task)}")
                return False
            
            max_retries = 6  # Tối đa retry 6 lần với cùng cookie (nếu không phải 429)
            max_retries_400 = 6  # ✅ Tối đa retry 6 lần cho lỗi 400 invalid argument
        
            num_cookies = len(self.cookies_list) if self.cookies_list else 1
            self._init_cookie_status()
            
            # ✅ ROUND-ROBIN COOKIE SELECTION: Phân phối đều các cookie
            # ✅ Ưu tiên cookie không bị 429, nhưng vẫn round-robin để đảm bảo phân phối đều
            cookie_index = None
            failed_cookies_429 = getattr(task, "_failed_cookies_429", set())  # Cookies đã bị 429
            
            # ✅ TRƯỜNG HỢP CHỈ CÓ 1 COOKIE: đừng bỏ qua task chỉ vì 1 lần fetch token fail
            if num_cookies == 1:
                import time
                single_idx = 0
                # Thử fetch token nhiều lần trước khi coi như "không có cookie"
                for attempt in range(3):
                    if not self._is_cookie_active(single_idx):
                        break
                    
                    task_client = self.build_client(single_idx)
                    if task_client and task_client.fetch_access_token():
                        cookie_index = single_idx
                        client = task_client
                        try:
                            setattr(task, "_cookie_index", cookie_index)
                            self._register_task_cookie(idx, cookie_index)
                            if hasattr(task, "_failed_cookies_429") and single_idx in task._failed_cookies_429:
                                task._failed_cookies_429.discard(single_idx)
                        except Exception:
                            pass
                        break
                    
                    # Nếu lần này fail, chờ 2s rồi thử lại (tránh lỗi mạng tạm thời)
                    time.sleep(2)
            else:
                # ✅ NHIỀU COOKIE: dùng round-robin như cũ
                if hasattr(self, '_text_video_cookie_lock') and hasattr(self, '_text_video_cookie_counter'):
                    with self._text_video_cookie_lock:
                        start = self._text_video_cookie_counter["count"] % num_cookies
                        self._text_video_cookie_counter["count"] += 1
                    
                    # ✅ Tạo thứ tự candidate: ưu tiên cookie chưa 429 trước, nhưng bắt đầu từ start (round-robin)
                    ordered_indices = [(start + shift) % num_cookies for shift in range(num_cookies)]
                    primary = [i for i in ordered_indices if i not in failed_cookies_429 and self._is_cookie_active(i)]
                    secondary = [i for i in ordered_indices if i in failed_cookies_429 and self._is_cookie_active(i)]
                    
                    # ✅ Thử cookie theo thứ tự round-robin (ưu tiên cookie không bị 429)
                    for cookie_idx in primary + secondary:
                        task_client = self.build_client(cookie_idx)
                        
                        if task_client and task_client.fetch_access_token():
                            cookie_index = cookie_idx
                            client = task_client
                            try:
                                setattr(task, "_cookie_index", cookie_index)
                                self._register_task_cookie(idx, cookie_index)
                                # ✅ Xóa cookie này khỏi failed_cookies_429 nếu đã thử lại thành công
                                if cookie_idx in failed_cookies_429:
                                    task._failed_cookies_429.discard(cookie_idx)
                            except Exception:
                                pass
                            break
                else:
                    # ✅ Fallback: Nếu không có counter, dùng logic cũ (chọn cookie đầu tiên)
                    for cookie_idx in range(num_cookies):
                        if not self._is_cookie_active(cookie_idx) or cookie_idx in failed_cookies_429:
                            continue
                        
                        task_client = self.build_client(cookie_idx)
                        
                        if task_client and task_client.fetch_access_token():
                            cookie_index = cookie_idx
                            client = task_client
                            try:
                                setattr(task, "_cookie_index", cookie_index)
                                self._register_task_cookie(idx, cookie_index)
                            except Exception:
                                pass
                            break
                    
                    # ✅ Nếu không tìm thấy cookie không bị 429, thử với cookie đã bị 429
                    if cookie_index is None:
                        for cookie_idx in range(num_cookies):
                            if not self._is_cookie_active(cookie_idx):
                                continue
                            
                            task_client = self.build_client(cookie_idx)
                            
                            if task_client and task_client.fetch_access_token():
                                cookie_index = cookie_idx
                                client = task_client
                                try:
                                    setattr(task, "_cookie_index", cookie_index)
                                    self._register_task_cookie(idx, cookie_index)
                                    if cookie_idx in failed_cookies_429:
                                        task._failed_cookies_429.discard(cookie_idx)
                                except Exception:
                                    pass
                                break

            # ✅ Chỉ dừng khi không có cookie nào có thể fetch token (không access được)
            if cookie_index is None:
                self.log(f"🛑 Không có cookie nào có thể fetch token cho task {idx} - Dừng và đợi chạy lại")
                self.signals.update_status.emit(idx, "Fail (Không có cookie access)")
                self.update_task_progress(idx, 0)
                return False
            
            self.log(f"\n{'='*50}")
            self.log(f"📝 Task {idx}/{total_tasks}: {task.prompt_text[:60]}...")
            self.log(f"🔑 Task {idx} dùng cookie {cookie_index + 1}/{num_cookies} (round-robin)")
            
            self.signals.update_status.emit(idx, "Đang xử lý")
            self.update_task_progress(idx, 5)
            self.signals.update_batch.emit(idx, total_tasks)
            
            # ✅ Vòng lặp retry: 429 không giới hạn (chỉ dừng khi hết cookie), lỗi khác retry tối đa 6 lần
            # ✅ Lưu retry_count_non_429 vào task để không bị reset khi đổi cookie (tránh vòng lặp vô hạn)
            if not hasattr(task, "_retry_count_non_429"):
                task._retry_count_non_429 = 0
            retry_count_non_429 = task._retry_count_non_429  # Lấy từ task object
            
            # ✅ Lưu retry_count_400 vào task để đếm số lần retry cho lỗi 400
            if not hasattr(task, "_retry_count_400"):
                task._retry_count_400 = 0
            retry_count_400 = task._retry_count_400  # Lấy từ task object
            
            # ✅ Track số lần retry cho cookie hiện tại (để biết khi nào cần restart context)
            if not hasattr(task, "_cookie_retry_count"):
                task._cookie_retry_count = {}  # {cookie_index: retry_count}
            if cookie_index not in task._cookie_retry_count:
                task._cookie_retry_count[cookie_index] = 0
            cookie_retry_count = task._cookie_retry_count[cookie_index]
            
            # ✅ Track xem cookie đã được restart chưa (sau 6 lần retry)
            if not hasattr(task, "_cookie_restarted"):
                task._cookie_restarted = set()  # {cookie_index} - cookies đã được restart
            
            # ✅ Track số lần retry cho cookie hiện tại (để biết khi nào cần restart context)
            if not hasattr(task, "_cookie_retry_count"):
                task._cookie_retry_count = {}  # {cookie_index: retry_count}
            if cookie_index not in task._cookie_retry_count:
                task._cookie_retry_count[cookie_index] = 0
            cookie_retry_count = task._cookie_retry_count[cookie_index]
            
            # ✅ Track xem cookie đã được restart chưa (sau 6 lần retry)
            if not hasattr(task, "_cookie_restarted"):
                task._cookie_restarted = set()  # {cookie_index} - cookies đã được restart
            
            while True:  # Vòng lặp vô hạn cho 429, sẽ break khi thành công hoặc hết cookie
                # ✅ Check app_closing và stop_event trước khi xử lý
                if getattr(self, "app_closing", False):
                    self.log(f"🛑 App đang đóng, dừng task {idx}")
                    self._unregister_task_cookie(idx)
                    return False
                if self.stop_event.is_set():
                    self.log(f"🛑 stop_event set, dừng task {idx}")
                    self._unregister_task_cookie(idx)
                    return False
                if self.pause_event.is_set():
                    self.log(f"⏸️ PAUSED - Dừng task {idx}")
                    self._unregister_task_cookie(idx)
                    return False
                
                try:
                    result = self._execute_text_to_video(client, task, model, num_videos, aspect, output_folder)
                except Exception as e:
                    # ✅ Bắt exception từ _execute_text_to_video
                    error_str = str(e)
                    self.log(f"❌ Task {idx} lỗi: {error_str[:100]}")
                    
                    # ✅ Đảm bảo set error_detail với đầy đủ thông tin
                    try:
                        # Set error_detail với exception message (có thể chứa "429 Client Error")
                        client.last_error_detail = f"Exception: {error_str}"
                        client.last_error = error_str
                        
                        # ✅ Nếu exception có attribute response (HTTP response), lấy status code
                        if hasattr(e, 'response'):
                            try:
                                status_code = getattr(e.response, 'status_code', None)
                                if status_code:
                                    error_msg_with_status = f"Exception (Status: {status_code}): {error_str}"
                                    client.last_error_detail = error_msg_with_status
                            except:
                                pass
                    except Exception:
                        pass
                    
                    result = False
                
                if result:
                    # ✅ Thành công - reset counter để tránh vòng lặp
                    if hasattr(task, "_retry_count_non_429"):
                        task._retry_count_non_429 = 0
                    if hasattr(task, "_retry_count_400"):
                        task._retry_count_400 = 0
                    self._unregister_task_cookie(idx)
                    self.signals.update_status.emit(idx, "Done")
                    self.update_task_progress(idx, 100)
                    return True
                
                # ✅ Lỗi - lấy error_detail từ nhiều nguồn để đảm bảo bắt được
                error_detail = ""
                try:
                    # Thử lấy từ last_error_detail trước
                    error_detail = getattr(client, "last_error_detail", "") or ""
                    if not error_detail:
                        # Thử lấy từ last_error
                        error_detail = getattr(client, "last_error", "") or ""
                    if not error_detail:
                        # Thử lấy từ exception nếu có
                        if hasattr(client, "last_exception"):
                            error_detail = str(getattr(client, "last_exception", ""))
                except Exception as e:
                    self.log(f"⚠️ Không thể lấy error_detail: {e}")
                
                error_log = error_detail[:100] if error_detail else "Không rõ nguyên nhân"
                
                # ✅ Check nếu là 400 invalid argument → retry tối đa 6 lần, sau đó dừng
                if self._check_is_400_invalid_argument(error_detail):
                    retry_count_400 += 1
                    task._retry_count_400 = retry_count_400  # ✅ Lưu vào task object
                    
                    if retry_count_400 <= max_retries_400:
                        self.log(f"⚠️ Task {idx} gặp lỗi 400 invalid argument (retry {retry_count_400}/{max_retries_400})")
                        self.signals.update_status.emit(idx, f"400 Error - Retry {retry_count_400}/{max_retries_400}")
                        # Đợi 1s trước khi retry
                        import time
                        time.sleep(1)
                        continue  # Retry lại
                    else:
                        # ✅ Đã retry 6 lần vẫn lỗi 400 - dừng lại và đánh dấu error
                        task._retry_count_400 = 0  # Reset khi fail hoàn toàn
                        self.log(f"❌ Task {idx} thất bại sau {max_retries_400} lần retry lỗi 400 invalid argument")
                        self._unregister_task_cookie(idx)
                        self.signals.update_status.emit(idx, "Fail (400 Invalid Argument)")
                        self.update_task_progress(idx, 0)
                        return False
                
                # ✅ Check nếu là 429/high traffic → đợi 6s → chuyển cookie khác (KHÔNG GIỚI HẠN)
                if self._check_is_429_or_high_traffic(error_detail):
                    self.log(f"⚠️ Task {idx} gặp 429 với cookie #{cookie_index + 1}, đổi cookie...")
                    
                    # Đánh dấu cookie này đã bị 429
                    if not hasattr(task, "_failed_cookies_429"):
                        task._failed_cookies_429 = set()
                    task._failed_cookies_429.add(cookie_index)
                    
                    # ✅ KHÔNG reset retry_count_non_429 khi đổi cookie - giữ nguyên để tránh vòng lặp vô hạn
                    # retry_count_non_429 đã được lưu trong task object, không cần reset
                    # Chỉ reset khi thành công hoặc fail hoàn toàn
                    
                    # Đợi 6s trước khi chuyển cookie khác
                    import time
                    time.sleep(6)
                    
                    # Hủy đăng ký cookie cũ
                    self._unregister_task_cookie(idx)
                    
                    # Cập nhật failed_cookies_429 từ task
                    failed_cookies_429 = getattr(task, "_failed_cookies_429", set())
                    
                    # ✅ Tìm cookie khác available (không bị 429, không inactive)
                    new_cookie_index = None
                    for cookie_idx in range(num_cookies):
                        if cookie_idx == cookie_index:  # Bỏ qua cookie cũ
                            continue
                        if not self._is_cookie_active(cookie_idx) or cookie_idx in failed_cookies_429:
                            continue
                        
                        new_client = self.build_client(cookie_idx)
                        
                        if new_client and new_client.fetch_access_token():
                            # ✅ Đảm bảo set model cho cookie mới
                            if not new_client.set_video_model_key(model):
                                error_msg = getattr(new_client, "last_error_detail", "") or getattr(new_client, "last_error", "") or "Lỗi set model"
                                self.log(f"❌ Set model thất bại cho cookie #{cookie_idx + 1}: {error_msg}")
                                continue  # Thử cookie khác
                            
                            new_cookie_index = cookie_idx
                            client = new_client
                            cookie_index = new_cookie_index
                            try:
                                setattr(task, "_cookie_index", cookie_index)
                                self._register_task_cookie(idx, cookie_index)
                                self.log(f"✅ Task {idx} chuyển sang cookie #{cookie_idx + 1} (model: {model})")
                            except Exception:
                                pass
                            break
                    
                    # ✅ Nếu không tìm thấy cookie khác (tất cả đều bị 429), thử lại với cookie đã bị 429
                    if new_cookie_index is None:
                        # ✅ Thử tìm cookie có thể fetch token (kể cả cookie đã bị 429)
                        found_any_cookie = False
                        for cookie_idx in range(num_cookies):
                            if not self._is_cookie_active(cookie_idx):
                                continue
                            
                            new_client = self.build_client(cookie_idx)
                            
                            if new_client and new_client.fetch_access_token():
                                # ✅ Cookie này vẫn có thể fetch token → tiếp tục retry
                                new_cookie_index = cookie_idx
                                client = new_client
                                cookie_index = new_cookie_index
                                try:
                                    setattr(task, "_cookie_index", cookie_index)
                                    self._register_task_cookie(idx, cookie_index)
                                except Exception:
                                    pass
                                
                                # ✅ Xóa cookie này khỏi failed_cookies_429 để có thể thử lại
                                if cookie_idx in failed_cookies_429:
                                    task._failed_cookies_429.discard(cookie_idx)
                                
                                found_any_cookie = True
                                self.log(f"✅ Task {idx} tiếp tục retry với cookie #{cookie_idx + 1}")
                                break
                        
                        # ✅ Nếu không có cookie nào có thể fetch token → dừng và báo lỗi
                        if not found_any_cookie:
                            self.log(f"🛑 Không có cookie nào có thể fetch token cho task {idx} - Dừng và đợi chạy lại")
                            self._unregister_task_cookie(idx)
                            self.signals.update_status.emit(idx, "Fail (Không có cookie access)")
                            self.update_task_progress(idx, 0)
                            return False
                    
                    # Tiếp tục retry với cookie mới (không giới hạn số lần cho 429)
                    continue
                
                # ✅ Lỗi khác (không phải 429) → retry với cùng cookie
                retry_count_non_429 += 1
                task._retry_count_non_429 = retry_count_non_429  # ✅ Lưu vào task object
                cookie_retry_count += 1
                task._cookie_retry_count[cookie_index] = cookie_retry_count
                
                # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                if cookie_retry_count >= 2 and cookie_index not in task._cookie_restarted:
                    self.log(f"🔄 Task {idx}: Cookie {cookie_index+1} đã retry 6 lần → restart BrowserContext (renew cookie)")
                    self.signals.update_status.emit(idx, f"🔄 Restart BrowserContext (retry 6/6)")
                    
                    # Gọi renew cookie và restart context
                    try:
                        from complete_flow import LabsFlowClient
                        cookie_hash = client._cookie_hash if hasattr(client, '_cookie_hash') else None
                        
                        if cookie_hash:
                            # Lấy callback để renew cookie
                            get_new_cookies_callback = None
                            if hasattr(LabsFlowClient, '_recaptcha_renew_cookie_callbacks'):
                                get_new_cookies_callback = LabsFlowClient._recaptcha_renew_cookie_callbacks.get(cookie_hash)
                            
                            if get_new_cookies_callback:
                                # Gọi renew cookie và restart context
                                new_cookies = LabsFlowClient._renew_cookie_and_restart_context(
                                    browser=LabsFlowClient._recaptcha_worker_browser if hasattr(LabsFlowClient, '_recaptcha_worker_browser') else None,
                                    cookie_hash=cookie_hash,
                                    old_cookies=client.cookies if hasattr(client, 'cookies') else {},
                                    proxy_config=getattr(client, 'proxy_config', None),
                                    user_agent=getattr(client, 'user_agent', ''),
                                    get_new_cookies_callback=get_new_cookies_callback,
                                )
                                
                                if new_cookies:
                                    # ✅ Update cookies trong client hiện tại
                                    client.cookies = new_cookies
                                    # Re-fetch token với cookie mới
                                    if client.fetch_access_token() and client.set_video_model_key(model):
                                        task._cookie_restarted.add(cookie_index)
                                        task._cookie_retry_count[cookie_index] = 0  # Reset counter sau khi restart
                                        cookie_retry_count = 0
                                        self.log(f"✅ Task {idx}: Cookie {cookie_index+1} đã được renew và restart thành công")
                                    else:
                                        self.log(f"⚠️ Task {idx}: Cookie {cookie_index+1} renew thành công nhưng fetch token/set model fail")
                                else:
                                    self.log(f"⚠️ Task {idx}: Không thể renew cookie {cookie_index+1}")
                            else:
                                self.log(f"⚠️ Task {idx}: Không có callback để renew cookie {cookie_index+1}")
                    except Exception as renew_err:
                        self.log(f"⚠️ Task {idx}: Lỗi khi renew cookie {cookie_index+1}: {renew_err}")
                        import traceback
                        self.log(traceback.format_exc())
                    
                    # Tiếp tục retry với cookie (có thể đã được renew)
                    continue
                
                # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → đánh dấu cookie die
                if cookie_retry_count >= 3 and cookie_index in task._cookie_restarted:
                    self.log(f"💀 Task {idx}: Cookie {cookie_index+1} đã restart nhưng vẫn lỗi sau lần thứ 7 → đánh dấu die")
                    
                    # Đánh dấu cookie die
                    if not hasattr(task, "_failed_cookies_die"):
                        task._failed_cookies_die = set()
                    task._failed_cookies_die.add(cookie_index)
                    
                    # Tìm cookie khác
                    new_cookie_index = None
                    for cookie_idx in range(num_cookies):
                        if cookie_idx == cookie_index:  # Bỏ qua cookie die
                            continue
                        if cookie_idx in getattr(task, "_failed_cookies_die", set()):  # Bỏ qua cookie đã die
                            continue
                        if not self._is_cookie_active(cookie_idx):
                            continue
                        
                        new_client = self.build_client(cookie_idx)
                        if new_client and new_client.fetch_access_token():
                            if new_client.set_video_model_key(model):
                                new_cookie_index = cookie_idx
                                client = new_client
                                cookie_index = new_cookie_index
                                try:
                                    setattr(task, "_cookie_index", cookie_index)
                                    self._register_task_cookie(idx, cookie_index)
                                    # Reset retry count cho cookie mới
                                    if cookie_index not in task._cookie_retry_count:
                                        task._cookie_retry_count[cookie_index] = 0
                                    cookie_retry_count = 0
                                    self.log(f"✅ Task {idx} chuyển sang cookie #{cookie_idx + 1} (cookie cũ đã die)")
                                except Exception:
                                    pass
                                break
                    
                    if new_cookie_index is None:
                        # Không còn cookie nào sống
                        alive_count = num_cookies - len(getattr(task, "_failed_cookies_die", set()))
                        if alive_count == 0:
                            self.log(f"🛑 Task {idx}: Tất cả {num_cookies} cookie(s) đều die")
                            self._unregister_task_cookie(idx)
                            self.signals.update_status.emit(idx, "Fail (Tất cả cookie die)")
                            self.update_task_progress(idx, 0)
                            return False
                        else:
                            # Vẫn còn cookie sống nhưng không fetch được token ngay → thử lại
                            self.log(f"⚠️ Task {idx}: Còn {alive_count} cookie(s) sống nhưng không fetch được token ngay")
                            continue
                    else:
                        # Đã chuyển sang cookie mới → tiếp tục retry
                        continue
                
                if retry_count_non_429 <= max_retries:
                    self.log(f"🔄 Task {idx} retry {retry_count_non_429}/{max_retries} (cookie {cookie_index+1}: {cookie_retry_count} lần)")
                    self.signals.update_status.emit(idx, f"Retry {retry_count_non_429}/{max_retries}")
                    # Không đổi cookie, retry với cùng cookie
                    continue
                else:
                    # Đã retry 6 lần vẫn lỗi (không phải 429) - reset counter để tránh vòng lặp
                    task._retry_count_non_429 = 0  # Reset khi fail hoàn toàn
                    self.log(f"❌ Task {idx} thất bại sau {max_retries} lần retry")
                    self._unregister_task_cookie(idx)
                    self.signals.update_status.emit(idx, "Fail")
                    self.update_task_progress(idx, 0)
                    return False
            
        except Exception as e:
            self.log(f"❌ Lỗi task {idx}: {e}")
            import traceback
            self.log(traceback.format_exc())
            try:
                self._unregister_task_cookie(idx)
            except:
                pass
            self.signals.update_status.emit(idx, "Fail")
            self.update_task_progress(idx, 0)
            return False

    def process_single_text_task(self, client, task, model, num_videos, aspect, output_folder, total_tasks, wave_position=1, retry_count=0):
        """Process 1 Text-to-Video task (LEGACY - giữ lại cho các mode khác)"""
        # ✅ Nếu client được truyền vào, dùng luôn (cho các mode khác)
        if client is not None:
            try:
                # ✅ Xử lý cả ImageTask và PromptTask (ImageTask có task_index, PromptTask có prompt_index)
                if hasattr(task, 'task_index'):
                    idx = task.task_index
                elif hasattr(task, 'prompt_index'):
                    idx = task.prompt_index
                else:
                    self.log(f"❌ Task không có task_index hoặc prompt_index: {type(task)}")
                    return False
                
                cookie_index = getattr(task, "_cookie_index", None)
                
                if cookie_index is None:
                    cookie_index = 0
                    try:
                        setattr(task, "_cookie_index", cookie_index)
                        self._register_task_cookie(idx, cookie_index)
                    except Exception:
                        pass
                
                self.log(f"\n{'='*50}")
                self.log(f"📝 Task {idx}/{total_tasks}: {task.prompt_text[:60]}...")
                
                self.signals.update_status.emit(idx, "Đang xử lý")
                self.update_task_progress(idx, 5)
                self.signals.update_batch.emit(idx, total_tasks)
                
                result = self._execute_text_to_video(client, task, model, num_videos, aspect, output_folder)
                
                if result:
                    self._unregister_task_cookie(idx)
                    self.signals.update_status.emit(idx, "Done")
                    self.update_task_progress(idx, 100)
                    return True
                else:
                    self._unregister_task_cookie(idx)
                    self.signals.update_status.emit(idx, "Fail")
                    self.update_task_progress(idx, 0)
                    return False
            except Exception as e:
                # ✅ Lấy idx an toàn cho error handling
                idx = getattr(task, 'task_index', None) or getattr(task, 'prompt_index', None)
                if idx is None:
                    self.log(f"❌ Lỗi task (không có index): {e}")
                    return False
                self.log(f"❌ Lỗi task {idx}: {e}")
                try:
                    self._unregister_task_cookie(idx)
                except:
                    pass
                self.signals.update_status.emit(idx, "Fail")
                self.update_task_progress(idx, 0)
                return False
        else:
            # ✅ Nếu không có client, gọi hàm mới
            return self.process_single_text_task_new(task, model, num_videos, aspect, output_folder, total_tasks)

"""Flow/Banana Pro tab logic extracted from gui_app_mac.py."""

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
from gui_ui_shared import FlowTaskData, ThumbnailGridWidget


class FlowTabMixin:
    def build_flow_tab_content(self):
        """Build Flow Image tab content similar to provided mock"""
        flow_widget = QWidget()
        layout = QVBoxLayout(flow_widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = self.build_flow_left_panel()
        right_panel = self.build_flow_right_panel()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([470, 950])

        layout.addWidget(splitter)
        self.tab_stack.addWidget(flow_widget)

    def build_flow_left_panel(self):
        widget = QWidget()
        widget.setObjectName("flowInputPanel")
        widget.setStyleSheet("""
            QWidget#flowInputPanel {
                background: #ffffff;
            }
            QFrame#flowCard {
                background: #ffffff;
                border: 1px solid #dee2e6;
                border-radius: 14px;
            }
            QLabel#flowCardTitle {
                color: #0f172a;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel.flowSubLabel {
                color: #6b7280;
                font-size: 12px;
            }
        """)

        root_layout = QVBoxLayout(widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        root_layout.addWidget(scroll)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(18, 18, 18, 18)
        container_layout.setSpacing(18)
        scroll.setWidget(container)

        # ===== CONFIG SECTION =====
        config_card, config_layout = self._create_flow_card("Cấu hình")
        config_form = QGridLayout()
        config_form.setColumnStretch(1, 1)
        config_form.setHorizontalSpacing(12)
        config_form.setVerticalSpacing(12)

        # Row 0: Model
        model_label = QLabel("Model")
        model_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_model_combo = QComboBox()
        self.flow_model_combo.addItem("Banana Pro 2", "NARWHAL")
        self.flow_model_combo.addItem("Banana Pro", "GEM_PIX_2")
        self.flow_model_combo.setCurrentIndex(0)
        config_form.addWidget(model_label, 0, 0)
        config_form.addWidget(self.flow_model_combo, 0, 1)

        # Row 1: Quality / Upsample
        upsample_label = QLabel("Chất lượng")
        upsample_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_upsample_combo = QComboBox()
        self.flow_upsample_combo.addItem("Gốc", "none")
        self.flow_upsample_combo.addItem("2K", "UPSAMPLE_IMAGE_RESOLUTION_2K")
        self.flow_upsample_combo.addItem("4K", "UPSAMPLE_IMAGE_RESOLUTION_4K")
        self.flow_upsample_combo.setCurrentIndex(0)
        self.flow_upsample_combo.currentIndexChanged.connect(self.update_flow_concurrent_range)
        config_form.addWidget(upsample_label, 1, 0)
        config_form.addWidget(self.flow_upsample_combo, 1, 1)

        # Row 2: Aspect Ratio
        aspect_label = QLabel("Tỷ lệ khung")
        aspect_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_aspect_combo = QComboBox()
        self.flow_aspect_combo.addItem("16:9 Ngang", "IMAGE_ASPECT_RATIO_LANDSCAPE")
        self.flow_aspect_combo.addItem("9:16 Dọc", "IMAGE_ASPECT_RATIO_PORTRAIT")
        self.flow_aspect_combo.addItem("4:3 Ngang", "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE")
        self.flow_aspect_combo.addItem("3:4 Dọc", "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR")
        self.flow_aspect_combo.addItem("1:1 Vuông", "IMAGE_ASPECT_RATIO_SQUARE")
        self.flow_aspect_combo.setCurrentIndex(0)
        config_form.addWidget(aspect_label, 2, 0)
        config_form.addWidget(self.flow_aspect_combo, 2, 1)

        # Row 3: Variations (số ảnh / prompt)
        variations_label = QLabel("Số ảnh / prompt")
        variations_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_variations_spin = QSpinBox()
        self.flow_variations_spin.setRange(1, 1)
        self.flow_variations_spin.setValue(1)
        self.flow_variations_spin.setToolTip("Cố định 1 ảnh cho mỗi prompt")
        config_form.addWidget(variations_label, 3, 0)
        config_form.addWidget(self.flow_variations_spin, 3, 1)
        variations_label.setVisible(False)
        self.flow_variations_spin.setVisible(False)

        # Row 4: Concurrent (ẩn khỏi UI, vẫn giữ cho logic cũ)
        concurrent_label = QLabel("Số công việc đồng thời")
        concurrent_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_concurrent_spin = QSpinBox()
        self.flow_concurrent_spin.setRange(1, 6)
        self.flow_concurrent_spin.setValue(2)
        self.flow_concurrent_spin.setToolTip("Số prompt xử lý đồng thời (1-6)")
        config_form.addWidget(concurrent_label, 4, 0)
        config_form.addWidget(self.flow_concurrent_spin, 4, 1)
        concurrent_label.setVisible(False)
        self.flow_concurrent_spin.setVisible(False)

        # Row 5: Delay
        delay_label = QLabel("Delay (giây)")
        delay_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_delay_spin = QSpinBox()
        self.flow_delay_spin.setRange(3, 3)
        self.flow_delay_spin.setValue(3)
        self.flow_delay_spin.setSuffix(" s")
        self.flow_delay_spin.setToolTip("Cố định 3 giây giữa các prompt")
        config_form.addWidget(delay_label, 5, 0)
        config_form.addWidget(self.flow_delay_spin, 5, 1)
        delay_label.setVisible(False)
        self.flow_delay_spin.setVisible(False)

        # Row 6: Reference Mode (ẩn khỏi UI)
        ref_mode_label = QLabel("Chế độ tham chiếu")
        ref_mode_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_ref_mode_combo = QComboBox()
        self.flow_ref_mode_combo.addItem("Mặc định", "default")
        self.flow_ref_mode_combo.addItem("Subject", "subject")
        self.flow_ref_mode_combo.addItem("Scene", "scene")
        self.flow_ref_mode_combo.addItem("Style", "style")
        self.flow_ref_mode_combo.setCurrentIndex(0)
        config_form.addWidget(ref_mode_label, 6, 0)
        config_form.addWidget(self.flow_ref_mode_combo, 6, 1)
        ref_mode_label.setVisible(False)
        self.flow_ref_mode_combo.setVisible(False)

        # Row 7: Seed (ẩn khỏi UI)
        seed_label = QLabel("Seed")
        seed_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        self.flow_seed_input = QSpinBox()
        self.flow_seed_input.setRange(0, 999999999)
        self.flow_seed_input.setValue(0)
        self.flow_seed_input.setToolTip("Seed (0 = random)")
        self.flow_seed_input.setSpecialValueText("Random")
        config_form.addWidget(seed_label, 7, 0)
        config_form.addWidget(self.flow_seed_input, 7, 1)
        seed_label.setVisible(False)
        self.flow_seed_input.setVisible(False)

        # Row 8: Output directory
        output_label = QLabel("Thư mục lưu ảnh")
        output_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        output_row = QHBoxLayout()
        default_flow_output = str((Path.cwd() / "downloaded_images" / "flow").resolve())
        self.flow_output_input = QLineEdit()
        self.flow_output_input.setPlaceholderText("Chọn thư mục lưu ảnh Flow…")
        self.flow_output_input.setText(default_flow_output)
        self.flow_output_input.setReadOnly(True)
        self.flow_output_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        self.btn_browse_flow_output = QPushButton("Chọn thư mục")
        self.btn_browse_flow_output.setFixedWidth(110)
        self.btn_browse_flow_output.clicked.connect(self.browse_flow_output_dir)
        self.btn_browse_flow_output.setStyleSheet("""
            QPushButton {
                background: #e0f2fe;
                border-radius: 10px;
                color: #0369a1;
                padding: 8px 14px;
                border: 1px solid #7dd3fc;
                font-weight: 600;
            }
            QPushButton:hover { background: #bae6fd; }
        """)
        output_row.addWidget(self.flow_output_input)
        output_row.addWidget(self.btn_browse_flow_output)
        config_form.addWidget(output_label, 8, 0)
        config_form.addLayout(output_row, 8, 1)

        config_layout.addLayout(config_form)
        container_layout.addWidget(config_card)

        # ===== MODE SELECTION (ẩn khỏi UI, giữ mode mặc định tương thích) =====
        mode_card, mode_layout = self._create_flow_card("Chế độ tạo ảnh")
        mode_group_layout = QVBoxLayout()

        # Hàng 1: Thường
        row1_layout = QHBoxLayout()
        self.rb_flow_normal = QRadioButton("Thường (chọn từng ảnh)")
        self.rb_flow_normal.setChecked(True)
        self.rb_flow_normal.clicked.connect(self.on_flow_mode_change)
        row1_layout.addWidget(self.rb_flow_normal)
        row1_layout.addStretch()
        mode_group_layout.addLayout(row1_layout)

        # Hàng 2: Multiple-to-Image (tạm ẩn khỏi UI)
        row2_layout = QHBoxLayout()
        self.rb_flow_multiple = QRadioButton("Multiple-to-Image (chọn folder)")
        self.rb_flow_multiple.clicked.connect(self.on_flow_mode_change)
        self.rb_flow_multiple.setVisible(False)
        row2_layout.addWidget(self.rb_flow_multiple)
        row2_layout.addStretch()
        mode_group_layout.addLayout(row2_layout)

        # Hàng 3: Folder Structure
        row3_layout = QHBoxLayout()
        self.rb_flow_folder_structure = QRadioButton("Folder Structure (folder cha chứa folder con)")
        self.rb_flow_folder_structure.clicked.connect(self.on_flow_mode_change)
        row3_layout.addWidget(self.rb_flow_folder_structure)
        row3_layout.addStretch()
        mode_group_layout.addLayout(row3_layout)

        mode_layout.addLayout(mode_group_layout)
        mode_card.setVisible(False)
        container_layout.addWidget(mode_card)

        # ===== REFERENCE IMAGES - NORMAL MODE (ẨN - đã có nút ở toolbar grid) =====
        self.flow_ref_normal_card, flow_ref_normal_layout = self._create_flow_card("Ảnh tham chiếu (tùy chọn)")
        self.flow_reference_list = QListWidget()
        self.flow_reference_list.setVisible(False)
        self.flow_ref_normal_card.setVisible(False)

        # ===== HIDDEN PROMPT INPUT (backward compat - used by batch logic) =====
        self.flow_prompt_input = QPlainTextEdit()
        self.flow_prompt_input.setVisible(False)
        self.flow_prompt_count_label = QLabel("0 prompt")
        self.flow_prompt_count_label.setVisible(False)

        # ===== NGUỒN PROMPT (.TXT) =====
        self.flow_source_card, source_layout = self._create_flow_card("Nguồn nội dung (.txt)")
        source_desc = QLabel("Chọn 1 file .txt hoặc 1 thư mục chứa nhiều file .txt.")
        source_desc.setObjectName("flowSubLabel")
        source_desc.setWordWrap(True)
        source_layout.addWidget(source_desc)

        file_row = QHBoxLayout()
        file_label = QLabel("File .txt")
        file_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        file_row.addWidget(file_label)
        self.flow_prompt_file_input = QLineEdit()
        self.flow_prompt_file_input.setPlaceholderText("Chọn file .txt chứa prompts…")
        self.flow_prompt_file_input.setReadOnly(True)
        self.flow_prompt_file_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        file_row.addWidget(self.flow_prompt_file_input, stretch=1)
        btn_browse_flow_file = QPushButton("Chọn file")
        btn_browse_flow_file.setFixedWidth(100)
        btn_browse_flow_file.clicked.connect(self.browse_flow_prompt_file)
        file_row.addWidget(btn_browse_flow_file)
        source_layout.addLayout(file_row)

        folder_row = QHBoxLayout()
        folder_label = QLabel("Thư mục .txt")
        folder_label.setStyleSheet("color: #0f172a; font-weight: 600;")
        folder_row.addWidget(folder_label)
        self.flow_prompt_folder_input = QLineEdit()
        self.flow_prompt_folder_input.setPlaceholderText("Chọn thư mục chứa nhiều file .txt…")
        self.flow_prompt_folder_input.setReadOnly(True)
        self.flow_prompt_folder_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        folder_row.addWidget(self.flow_prompt_folder_input, stretch=1)
        btn_browse_flow_folder = QPushButton("Chọn thư mục")
        btn_browse_flow_folder.setFixedWidth(120)
        btn_browse_flow_folder.clicked.connect(self.browse_flow_prompt_folder)
        folder_row.addWidget(btn_browse_flow_folder)
        source_layout.addLayout(folder_row)

        action_row = QHBoxLayout()
        action_row.addStretch()
        btn_clear_sources = QPushButton("Xóa danh sách")
        btn_clear_sources.setFixedWidth(140)
        btn_clear_sources.clicked.connect(self.clear_flow_prompt_sources)
        action_row.addWidget(btn_clear_sources)
        source_layout.addLayout(action_row)

        self.flow_batch_table = QTableWidget()
        self.flow_batch_table.setColumnCount(4)
        self.flow_batch_table.setHorizontalHeaderLabels(["STT", "Tên File", "Số Prompt", "Trạng thái"])
        self.flow_batch_table.setMinimumHeight(150)
        self.flow_batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.flow_batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.flow_batch_table.verticalHeader().setVisible(False)
        self.flow_batch_table.setColumnWidth(0, 50)
        self.flow_batch_table.setColumnWidth(1, 160)
        self.flow_batch_table.setColumnWidth(2, 90)
        self.flow_batch_table.horizontalHeader().setStretchLastSection(True)
        # ✅ Click vào row để filter kết quả theo file txt đó
        self.flow_batch_table.cellClicked.connect(self._on_flow_batch_table_clicked)
        source_layout.addWidget(self.flow_batch_table)

        container_layout.addWidget(self.flow_source_card)


        # ===== REFERENCE FOLDERS - MULTIPLE-TO-IMAGE MODE =====
        self.flow_ref_multiple_card, flow_ref_multiple_layout = self._create_flow_card("Thư mục ảnh tham chiếu (Subject / Scene / Style)")
        ref_multiple_desc = QLabel("Chọn 3 folder chứa ảnh Subject/Scene/Style, mỗi ảnh trong folder sẽ map với từng prompt.")
        ref_multiple_desc.setObjectName("flowSubLabel")
        ref_multiple_desc.setWordWrap(True)
        flow_ref_multiple_layout.addWidget(ref_multiple_desc)

        folder_ref_layout = QGridLayout()
        folder_ref_layout.setSpacing(8)

        # Subject folder
        folder_ref_layout.addWidget(QLabel("Subject Folder:"), 0, 0)
        self.flow_subject_folder = QLineEdit()
        self.flow_subject_folder.setPlaceholderText("Chọn thư mục chứa ảnh Subject...")
        self.flow_subject_folder.setReadOnly(True)
        self.flow_subject_folder.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        folder_ref_layout.addWidget(self.flow_subject_folder, 0, 1)
        btn_flow_subject_folder = QPushButton("Chọn thư mục")
        btn_flow_subject_folder.setFixedWidth(120)
        btn_flow_subject_folder.clicked.connect(self.browse_flow_subject_folder)
        folder_ref_layout.addWidget(btn_flow_subject_folder, 0, 2)

        # Scene folder
        folder_ref_layout.addWidget(QLabel("Scene Folder:"), 1, 0)
        self.flow_scene_folder = QLineEdit()
        self.flow_scene_folder.setPlaceholderText("Chọn thư mục chứa ảnh Scene...")
        self.flow_scene_folder.setReadOnly(True)
        self.flow_scene_folder.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        folder_ref_layout.addWidget(self.flow_scene_folder, 1, 1)
        btn_flow_scene_folder = QPushButton("Chọn thư mục")
        btn_flow_scene_folder.setFixedWidth(120)
        btn_flow_scene_folder.clicked.connect(self.browse_flow_scene_folder)
        folder_ref_layout.addWidget(btn_flow_scene_folder, 1, 2)

        # Style folder
        folder_ref_layout.addWidget(QLabel("Style Folder:"), 2, 0)
        self.flow_style_folder = QLineEdit()
        self.flow_style_folder.setPlaceholderText("Chọn thư mục chứa ảnh Style...")
        self.flow_style_folder.setReadOnly(True)
        self.flow_style_folder.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        folder_ref_layout.addWidget(self.flow_style_folder, 2, 1)
        btn_flow_style_folder = QPushButton("Chọn thư mục")
        btn_flow_style_folder.setFixedWidth(120)
        btn_flow_style_folder.clicked.connect(self.browse_flow_style_folder)
        folder_ref_layout.addWidget(btn_flow_style_folder, 2, 2)

        flow_ref_multiple_layout.addLayout(folder_ref_layout)
        self.flow_ref_multiple_card.setVisible(False)  # Hidden by default
        container_layout.addWidget(self.flow_ref_multiple_card)

        # ===== FOLDER STRUCTURE MODE =====
        self.flow_ref_folder_structure_card, flow_ref_folder_structure_layout = self._create_flow_card("Folder Structure Mode")
        ref_folder_structure_desc = QLabel("Chọn folder cha chứa các file .txt và folder ảnh cùng tên. Hệ thống sẽ tự động map file .txt với folder cùng tên (ví dụ: 1.txt ↔ folder 1). Kết quả sẽ lưu vào folder result_{tên}.")
        ref_folder_structure_desc.setObjectName("flowSubLabel")
        ref_folder_structure_desc.setWordWrap(True)
        flow_ref_folder_structure_layout.addWidget(ref_folder_structure_desc)

        folder_structure_row = QHBoxLayout()
        folder_structure_row.addWidget(QLabel("Folder cha:"))
        self.flow_folder_structure_input = QLineEdit()
        self.flow_folder_structure_input.setPlaceholderText("Chọn folder cha chứa các folder con...")
        self.flow_folder_structure_input.setReadOnly(True)
        self.flow_folder_structure_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        folder_structure_row.addWidget(self.flow_folder_structure_input, stretch=1)
        btn_flow_folder_structure = QPushButton("Chọn folder cha")
        btn_flow_folder_structure.setFixedWidth(130)
        btn_flow_folder_structure.clicked.connect(self.browse_flow_folder_structure)
        folder_structure_row.addWidget(btn_flow_folder_structure)
        flow_ref_folder_structure_layout.addLayout(folder_structure_row)

        # Table hiển thị các folder con đã phát hiện
        self.flow_folder_structure_table = QTableWidget()
        self.flow_folder_structure_table.setColumnCount(4)
        self.flow_folder_structure_table.setHorizontalHeaderLabels(["STT", "Folder Con", "Số Ảnh", "Số Prompt"])
        self.flow_folder_structure_table.setMinimumHeight(150)
        self.flow_folder_structure_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.flow_folder_structure_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.flow_folder_structure_table.verticalHeader().setVisible(False)
        self.flow_folder_structure_table.setColumnWidth(0, 50)
        self.flow_folder_structure_table.setColumnWidth(1, 200)
        self.flow_folder_structure_table.setColumnWidth(2, 80)
        self.flow_folder_structure_table.horizontalHeader().setStretchLastSection(True)
        flow_ref_folder_structure_layout.addWidget(self.flow_folder_structure_table)

        self.flow_ref_folder_structure_card.setVisible(False)  # Hidden by default
        container_layout.addWidget(self.flow_ref_folder_structure_card)

        # ===== REFERENCE IMAGE DIRECTORY (ẩn khỏi UI) =====
        ref_dir_card, ref_dir_layout = self._create_flow_card("Thư mục ảnh tham chiếu")
        ref_dir_row = QHBoxLayout()
        self.flow_ref_dir_input = QLineEdit()
        self.flow_ref_dir_input.setPlaceholderText("Chọn thư mục chứa ảnh tham chiếu…")
        self.flow_ref_dir_input.setReadOnly(True)
        self.flow_ref_dir_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #d0d7e2;
                color: #0f172a;
                padding: 10px;
            }
        """)
        btn_browse_ref_dir = QPushButton("Chọn")
        btn_browse_ref_dir.setFixedWidth(90)
        btn_browse_ref_dir.clicked.connect(self._browse_flow_ref_dir)
        btn_browse_ref_dir.setStyleSheet("""
            QPushButton {
                background: #e0f2fe;
                border-radius: 10px;
                color: #0369a1;
                padding: 8px 14px;
                border: 1px solid #7dd3fc;
                font-weight: 600;
            }
            QPushButton:hover { background: #bae6fd; }
        """)
        ref_dir_row.addWidget(self.flow_ref_dir_input)
        ref_dir_row.addWidget(btn_browse_ref_dir)
        ref_dir_layout.addLayout(ref_dir_row)
        ref_dir_card.setVisible(False)
        container_layout.addWidget(ref_dir_card)

        # ===== ACTION BUTTONS =====
        action_card, action_layout = self._create_flow_card("Thao tác")

        self.btn_flow_run = QPushButton("CHẠY NGAY")
        self.btn_flow_run.setFixedHeight(50)
        self.btn_flow_run.setStyleSheet("""
            QPushButton {
                background: #16a34a;
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                border: none;
                border-radius: 12px;
                padding: 12px;
            }
            QPushButton:hover { background: #15803d; }
            QPushButton:disabled {
                background: #94a3b8;
                color: #e2e8f0;
            }
        """)
        self.btn_flow_run.clicked.connect(self.on_flow_run_clicked)
        action_layout.addWidget(self.btn_flow_run)

        self.btn_flow_pause = QPushButton("TẠM DỪNG")
        self.btn_flow_pause.setFixedHeight(50)
        self.btn_flow_pause.setEnabled(False)
        self.btn_flow_pause.setStyleSheet("""
            QPushButton {
                background: #eab308;
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                border: none;
                border-radius: 12px;
                padding: 12px;
            }
            QPushButton:hover { background: #ca8a04; }
            QPushButton:disabled {
                background: #94a3b8;
                color: #e2e8f0;
            }
        """)
        action_layout.addWidget(self.btn_flow_pause)

        self.btn_flow_stop = QPushButton("DỪNG")
        self.btn_flow_stop.setFixedHeight(50)
        self.btn_flow_stop.setEnabled(False)
        self.btn_flow_stop.setStyleSheet("""
            QPushButton {
                background: #dc2626;
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                border: none;
                border-radius: 12px;
                padding: 12px;
            }
            QPushButton:hover { background: #b91c1c; }
            QPushButton:disabled {
                background: #94a3b8;
                color: #e2e8f0;
            }
        """)
        self.btn_flow_stop.clicked.connect(self.on_flow_stop_clicked)
        action_layout.addWidget(self.btn_flow_stop)

        # Nút chạy lại file lỗi
        self.btn_flow_retry_failed = QPushButton("🔄 Chạy lại file lỗi")
        self.btn_flow_retry_failed.setFixedHeight(40)
        self.btn_flow_retry_failed.setEnabled(False)
        self.btn_flow_retry_failed.setStyleSheet("""
            QPushButton {
                background: #f59e0b;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover { background: #d97706; }
            QPushButton:disabled {
                background: #94a3b8;
                color: #e2e8f0;
            }
        """)
        self.btn_flow_retry_failed.clicked.connect(self.on_flow_retry_failed_clicked)
        action_layout.addWidget(self.btn_flow_retry_failed)

        self.flow_status_label = QLabel("Chưa chạy")
        self.flow_status_label.setAlignment(Qt.AlignCenter)
        self.flow_status_label.setStyleSheet("color: #475569; font-style: italic; padding-top: 6px;")
        action_layout.addWidget(self.flow_status_label)
        container_layout.addWidget(action_card)

        container_layout.addStretch()
        self.refresh_flow_reference_list()
        self.update_flow_prompt_count()
        return widget

    def _create_flow_card(self, title: str) -> Tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("flowCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        header = QLabel(title)
        header.setObjectName("flowCardTitle")
        layout.addWidget(header)
        return card, layout

    def build_flow_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        widget.setStyleSheet("""
            QWidget#flowResultPanel {
                background: #ffffff;
                border-radius: 16px;
                border: 1px solid #e2e8f0;
            }
        """)
        widget.setObjectName("flowResultPanel")

        # ==================== HEADER ====================
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        
        title_label = QLabel("Kết quả")
        title_label.setStyleSheet("color: #0f172a; font-size: 15px; font-weight: 700;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # ==================== SUMMARY STATUS BAR ====================
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background: #f8fafc;
                border-radius: 10px;
                border: 1px solid #e2e8f0;
                padding: 4px;
            }
        """)
        status_bar = QHBoxLayout(status_frame)
        status_bar.setContentsMargins(12, 8, 12, 8)
        status_bar.setSpacing(20)

        self.flow_status_total = QLabel("Tổng: 0")
        self.flow_status_total.setStyleSheet("color: #334155; font-weight: 600; font-size: 13px;")
        status_bar.addWidget(self.flow_status_total)

        self.flow_status_running = QLabel("Đang chạy: 0")
        self.flow_status_running.setStyleSheet("color: #2563eb; font-weight: 600; font-size: 13px;")
        status_bar.addWidget(self.flow_status_running)

        self.flow_status_success = QLabel("Thành công: 0")
        self.flow_status_success.setStyleSheet("color: #16a34a; font-weight: 600; font-size: 13px;")
        status_bar.addWidget(self.flow_status_success)

        self.flow_status_error = QLabel("Lỗi: 0")
        self.flow_status_error.setStyleSheet("color: #dc2626; font-weight: 600; font-size: 13px;")
        status_bar.addWidget(self.flow_status_error)

        status_bar.addStretch()
        layout.addWidget(status_frame)

        # ==================== TASK GRID (QTableWidget) ====================
        self.flow_task_grid = QTableWidget()
        self.flow_task_grid.setColumnCount(6)
        self.flow_task_grid.setHorizontalHeaderLabels(["#", "Trạng thái", "Ảnh tham chiếu", "Kết quả", "Nội dung", "Chi tiết"])
        self.flow_task_grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.flow_task_grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.flow_task_grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.flow_task_grid.verticalHeader().setVisible(False)
        self.flow_task_grid.setShowGrid(False)
        self.flow_task_grid.setAlternatingRowColors(True)
        self.flow_task_grid.setStyleSheet("""
            QTableWidget {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                font-size: 13px;
                outline: none;
            }
            QTableWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #f1f5f9;
            }
            QTableWidget::item:alternate {
                background: #fafbfc;
            }
            QTableWidget::item:selected {
                background: #eff6ff;
                color: #1e40af;
            }
            QTableWidget::item:hover {
                background: #f0f9ff;
            }
            QHeaderView::section {
                background: #f1f5f9;
                color: #475569;
                font-weight: 700;
                font-size: 12px;
                border: none;
                border-bottom: 2px solid #cbd5e1;
                padding: 8px 10px;
            }
            QScrollBar:vertical {
                background: #f8fafc;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94a3b8;
            }
        """)

        # Column widths
        header = self.flow_task_grid.horizontalHeader()
        # Col 0: STT
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.flow_task_grid.setColumnWidth(0, 40)
        # Col 1: Trạng thái
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.flow_task_grid.setColumnWidth(1, 160)
        # Col 2: Ảnh tham chiếu
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.flow_task_grid.setColumnWidth(2, 300)
        # Col 3: Preview (nhỏ, cố định)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.flow_task_grid.setColumnWidth(3, 110)
        # Col 4: Prompt
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        # Col 5: Status (hiển thị trạng thái chi tiết + lỗi dễ hiểu)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.flow_task_grid.setColumnWidth(5, 170)

        layout.addWidget(self.flow_task_grid, 1)

        # ==================== BOTTOM TOOLBAR ====================
        toolbar_frame = QFrame()
        toolbar_frame.setStyleSheet("""
            QFrame {
                background: #f8fafc;
                border-radius: 10px;
                border: 1px solid #e2e8f0;
            }
        """)
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(10, 8, 10, 8)
        toolbar.setSpacing(8)

        btn_base = """
            QPushButton {{
                background: {bg};
                color: {fg};
                border: none;
                border-radius: 8px;
                padding: 7px 16px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:disabled {{ background: #e2e8f0; color: #94a3b8; }}
        """

        self.btn_add_images = QPushButton("➕ Thêm ảnh")
        self.btn_add_images.setFixedHeight(34)
        self.btn_add_images.setCursor(Qt.PointingHandCursor)
        self.btn_add_images.setStyleSheet(btn_base.format(bg="#3b82f6", fg="white", hover="#2563eb"))
        toolbar.addWidget(self.btn_add_images)

        self.btn_delete_selected = QPushButton("Xóa chọn")
        self.btn_delete_selected.setFixedHeight(34)
        self.btn_delete_selected.setCursor(Qt.PointingHandCursor)
        self.btn_delete_selected.setStyleSheet(btn_base.format(bg="#f1f5f9", fg="#475569", hover="#e2e8f0"))
        toolbar.addWidget(self.btn_delete_selected)

        self.btn_delete_all = QPushButton("Xóa kết quả")
        self.btn_delete_all.setFixedHeight(34)
        self.btn_delete_all.setCursor(Qt.PointingHandCursor)
        self.btn_delete_all.setStyleSheet(btn_base.format(bg="#fef2f2", fg="#b91c1c", hover="#fecaca"))
        toolbar.addWidget(self.btn_delete_all)

        # ===== BULK REFERENCE IMAGE BUTTONS =====
        self.btn_import_images_all = QPushButton("Thêm ảnh tham chiếu")
        self.btn_import_images_all.setFixedHeight(34)
        self.btn_import_images_all.setCursor(Qt.PointingHandCursor)
        self.btn_import_images_all.setStyleSheet(btn_base.format(bg="#f0fdf4", fg="#166534", hover="#dcfce7"))
        toolbar.addWidget(self.btn_import_images_all)

        self.btn_clear_images_all = QPushButton("Xóa ảnh tham chiếu")
        self.btn_clear_images_all.setFixedHeight(34)
        self.btn_clear_images_all.setCursor(Qt.PointingHandCursor)
        self.btn_clear_images_all.setStyleSheet(btn_base.format(bg="#fef2f2", fg="#b91c1c", hover="#fecaca"))
        toolbar.addWidget(self.btn_clear_images_all)

        toolbar.addStretch()

        self.btn_retry_failed = QPushButton("Chạy lại lỗi")
        self.btn_retry_failed.setFixedHeight(34)
        self.btn_retry_failed.setCursor(Qt.PointingHandCursor)
        self.btn_retry_failed.setStyleSheet(btn_base.format(bg="#fef3c7", fg="#92400e", hover="#fde68a"))
        toolbar.addWidget(self.btn_retry_failed)

        self.btn_flow_stop_toolbar = QPushButton("Dừng")
        self.btn_flow_stop_toolbar.setFixedHeight(34)
        self.btn_flow_stop_toolbar.setCursor(Qt.PointingHandCursor)
        self.btn_flow_stop_toolbar.setEnabled(False)
        self.btn_flow_stop_toolbar.setStyleSheet(btn_base.format(bg="#dc2626", fg="white", hover="#b91c1c"))
        self.btn_flow_stop_toolbar.clicked.connect(self.on_flow_stop_clicked)
        toolbar.addWidget(self.btn_flow_stop_toolbar)

        self.btn_run_selected = QPushButton("Tạo ảnh")
        self.btn_run_selected.setFixedHeight(34)
        self.btn_run_selected.setCursor(Qt.PointingHandCursor)
        self.btn_run_selected.setStyleSheet(btn_base.format(bg="#10b981", fg="white", hover="#059669"))
        self.btn_run_selected.clicked.connect(self.on_flow_run_clicked)
        toolbar.addWidget(self.btn_run_selected)
        self.log(f"DEBUG: btn_run_selected created and connected to on_flow_run_clicked")

        layout.addWidget(toolbar_frame)

        # ==================== BACKWARD COMPAT: Old widget refs ====================
        # Keep old widget references alive so existing methods don't crash
        self.flow_result_success_label = QLabel("0 success")
        self.flow_result_success_label.setVisible(False)
        self.flow_result_hint = QLabel("")
        self.flow_result_hint.setVisible(False)
        self.flow_folder_selector = QComboBox()
        self.flow_folder_selector.setVisible(False)
        self.flow_result_view_stack = QStackedWidget()
        self.flow_result_view_stack.setVisible(False)
        self.flow_results_container = QWidget()
        self.flow_results_grid = QGridLayout(self.flow_results_container)
        self.flow_result_tiles = []
        self.flow_result_table = QTableWidget()
        self.flow_result_table.setColumnCount(7)
        self.flow_result_table.setVisible(False)
        self.flow_page_info = QLabel("")
        self.flow_page_info.setVisible(False)
        self.btn_flow_prev_page = QPushButton()
        self.btn_flow_prev_page.setVisible(False)
        self.btn_flow_next_page = QPushButton()
        self.btn_flow_next_page.setVisible(False)
        self.btn_flow_show_all = QPushButton()
        self.btn_flow_show_all.setVisible(False)

        # ==================== CONNECT TOOLBAR SIGNALS ====================
        self.btn_add_images.clicked.connect(self._on_flow_add_images)
        self.btn_delete_selected.clicked.connect(self._on_flow_delete_selected)
        self.btn_delete_all.clicked.connect(self._on_flow_delete_all)
        self.btn_import_images_all.clicked.connect(self._on_flow_import_images_all)
        self.btn_clear_images_all.clicked.connect(self._on_flow_clear_images_all)
        self.btn_retry_failed.clicked.connect(self._on_flow_retry_failed)
        self.btn_run_selected.clicked.connect(self.on_flow_run_clicked)

        return widget

    def create_flow_result_tile(self, index: int):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border-radius: 16px;
                border: 1px solid #e4e7ec;
                box-shadow: 0px 8px 20px rgba(15, 23, 42, 0.05);
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        image = QLabel("Chưa có ảnh")
        image.setAlignment(Qt.AlignCenter)
        image.setFixedHeight(160)
        image.setStyleSheet("""
            QLabel {
                background: #f8fafc;
                border-radius: 12px;
                color: #94a3b8;
                border: 1px solid #e2e8f0;
            }
        """)
        image.setWordWrap(True)
        card_layout.addWidget(image)

        caption = QLabel(f"Prompt {index}")
        caption.setStyleSheet("color: #0f172a; font-weight: 600;")
        caption.setWordWrap(True)
        card_layout.addWidget(caption)

        status = QLabel("Trạng thái: Pending")
        status.setStyleSheet("color: #475569; font-size: 11px;")
        card_layout.addWidget(status)

        return card, image, caption, status

    def update_flow_prompt_count(self):
        if not hasattr(self, "flow_prompt_input"):
            return
        prompts = [line.strip() for line in self.flow_prompt_input.toPlainText().splitlines() if line.strip()]
        self.flow_prompt_count_label.setText(f"{len(prompts)} prompt")

    def refresh_flow_reference_list(self):
        if not hasattr(self, "flow_reference_list"):
            return
        self.flow_reference_list.clear()
        for path in self.flow_reference_paths:
            img_path = Path(path)
            if not img_path.exists():
                continue
            
            # Tạo custom widget với preview ảnh
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(8)
            
            # Preview ảnh
            img_label = QLabel()
            pix = QPixmap(str(img_path.resolve()))
            if not pix.isNull():
                # Scale ảnh để fit trong 80x80
                scaled = pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                img_label.setPixmap(scaled)
            else:
                img_label.setText("❌")
                img_label.setStyleSheet("color: red; font-size: 20px;")
            img_label.setFixedSize(80, 80)
            img_label.setStyleSheet("border: 1px solid #d0d7e2; border-radius: 4px; background: #f8fafc;")
            img_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(img_label)
            
            # Tên file
            name_label = QLabel(img_path.name)
            name_label.setWordWrap(True)
            name_label.setToolTip(str(img_path.resolve()))
            layout.addWidget(name_label, 1)
            
            # Set widget vào list item
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.flow_reference_list.addItem(item)
            self.flow_reference_list.setItemWidget(item, widget)

    def browse_flow_output_dir(self):
        initial_dir = self.flow_output_input.text() if hasattr(self, "flow_output_input") else ""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục lưu ảnh Flow",
            initial_dir or str(Path.cwd())
        )
        if directory and hasattr(self, "flow_output_input"):
            self.flow_output_input.setText(directory)
            self.log(f"📁 Flow output folder: {directory}")

    def _browse_flow_ref_dir(self):
        """Browse for reference image directory."""
        initial_dir = self.flow_ref_dir_input.text() if hasattr(self, "flow_ref_dir_input") else ""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục ảnh tham chiếu",
            initial_dir or str(Path.cwd())
        )
        if directory and hasattr(self, "flow_ref_dir_input"):
            self.flow_ref_dir_input.setText(directory)
            self.log(f"📁 Flow reference image dir: {directory}")

    def _get_flow_output_dir(self) -> Path:
        target_dir = None
        if hasattr(self, "flow_output_input"):
            text = self.flow_output_input.text().strip()
            if text:
                target_dir = Path(text)
        if target_dir is None:
            # Fallback mặc định: Downloads/flow_images (tránh dùng Desktop/CWD)
            target_dir = Path.home() / "Downloads" / "flow_images"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Nếu tạo không được, fallback về CWD/downloaded_images/flow
            target_dir = Path.cwd() / "downloaded_images" / "flow"
            target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def browse_flow_prompt_file(self):
        """Select a single .txt prompt file for Flow generation."""
        if self.flow_is_running or self.flow_batch_active:
            QMessageBox.information(self, "Đang chạy", "Không thể thay đổi file khi đang chạy.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file prompt (.txt)",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".txt"):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn file .txt hợp lệ!")
            return
        
        # ✅ Clear toàn bộ state trước khi load file mới
        self._clear_flow_batch_state()
        
        path_obj = Path(file_path)
        self.flow_prompt_file_input.setText(file_path)
        # ✅ Validate: Clear folder inputs khi chọn file
        if hasattr(self, "flow_prompt_folder_input"):
            self.flow_prompt_folder_input.clear()
        if hasattr(self, "flow_folder_structure_input"):
            self.flow_folder_structure_input.clear()
            self.flow_folder_structure_path = None
            self.flow_folder_structure_subfolders = []
            if hasattr(self, "flow_folder_structure_table"):
                self.flow_folder_structure_table.setRowCount(0)
        
        # ✅ Lưu file path hiện tại để dùng cho save logic
        self.flow_current_txt_file = path_obj
        
        # ✅ Đọc prompts và populate grid ngay lập tức
        prompts = self._load_prompts_from_file(path_obj)
        if not prompts:
            QMessageBox.warning(self, "File rỗng", f"File '{path_obj.name}' không chứa prompt hợp lệ.")
            return
        
        # Populate grid với prompts từ file
        model_code = self.flow_model_combo.currentData() if hasattr(self, "flow_model_combo") else "GEM_PIX_2"
        aspect_ratio = self.flow_aspect_combo.currentData() if hasattr(self, "flow_aspect_combo") else "IMAGE_ASPECT_RATIO_LANDSCAPE"
        reference_paths = list(self.flow_reference_paths)
        base_seed = random.randint(1, 999999)
        self._flow_create_tasks_from_prompts(prompts, model_code, aspect_ratio, reference_paths, base_seed)
        
        # Hiển thị batch table cho tracking
        self.flow_batch_files = [path_obj]
        self.populate_flow_batch_table(self.flow_batch_files)
        self.log(f"📄 Flow prompt file: {path_obj.name} ({len(prompts)} prompts → grid)")

    def browse_flow_prompt_folder(self):
        """Select a folder that contains multiple .txt files for Flow batch generation."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa file .txt"
        )
        if not folder_path:
            return
        txt_files = sorted(Path(folder_path).glob("*.txt"))
        if not txt_files:
            QMessageBox.warning(self, "Cảnh báo", f"Thư mục '{folder_path}' không chứa file .txt nào!")
            return
        
        # ✅ Clear toàn bộ state trước khi load thư mục mới
        self._clear_flow_batch_state()
        
        self.flow_prompt_folder_input.setText(folder_path)
        # ✅ Validate: Clear file input và folder structure khi chọn folder
        if hasattr(self, "flow_prompt_file_input"):
            self.flow_prompt_file_input.clear()
        if hasattr(self, "flow_folder_structure_input"):
            self.flow_folder_structure_input.clear()
            self.flow_folder_structure_path = None
            self.flow_folder_structure_subfolders = []
            if hasattr(self, "flow_folder_structure_table"):
                self.flow_folder_structure_table.setRowCount(0)
        self.flow_batch_files = txt_files
        self.populate_flow_batch_table(self.flow_batch_files)
        self.log(f"📁 Flow prompt folder: {folder_path} ({len(txt_files)} file .txt)")

    def _clear_flow_batch_state(self):
        """Clear toàn bộ state của Flow batch để load lại từ đầu (giống như import mới)."""
        # Clear input fields
        if hasattr(self, "flow_prompt_file_input"):
            self.flow_prompt_file_input.clear()
        if hasattr(self, "flow_prompt_folder_input"):
            self.flow_prompt_folder_input.clear()
        
        # Clear current txt file reference
        self.flow_current_txt_file = None
        
        # Clear batch files và queue
        self.flow_batch_files = []
        self.flow_batch_queue = []
        self.flow_batch_params = {}
        self.flow_batch_active = False
        self.flow_batch_status = {}
        
        # Clear job tracking
        self.flow_active_jobs = []
        self.flow_failed_files = []
        self.flow_file_job_mapping = {}
        self.flow_file_output_mapping = {}
        
        # Clear results tracking
        self.flow_results_total = 0
        self.flow_results_success = 0
        self.flow_last_seed = None
        self.flow_is_running = False
        
        # Clear folder structure results và inputs
        if hasattr(self, "flow_folder_results"):
            self.flow_folder_results = {}
        if hasattr(self, "flow_current_folder_view"):
            self.flow_current_folder_view = None
        if hasattr(self, "flow_folder_structure_input"):
            self.flow_folder_structure_input.clear()
        self.flow_folder_structure_path = None
        self.flow_folder_structure_subfolders = []
        if hasattr(self, "flow_folder_structure_table"):
            self.flow_folder_structure_table.setRowCount(0)
        
        # Clear multiple-to-image mapping
        if hasattr(self, "flow_m2i_image_mapping"):
            self.flow_m2i_image_mapping = {}
        
        # Clear table
        self._clear_flow_batch_table()
        
        # Disable retry button
        if hasattr(self, "btn_flow_retry_failed"):
            self.btn_flow_retry_failed.setEnabled(False)
        
        # Clear task grid
        if hasattr(self, "flow_tasks"):
            self.flow_tasks.clear()
        if hasattr(self, "flow_task_grid"):
            self.flow_task_grid.setRowCount(0)
        if hasattr(self, "_flow_update_summary_bar"):
            self._flow_update_summary_bar()

    def clear_flow_prompt_sources(self):
        """Clear selected Flow prompt sources (file/folder)."""
        self._clear_flow_batch_state()
        self.log("🧹 Đã xóa danh sách file .txt cho Flow batch")

    def populate_flow_batch_table(self, txt_files: List[Path]):
        """Populate Flow batch table with list of .txt files."""
        if not hasattr(self, "flow_batch_table"):
            return
        table = self.flow_batch_table
        table.setRowCount(0)
        self.flow_batch_status = {}
        for idx, txt_file in enumerate(txt_files, 1):
            prompts = self._load_prompts_from_file(txt_file)
            num_prompts = len(prompts)
            row = table.rowCount()
            table.insertRow(row)
            
            # Lưu full path vào UserRole để tra cứu lại khi cần
            stt_item = QTableWidgetItem(str(idx))
            stt_item.setData(Qt.ItemDataRole.UserRole, str(txt_file))
            table.setItem(row, 0, stt_item)

            name_item = QTableWidgetItem(txt_file.name)
            name_item.setData(Qt.ItemDataRole.UserRole, str(txt_file))
            table.setItem(row, 1, name_item)

            table.setItem(row, 2, QTableWidgetItem(str(num_prompts)))
            status_item = QTableWidgetItem("Pending")
            table.setItem(row, 3, status_item)
            self.flow_batch_status[str(txt_file)] = {
                "row": row,
                "total": num_prompts,
            }
        if txt_files:
            self.log(f"📋 Flow batch: {len(txt_files)} file .txt đã được load vào danh sách")

    def _update_flow_batch_status(self, file_path: Path, status: str):
        key = str(file_path)
        info = self.flow_batch_status.get(key)
        if not info or not hasattr(self, "flow_batch_table"):
            return
        row = info.get("row")
        if row is None or row >= self.flow_batch_table.rowCount():
            return
        item = self.flow_batch_table.item(row, 3)
        if item:
            item.setText(status)

    def _clear_flow_batch_table(self):
        if hasattr(self, "flow_batch_table"):
            self.flow_batch_table.setRowCount(0)
        self.flow_batch_status = {}

    def _check_flow_failed_files_from_table(self):
        """Kiểm tra failed files từ batch table (giống Whisk) - trả về danh sách file paths bị lỗi"""
        failed_files = []
        if not hasattr(self, "flow_batch_table"):
            return failed_files
        
        error_keywords = ["Lỗi", "Thất bại", "❌", "Failed", "Fail", "Error"]
        exclude_keywords = ["Hoàn thành", "Completed", "✅", "Đang tạo", "Đang xử lý", "Chờ xử lý", "Processing", "Pending"]
        
        for row in range(self.flow_batch_table.rowCount()):
            status_item = self.flow_batch_table.item(row, 3)  # Cột "Trạng thái"
            if status_item:
                status = status_item.text().strip()
                
                # Kiểm tra kỹ: chỉ lấy status thực sự lỗi
                is_error = any(keyword in status for keyword in error_keywords)
                is_not_processing = not any(keyword in status for keyword in exclude_keywords)
                
                if is_error and is_not_processing:
                    # Lấy file path từ cột "Tên File" (cột 1)
                    file_item = self.flow_batch_table.item(row, 1)
                    if file_item:
                        file_name = file_item.text().strip()
                        # Tìm file path từ flow_batch_files hoặc flow_batch_status
                        file_path = None
                        for path in getattr(self, "flow_batch_files", []):
                            if path.name == file_name:
                                file_path = path
                                break
                        
                        if file_path and file_path not in failed_files:
                            failed_files.append(file_path)
        
        return failed_files

    def _get_failed_jobs_for_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Lấy danh sách jobs bị lỗi từ file mapping - chỉ retry các prompt lỗi, không retry prompt đã thành công"""
        failed_jobs = []
        file_stem = file_path.stem if isinstance(file_path, Path) else str(file_path)
        
        # Lấy jobs từ mapping
        jobs = self.flow_file_job_mapping.get(file_stem, [])
        
        for job in jobs:
            status = job.get("status", "")
            # Chỉ lấy jobs chưa thành công (failed hoặc chưa có status)
            if status != "success":
                # Copy job để không ảnh hưởng original
                failed_job = job.copy()
                # Reset retry counter để thử lại
                failed_job["_retry_non_429"] = 0
                # ✅ Lưu file_stem để retry worker biết job thuộc file nào
                failed_job["file_stem"] = file_stem
                failed_jobs.append(failed_job)
        
        if failed_jobs:
            self.log(f"📋 File {file_stem}: {len(failed_jobs)}/{len(jobs)} prompt(s) cần chạy lại")
        
        return failed_jobs

    def _load_prompts_from_file(self, file_path: Path) -> List[str]:
        """Read prompts from a txt file."""
        if not file_path.exists():
            self.log(f"❌ File không tồn tại: {file_path}")
            return []
        
        prompts: List[str] = []
        encodings = ["utf-8", "utf-8-sig", "cp1258"]
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    all_lines = f.readlines()
                    prompts = [line.strip() for line in all_lines if line.strip()]
                if prompts:
                    self.log(f"✅ Đọc {len(prompts)} prompt(s) từ {file_path.name} (encoding: {enc})")
                break
            except Exception as e:
                continue
        if not prompts:
            try:
                with open(file_path, "r") as f:
                    all_lines = f.readlines()
                    prompts = [line.strip() for line in all_lines if line.strip()]
                if prompts:
                    self.log(f"✅ Đọc {len(prompts)} prompt(s) từ {file_path.name} (encoding: default)")
            except Exception as e:
                self.log(f"❌ Lỗi đọc {file_path.name}: {e}")
                return []
        
        if not prompts:
            self.log(f"⚠️ File {file_path.name} không có prompt hợp lệ (file có thể rỗng hoặc chỉ có dòng trống)")
        
        return prompts

    def _collect_flow_prompts_from_editor(self) -> List[str]:
        if not hasattr(self, "flow_prompt_input"):
            return []
        return [line.strip() for line in self.flow_prompt_input.toPlainText().splitlines() if line.strip()]

    def _build_flow_jobs(self, prompts: List[str], variants: int, base_seed: Optional[int], task_grid_rows: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        timestamp = int(time.time() * 1000)
        if not base_seed or base_seed <= 0:
            base_seed = random.randint(1, 999999)
        for prompt_idx, prompt in enumerate(prompts):
            # task_grid_row maps prompt_idx to actual row in Task Grid
            grid_row = task_grid_rows[prompt_idx] if task_grid_rows and prompt_idx < len(task_grid_rows) else prompt_idx
            for variation_idx in range(variants):
                session_id = f";{timestamp + prompt_idx * 100 + variation_idx}"
                jobs.append({
                    "prompt": prompt,
                    "prompt_idx": prompt_idx,
                    "task_grid_row": grid_row,
                    "variation_idx": variation_idx,
                    "seed": base_seed,
                    "session_id": session_id,
                })
        return jobs

    def _start_flow_generation(
        self,
        prompts: List[str],
        variants: int,
        model_code: str,
        aspect_ratio: str,
        reference_paths: List[str],
        output_dir: Path,
        base_seed: int,
        batch_context: Optional[Dict[str, Any]] = None,
        task_grid_rows: Optional[List[int]] = None,
    ) -> bool:
        prompts = [p.strip() for p in prompts if p.strip()]
        if not prompts:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Không tìm thấy prompt hợp lệ để chạy Flow.")
            return False
        folder_label = batch_context["label"] if batch_context and "label" in batch_context else "Run"
        jobs = self.update_flow_result_tiles(prompts, variants, base_seed, folder_label, batch_context, task_grid_rows=task_grid_rows)
        if not jobs:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Không tạo được danh sách công việc Flow.")
            return False
        
        # Track file mapping nếu có batch_context
        if batch_context and "file_path" in batch_context:
            file_path = batch_context["file_path"]
            file_stem = file_path.stem
            self.flow_file_job_mapping[file_stem] = jobs.copy()  # Lưu jobs với tile_index
            self.flow_file_output_mapping[file_stem] = output_dir  # Lưu output_dir
        
        # ✅ Reset stop_event khi bắt đầu worker
        if hasattr(self, 'stop_event'):
            self.stop_event.clear()
        
        self.flow_is_running = True
        label = batch_context["label"] if batch_context and "label" in batch_context else f"{len(prompts)} prompt(s)"
        self._flow_enable_run_button(False)
        self._flow_update_status_text(f"Đang xử lý {label} ({len(jobs)} ảnh)…")
        self._flow_update_hint_text("Đang chuẩn bị cookie/token…")
        log_msg = (
            f"🚀 Flow run: {len(prompts)} prompt(s), variants={variants}, seed={base_seed}, "
            f"refs={len(reference_paths)}, model={model_code}"
        )
        if batch_context and "label" in batch_context:
            log_msg += f", file={batch_context['label']}"
        self.log(log_msg)
        worker = threading.Thread(
            target=self._flow_generation_worker,
            args=(prompts, variants, jobs, model_code, aspect_ratio, reference_paths, output_dir, batch_context),
            daemon=True,
        )
        worker.start()
        return True

    def _start_next_flow_batch(self):
        self.log(f"🔍 _start_next_flow_batch called - queue length: {len(self.flow_batch_queue)}, batch_active: {self.flow_batch_active}")
        
        if not self.flow_batch_queue:
            self.flow_batch_active = False
            self._flow_update_status_text("Batch Flow hoàn tất")
            self._flow_update_hint_text("Đã xử lý xong tất cả file .txt")
            self._flow_enable_run_button(True)
            # ✅ Unlock grid khi batch hoàn tất
            self._flow_lock_grid(False)
            self.log("🎉 Flow batch đã hoàn tất")
            
            # ✅ POPUP THÔNG BÁO THÀNH CÔNG (chỉ khi thành công, không popup lỗi)
            if hasattr(self, 'flow_results_success') and self.flow_results_success > 0:
                try:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("🎉 Hoàn thành!")
                    msg.setText(f"Đã tạo thành công {self.flow_results_success} ảnh Banana Pro!")
                    msg.setInformativeText("Ảnh đã được tải về thư mục đầu ra.")
                    msg.exec()
                except Exception:
                    pass
            return
        
        params = self.flow_batch_params or {}
        variants = params.get("variants", 1)
        model_code = params.get("model_code", "GEM_PIX_2")
        aspect_ratio = params.get("aspect_ratio", "IMAGE_ASPECT_RATIO_LANDSCAPE")
        reference_paths = params.get("reference_paths", [])
        output_root: Optional[Path] = params.get("output_root")
        if output_root is None:
            output_root = self._get_flow_output_dir()
        batch_mode = params.get("mode", "Normal")
        
        current_path = self.flow_batch_queue.pop(0)
        
        # ✅ Khởi tạo prompts để tránh UnboundLocalError
        prompts = []
        
        # Xử lý Folder Structure mode
        if batch_mode == "Folder-Structure":
            # ✅ LOGIC MỚI: current_path là index (int) vào flow_folder_structure_subfolders
            if not isinstance(current_path, int):
                self.log(f"⚠️ Invalid index trong queue: {current_path}, bỏ qua")
                self.signals.flow_start_next_batch.emit()
                return
            
            if current_path >= len(self.flow_folder_structure_subfolders):
                self.log(f"⚠️ Index {current_path} vượt quá danh sách, bỏ qua")
                self.signals.flow_start_next_batch.emit()
                return
            
            # Lấy thông tin từ index
            subfolder_info = self.flow_folder_structure_subfolders[current_path]
            txt_file = subfolder_info.get("txt_file")
            image_folder = subfolder_info.get("image_folder")
            pair_name = subfolder_info.get("pair_name", txt_file.stem if txt_file else "unknown")
            
            # Kiểm tra file .txt và folder ảnh
            if not txt_file or not txt_file.exists():
                self.log(f"⚠️ File .txt không tồn tại: {txt_file}, bỏ qua")
                self.signals.flow_start_next_batch.emit()
                return
            
            if not image_folder or not image_folder.exists() or not image_folder.is_dir():
                self.log(f"⚠️ Folder ảnh không tồn tại: {image_folder}, bỏ qua")
                self.signals.flow_start_next_batch.emit()
                return
            
            # Đọc lại prompts từ file .txt để đảm bảo có dữ liệu mới nhất
            self.log(f"🔍 Đang đọc lại file: {txt_file} (exists: {txt_file.exists() if txt_file else False})")
            prompts = self._load_prompts_from_file(txt_file)
            self.log(f"📄 Đọc lại prompts từ {txt_file.name}: {len(prompts)} prompt(s)")
            if prompts:
                self.log(f"📝 Prompt đầu tiên (preview): {prompts[0][:100]}...")
            else:
                self.log(f"⚠️ {txt_file.name} không có prompt hợp lệ, bỏ qua")
                # Thử đọc trực tiếp để debug
                try:
                    with open(txt_file, 'r', encoding='utf-8') as f:
                        raw_lines = f.readlines()
                        self.log(f"🔍 Debug: File có {len(raw_lines)} dòng, dòng đầu: {repr(raw_lines[0][:100]) if raw_lines else 'EMPTY'}")
                except Exception as e:
                    self.log(f"🔍 Debug: Lỗi đọc file: {e}")
                self.signals.flow_start_next_batch.emit()
                return
            
            # ✅ LOGIC MỚI: Map prompt với ảnh dựa trên tên file
            # Lưu danh sách ảnh gốc để dùng cho mapping từng prompt
            all_images = subfolder_info["images"]
            
            # Upload tất cả ảnh với tất cả cookies để cache (sẽ map sau)
            # reference_paths sẽ được set trong batch_context để dùng cho mapping
            reference_paths = [str(img.resolve()) for img in all_images]
            
            # ✅ Output dir: Tạo folder kết quả trong folder cha, tên theo pair_name
            # Ví dụ: folder cha/result_1/ hoặc folder cha/1_result/
            output_dir = self.flow_folder_structure_path / f"result_{pair_name}"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            self.log(f"📁 Flow Folder Structure: Xử lý {txt_file.name} ↔ {image_folder.name} ({len(prompts)} prompts, {len(reference_paths)} ảnh)")
        else:
            # Normal batch mode (file .txt)
            prompts = self._load_prompts_from_file(current_path)
        if not prompts:
            if batch_mode == "Folder-Structure":
                self.log(f"⚠️ Không có prompt hợp lệ, chuyển cặp tiếp theo")
            else:
                self._update_flow_batch_status(current_path, "0 prompt")
                self.log(f"⚠️ {current_path.name} không có prompt, chuyển file khác")
            # Dùng Signal để gọi từ main thread
            self.signals.flow_start_next_batch.emit()
            return
        
        # Sử dụng lại output_dir từ mapping nếu có (khi retry) - chỉ cho Normal mode
        if batch_mode != "Folder-Structure":
            # Với Normal mode, current_path là Path object
            file_stem = current_path.stem if isinstance(current_path, Path) else str(current_path)
            if file_stem in self.flow_file_output_mapping:
                output_dir = self.flow_file_output_mapping[file_stem]
                self.log(f"♻️ Sử dụng lại output_dir từ mapping: {output_dir}")
            else:
                output_dir = output_root / file_stem
                output_dir.mkdir(parents=True, exist_ok=True)
        # Với Folder-Structure mode, output_dir đã được set ở trên (dòng ~4612)
        
        base_seed = random.randint(1, 999999)
        self.flow_last_seed = base_seed
        
        if batch_mode == "Folder-Structure":
            # Không có batch table status cho folder structure
            pass
        else:
            self._update_flow_batch_status(current_path, "Đang chạy…")
        
        # ✅ LOGIC MỚI: Với Folder Structure, label là tên cặp
        if batch_mode == "Folder-Structure":
            label = subfolder_info.get("pair_name", txt_file.stem if txt_file else "unknown")
            file_path_for_context = txt_file  # Dùng txt_file cho context
        else:
            label = current_path.name
            file_path_for_context = current_path
        
        batch_context = {
            "file_path": file_path_for_context,
            "label": label,
            "total_prompts": len(prompts),
            "mode": batch_mode,
        }
        
        # ✅ LOGIC MỚI: Thêm all_images vào batch_context cho Folder-Structure mode
        if batch_mode == "Folder-Structure":
            batch_context["all_images"] = all_images  # List[Path] của ảnh để dùng cho mapping
        started = self._start_flow_generation(
            prompts,
            variants,
            model_code,
            aspect_ratio,
            reference_paths,
            output_dir,
            base_seed,
            batch_context,
        )
        if not started:
            if batch_mode != "Folder-Structure":
                self._update_flow_batch_status(current_path, "Lỗi")
                # Dùng Signal để gọi từ main thread
                self.signals.flow_start_next_batch.emit()

    def _flow_worker_done(self, success: bool, batch_context: Optional[Dict[str, Any]]):
        """Worker thread callback - forward to main thread via signal"""
        if hasattr(self, "signals") and hasattr(self.signals, "flow_worker_done"):
            context_copy = dict(batch_context) if isinstance(batch_context, dict) else batch_context
            self.signals.flow_worker_done.emit(bool(success), context_copy)
        else:
            # Fallback: handle inline (should not happen)
            self._flow_worker_done_main(success, batch_context)

    def _flow_worker_done_main(self, success: bool, batch_context: Optional[Dict[str, Any]]):
        """Runs in main thread after worker completes"""
        if batch_context and "file_path" in batch_context:
            file_path = batch_context["file_path"]
            batch_mode = batch_context.get("mode", "Normal")

            if batch_mode == "Folder-Structure":
                self._flow_store_completed_folder(batch_context)
            
            # Chỉ update batch status nếu không phải Folder Structure mode
            if batch_mode != "Folder-Structure":
                status_text = "✅ Hoàn tất" if success else "❌ Lỗi"
                self._update_flow_batch_status(file_path, status_text)
                # ✅ _update_flow_batch_status đã tự động enable nút retry khi có file fail
            
            # Track failed files (chỉ cho Normal batch mode, không track Folder Structure)
            if batch_mode != "Folder-Structure":
                if not success:
                    if file_path not in self.flow_failed_files:
                        self.flow_failed_files.append(file_path)
                        self.log(f"📝 Đã thêm file lỗi vào danh sách retry: {file_path.name}")
                else:
                    # Remove khỏi failed_files nếu retry thành công
                    if file_path in self.flow_failed_files:
                        self.flow_failed_files.remove(file_path)
                        self.log(f"✅ Đã remove file khỏi danh sách lỗi (retry thành công): {file_path.name}")
        
        # Đảm bảo flow_is_running được set về False
        self.flow_is_running = False
        
        if self.flow_batch_active:
            batch_mode = batch_context.get("mode", "Normal") if batch_context else "Normal"
            remaining = len(self.flow_batch_queue)
            
            if remaining > 0:
                if batch_mode == "Folder-Structure":
                    self.log(f"📋 Flow batch: Còn {remaining} cặp file .txt ↔ folder cần xử lý, tiếp tục...")
                else:
                    self.log(f"📋 Flow batch: Còn {remaining} file .txt cần xử lý, tiếp tục...")
                # Dùng Signal thay vì QTimer vì đang ở worker thread
                self.signals.flow_start_next_batch.emit()
            else:
                self.flow_batch_active = False
                self._flow_enable_run_button(True)
                if batch_mode == "Folder-Structure":
                    self._flow_update_status_text("Folder Structure Flow hoàn tất")
                    self._flow_update_hint_text("Đã xử lý xong tất cả cặp file .txt ↔ folder")
                    self._flow_show_folder_results_initial()
                else:
                    self._flow_update_status_text("Batch Flow hoàn tất")
                    self._flow_update_hint_text("Đã xử lý xong tất cả file .txt")
                
                # ✅ POPUP THÔNG BÁO THÀNH CÔNG (chỉ khi thành công)
                if hasattr(self, 'flow_results_success') and self.flow_results_success > 0:
                    try:
                        self.signals.show_flow_success_popup.emit(self.flow_results_success)
                    except Exception:
                        pass
                
                # ✅ Enable/disable retry button CHỈ SAU KHI TẤT CẢ prompts hoàn thành
                # ✅ Kiểm tra failed files từ table - nếu có fail thì enable, nếu không thì disable
                if batch_mode != "Folder-Structure":
                    if hasattr(self, "btn_flow_retry_failed"):
                        # ✅ Kiểm tra failed files từ table (giống Whisk)
                        failed_files_from_table = self._check_flow_failed_files_from_table()
                        has_failed = len(failed_files_from_table) > 0
                        self.btn_flow_retry_failed.setEnabled(has_failed)
                        if has_failed:
                            self.log(f"✅ Đã enable nút 'Chạy lại file lỗi' sau khi hoàn thành tất cả ({len(failed_files_from_table)} file lỗi)")
                            # ✅ Cập nhật flow_failed_files từ table để đảm bảo đồng bộ
                            self.flow_failed_files = failed_files_from_table
                        else:
                            self.log(f"✅ Không có file lỗi, nút 'Chạy lại file lỗi' đã được disable")
                            self.btn_flow_retry_failed.setEnabled(False)
        else:
            # Enable run button khi không có batch
            self._flow_enable_run_button(True)
            # ✅ Enable/disable retry button CHỈ SAU KHI hoàn thành - kiểm tra từ table
            if hasattr(self, "btn_flow_retry_failed"):
                # ✅ Kiểm tra failed files từ table (giống Whisk)
                failed_files_from_table = self._check_flow_failed_files_from_table()
                has_failed = len(failed_files_from_table) > 0
                self.btn_flow_retry_failed.setEnabled(has_failed)
                if has_failed:
                    self.log(f"✅ Đã enable nút 'Chạy lại file lỗi' sau khi hoàn thành ({len(failed_files_from_table)} file lỗi)")
                    # ✅ Cập nhật flow_failed_files từ table để đảm bảo đồng bộ
                    self.flow_failed_files = failed_files_from_table
                else:
                    self.log(f"✅ Không có file lỗi, nút 'Chạy lại file lỗi' đã được disable")
                    self.btn_flow_retry_failed.setEnabled(False)

    def _flow_show_folder_results_initial(self):
        """Show all results after Folder Structure batch completes (without clearing cards)"""
        # Không làm gì cả vì cards đã được hiển thị trong quá trình xử lý
        # Chỉ log để debug
        self.log(f"📊 Folder Structure hoàn tất - Hiển thị {len(self.flow_result_tiles) if hasattr(self, 'flow_result_tiles') else 0} kết quả")
        
        # Update pagination
        self._flow_update_pagination()

    def _flow_update_pagination(self):
        """Update pagination display - 30 cards per page
        
        Re-layout cards from position 0 in grid for proper ordering.
        """
        if not hasattr(self, "flow_result_tiles") or not hasattr(self, "flow_results_grid"):
            return
        
        grid = self.flow_results_grid
        
        # Check for folder filter
        folder_filter = getattr(self, "flow_current_folder_filter", None)
        
        # Get filtered tiles if folder filter is active
        if folder_filter:
            filtered_tiles = []
            for tile in self.flow_result_tiles:
                job = tile.get("job", {})
                tile_folder = job.get("folder_label", "")
                if folder_filter.lower() in str(tile_folder).lower():
                    filtered_tiles.append(tile)
            display_tiles = filtered_tiles
        else:
            display_tiles = self.flow_result_tiles
        
        total_cards = len(display_tiles)
        cards_per_page = 30
        
        if not hasattr(self, "flow_current_page"):
            self.flow_current_page = 1
        
        total_pages = max(1, (total_cards + cards_per_page - 1) // cards_per_page)
        
        # Adjust current page if needed
        if self.flow_current_page > total_pages:
            self.flow_current_page = total_pages
        
        # Update page info label if exists
        if hasattr(self, "flow_page_info"):
            if folder_filter:
                self.flow_page_info.setText(f"🔍 {folder_filter}: Trang {self.flow_current_page}/{total_pages} ({total_cards} ảnh)")
            else:
                self.flow_page_info.setText(f"Trang {self.flow_current_page}/{total_pages} ({total_cards} ảnh)")
        
        # Update button states
        if hasattr(self, "btn_flow_prev_page"):
            self.btn_flow_prev_page.setEnabled(self.flow_current_page > 1)
        if hasattr(self, "btn_flow_next_page"):
            self.btn_flow_next_page.setEnabled(self.flow_current_page < total_pages)
        
        # Clear grid first - remove all widgets without deleting them
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        
        # Hide all cards first
        for tile in self.flow_result_tiles:
            card = tile.get("card")
            if card:
                card.setVisible(False)
        
        # Calculate page range
        start_idx = (self.flow_current_page - 1) * cards_per_page
        end_idx = min(start_idx + cards_per_page, total_cards)
        
        # Re-layout cards for current page from position 0
        # Tính số cột dựa trên kích thước container
        container_width = self.flow_results_container.width() if self.flow_results_container.width() > 0 else 900
        card_width = 270
        columns = max(1, min(4, container_width // card_width))
        position = 0
        
        for i, tile in enumerate(display_tiles):
            card = tile.get("card")
            if card and start_idx <= i < end_idx:
                row_grid = position // columns
                col_grid = position % columns
                grid.addWidget(card, row_grid, col_grid)
                card.setVisible(True)
                position += 1

    def _flow_goto_page(self, page: int):
        """Go to specific page"""
        if not hasattr(self, "flow_result_tiles"):
            return
        
        # Check for folder filter
        folder_filter = getattr(self, "flow_current_folder_filter", None)
        if folder_filter:
            filtered_tiles = [t for t in self.flow_result_tiles 
                            if folder_filter.lower() in str(t.get("job", {}).get("folder_label", "")).lower()]
            total_cards = len(filtered_tiles)
        else:
            total_cards = len(self.flow_result_tiles)
        
        cards_per_page = 30
        total_pages = max(1, (total_cards + cards_per_page - 1) // cards_per_page)
        
        self.flow_current_page = max(1, min(page, total_pages))
        self._flow_update_pagination()

    def _flow_prev_page(self):
        """Go to previous page"""
        if hasattr(self, "flow_current_page"):
            self._flow_goto_page(self.flow_current_page - 1)

    def _flow_next_page(self):
        """Go to next page"""
        if hasattr(self, "flow_current_page"):
            self._flow_goto_page(self.flow_current_page + 1)
        else:
            self._flow_goto_page(1)

    def _on_flow_batch_table_clicked(self, row: int, column: int):
        """Handle click on batch table row - filter cards by that folder/file"""
        if not hasattr(self, "flow_batch_table"):
            return
        
        # Get file name from row
        file_name_item = self.flow_batch_table.item(row, 1)  # Column 1 = Tên File
        if not file_name_item:
            return
        
        file_name = file_name_item.text()
        if not file_name:
            return
        
        # Filter cards by this folder
        folder_label = Path(file_name).stem if file_name.endswith(".txt") else file_name
        self._flow_filter_cards_by_folder(folder_label)
        self.log(f"🔍 Đang hiển thị kết quả của: {folder_label}")

    def _flow_filter_cards_by_folder(self, folder_label: str = None):
        """Filter cards to show only results from specified folder, or show all if None
        
        Cards are re-layouted from position 0 in grid to maintain proper ordering.
        """
        if not hasattr(self, "flow_result_tiles") or not hasattr(self, "flow_results_grid"):
            return
        
        self.flow_current_folder_filter = folder_label
        grid = self.flow_results_grid
        
        if folder_label is None:
            # Show all cards (với pagination)
            self.flow_current_page = 1
            self._flow_update_pagination()
            return
        
        # Clear grid first
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        
        # Filter cards matching folder_label và re-add vào grid từ vị trí 0
        matching_tiles = []
        # Tính số cột dựa trên kích thước container
        container_width = self.flow_results_container.width() if self.flow_results_container.width() > 0 else 900
        card_width = 270
        columns = max(1, min(4, container_width // card_width))
        position = 0
        
        for tile in self.flow_result_tiles:
            job = tile.get("job", {})
            tile_folder = job.get("folder_label", "")
            card = tile.get("card")
            
            if card:
                if folder_label.lower() in str(tile_folder).lower():
                    matching_tiles.append(tile)
                    # Re-add card vào grid tại vị trí mới
                    row_grid = position // columns
                    col_grid = position % columns
                    grid.addWidget(card, row_grid, col_grid)
                    card.setVisible(True)
                    position += 1
                else:
                    card.setVisible(False)
        
        # Update page info
        if hasattr(self, "flow_page_info"):
            self.flow_page_info.setText(f"Hiển thị: {folder_label} ({len(matching_tiles)} ảnh)")

    def _flow_show_all_cards(self):
        """Show all cards (remove filter)"""
        self.flow_current_folder_filter = None
        self.flow_current_page = 1
        self._flow_update_pagination()
        self.log("📋 Hiển thị tất cả kết quả")

    def _format_flow_caption(self, job: Dict[str, Any]) -> str:
        prefix = f"#{job['prompt_idx'] + 1}.{job['variation_idx'] + 1} • seed {job['seed']}"
        return f"{prefix}\n{job['prompt']}"

    def _flow_reset_result_table(self, row_count: int):
        if hasattr(self, "flow_result_table"):
            self.flow_result_table.setRowCount(row_count)
        self.flow_result_tiles = []
        self._flow_clear_result_grid()

    def _prepare_flow_result_rows(self, jobs: List[Dict[str, Any]], folder_label: str):
        if not hasattr(self, "flow_result_table"):
            return
        # Chuyển sang grid view để hiển thị dạng thẻ
        self._flow_switch_to_grid_view()
        # Ẩn table, vẫn sử dụng cho logic nội bộ (retry/check lỗi)
        table = self.flow_result_table
        if table:
            table.setVisible(False)
        # ✅ flow_result_view_stack là backward compat widget (không có parent layout)
        # KHÔNG setVisible(True) vì sẽ hiện popup trắng
        
        # ✅ TÍCH LŨY ROWS: Không reset table, append rows mới vào cuối
        # Khởi tạo flow_result_tiles nếu chưa có (cho Folder-Structure mode)
        if not hasattr(self, "flow_result_tiles") or self.flow_result_tiles is None:
            self.flow_result_tiles = []
        if not hasattr(self, "flow_active_jobs") or self.flow_active_jobs is None:
            self.flow_active_jobs = []
        
        # Lấy số rows hiện tại (để append vào cuối)
        current_row_count = table.rowCount()
        # Tính tile_index offset (để unique cho mỗi job)
        tile_index_offset = len(self.flow_result_tiles)
        
        table.setUpdatesEnabled(False)
        
        # Append jobs vào active_jobs
        self.flow_active_jobs.extend(jobs)
        # Cập nhật total
        if not hasattr(self, "flow_results_total") or self.flow_results_total is None:
            self.flow_results_total = 0
        self.flow_results_total += len(jobs)
        if not hasattr(self, "flow_results_success"):
            self.flow_results_success = 0

        try:
            for idx, job in enumerate(jobs):
                # Tính row index (append vào cuối table)
                row_idx = current_row_count + idx
                # Tính tile_index unique (dựa trên offset)
                tile_index = tile_index_offset + idx
                
                job["folder_label"] = folder_label
                job["tile_index"] = tile_index  # ✅ Unique tile_index
                
                # Insert row mới (ẩn) để tái sử dụng logic cũ
                if table:
                    table.insertRow(row_idx)
                    folder_item = QTableWidgetItem(folder_label)
                    table.setItem(row_idx, 0, folder_item)
                    path_item = QTableWidgetItem("")
                    path_item.setToolTip("")
                    table.setItem(row_idx, 2, path_item)
                    seed_text = str(job.get("seed")) if job.get("seed") else ""
                    table.setItem(row_idx, 3, QTableWidgetItem(seed_text))
                    status_item = QTableWidgetItem("Đang chờ…")
                    table.setItem(row_idx, 4, status_item)
                    prompt_text = job.get("prompt", "")
                    prompt_item = QTableWidgetItem(prompt_text)
                    prompt_item.setToolTip(self._format_flow_caption(job))
                    table.setItem(row_idx, 5, prompt_item)
                    retry_btn = QPushButton("Gen lại")
                    retry_btn.setEnabled(True)
                    retry_btn.setStyleSheet("""
                        QPushButton {
                            background: #3b82f6;
                            color: white;
                            border: none;
                            border-radius: 6px;
                            padding: 6px 12px;
                            font-weight: 500;
                        }
                            QPushButton:hover:enabled { background: #2563eb; }
                            QPushButton:disabled { background: #cbd5e1; color: #64748b; }
                    """)
                    job_data = job.copy()
                    job_data["row_index"] = row_idx
                    retry_btn.clicked.connect(lambda checked, data=job_data: self._flow_retry_single_image_from_job(data))
                    table.setCellWidget(row_idx, 6, retry_btn)
                    table.setRowHeight(row_idx, 110)
                else:
                    path_item = None
                    status_item = None
                    retry_btn = None

                # ═══════════════════════════════════════════════════════════
                # 🎨 MODERN CARD DESIGN - Clean & Minimal (Responsive)
                # ═══════════════════════════════════════════════════════════
                card = QFrame()
                card.setMinimumSize(250, 320)
                card.setMaximumSize(320, 380)
                card.setStyleSheet("""
                    QFrame {
                        background: #ffffff;
                        border-radius: 12px;
                        border: 1px solid #e5e7eb;
                    }
                """)
                
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(10, 10, 10, 10)
                card_layout.setSpacing(8)

                # ── IMAGE PREVIEW ──
                preview_label = QLabel("🖼️")
                preview_label.setMinimumSize(230, 140)
                preview_label.setMaximumSize(300, 180)
                preview_label.setAlignment(Qt.AlignCenter)
                preview_label.setStyleSheet("""
                    QLabel {
                        background: #f3f4f6;
                        border-radius: 8px;
                        color: #9ca3af;
                        font-size: 32px;
                    }
                """)
                preview_label.setCursor(Qt.PointingHandCursor)
                preview_label.setToolTip("Click để xem ảnh")
                preview_label.mousePressEvent = lambda event, idx=tile_index: self._flow_preview_image_by_index(idx)
                card_layout.addWidget(preview_label)

                # Hidden elements for backward compatibility
                info_path = None

                # ── STATUS ──
                status_container = QWidget()
                status_container_layout = QVBoxLayout(status_container)
                status_container_layout.setContentsMargins(0, 10, 0, 10)  # 10px top, 10px bottom
                status_container_layout.setSpacing(0)
                
                status_lbl = QLabel("⏳ Đang chờ...")
                status_lbl.setFixedHeight(20)
                status_lbl.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: 500;")
                status_container_layout.addWidget(status_lbl)
                card_layout.addWidget(status_container)

                # ── PROMPT TEXT ──
                prompt_text = job.get('prompt', '')
                short_prompt = prompt_text[:60] + "..." if len(prompt_text) > 60 else prompt_text
                prompt_lbl = QLabel(short_prompt)
                prompt_lbl.setWordWrap(True)
                prompt_lbl.setFixedHeight(36)
                prompt_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                prompt_lbl.setToolTip(prompt_text)
                prompt_lbl.setStyleSheet("color: #374151; font-size: 11px;")
                card_layout.addWidget(prompt_lbl)

                # ── REFERENCE IMAGES ROW ──
                ref_row = QHBoxLayout()
                ref_row.setSpacing(4)
                ref_row.setContentsMargins(0, 0, 0, 0)
                
                try:
                    ref_paths = job.get("reference_paths", [])
                    if not ref_paths:
                        ref_paths = list(self.flow_reference_paths)[:3] if hasattr(self, "flow_reference_paths") else []
                    else:
                        ref_paths = ref_paths[:3]
                except Exception:
                    ref_paths = []
                
                if ref_paths:
                    for idx_ref, ref_path in enumerate(ref_paths, 1):
                        ref_label = QLabel()
                        ref_label.setFixedSize(64, 64)
                        ref_label.setAlignment(Qt.AlignCenter)
                        ref_label.setStyleSheet("""
                            QLabel {
                                background: #f9fafb;
                                border: 1px solid #e5e7eb;
                                border-radius: 4px;
                            }
                        """)
                        try:
                            self._flow_apply_pixmap_to_label(ref_label, ref_path)
                        except Exception:
                            ref_label.setText(str(idx_ref))
                            ref_label.setStyleSheet("background: #f3f4f6; border: 1px dashed #d1d5db; border-radius: 4px; color: #9ca3af; font-size: 10px;")
                        ref_row.addWidget(ref_label)
                
                ref_row.addStretch()
                card_layout.addLayout(ref_row)

                # ── SPACER ──
                card_layout.addStretch()

                # ── ACTION BUTTONS ──
                action_row = QHBoxLayout()
                action_row.setSpacing(6)
                action_row.setContentsMargins(0, 0, 0, 0)
                
                btn_open = QPushButton("📂 Mở")
                btn_open.setMinimumWidth(80)
                btn_open.setMaximumWidth(130)
                btn_open.setFixedHeight(28)
                btn_open.setCursor(Qt.PointingHandCursor)
                btn_open.setStyleSheet("""
                    QPushButton {
                        background: #10b981;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                    QPushButton:hover { background: #059669; }
                    QPushButton:disabled { background: #d1d5db; color: #9ca3af; }
                """)
                btn_open.setEnabled(False)
                btn_open.clicked.connect(lambda checked, idx=tile_index: self._flow_open_image_folder_by_index(idx))

                btn_retry = QPushButton("🔄 Gen lại")
                btn_retry.setMinimumWidth(80)
                btn_retry.setMaximumWidth(130)
                btn_retry.setFixedHeight(28)
                btn_retry.setCursor(Qt.PointingHandCursor)
                btn_retry.setStyleSheet("""
                    QPushButton {
                        background: #3b82f6;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                    QPushButton:hover { background: #2563eb; }
                    QPushButton:disabled { background: #d1d5db; color: #9ca3af; }
                """)
                btn_retry.clicked.connect(lambda checked, data=job.copy(): self._flow_retry_single_image_from_job(data))
                
                action_row.addWidget(btn_open)
                action_row.addWidget(btn_retry)
                card_layout.addLayout(action_row)

                # Thêm card vào grid (tự động tính số cột dựa trên kích thước)
                grid = self.flow_results_grid
                if grid:
                    pos = grid.count()
                    # Tính số cột dựa trên kích thước container (mỗi card ~270px + spacing)
                    container_width = self.flow_results_container.width() if self.flow_results_container.width() > 0 else 900
                    card_width = 270  # min card width + spacing
                    columns = max(1, container_width // card_width)
                    columns = min(columns, 4)  # tối đa 4 cột
                    row_grid = pos // columns
                    col_grid = pos % columns
                    grid.addWidget(card, row_grid, col_grid)

                self.flow_result_tiles.append({
                    "row": row_idx,
                    "job": job,
                    "image_widget": preview_label,
                    "status_item": status_item,
                    "path_item": path_item,
                    "status_label": status_lbl,
                    "path_label": info_path,
                    "prompt_label": prompt_lbl,
                    "retry_button": btn_retry,
                    "open_button": btn_open,
                    "image_path": None,
                    "ref_row": ref_row,
                    "card": card,
                })
        finally:
            table.setUpdatesEnabled(True)

        if jobs:
            total_jobs = self.flow_results_total
            self.flow_result_success_label.setText(f"{self.flow_results_success}/{total_jobs} success")
            self.flow_result_hint.setText(f"🚀 Đang xử lý {total_jobs} prompt(s) - Kết quả sẽ hiển thị bên dưới...")
            # Log to confirm table setup
            self.log(f"✅ Result table setup: +{len(jobs)} jobs (total: {total_jobs} jobs), table visible: {self.flow_result_table.isVisible()}")
        else:
            if not hasattr(self, "flow_results_total") or self.flow_results_total == 0:
                self.flow_result_success_label.setText("0 success")
                self.flow_result_hint.setText("Nhập prompt và bấm Run để tạo ảnh Flow.")

    def _flow_update_status_text(self, text: str):
        """Emit signal to update status text (thread-safe)"""
        self.signals.flow_update_status_text.emit(text)

    def _flow_update_hint_text(self, text: str):
        """Emit signal to update hint text (thread-safe)"""
        self.signals.flow_update_hint_text.emit(text)

    def _flow_update_success_label(self, success: int = None):
        """Emit signal to update success label (thread-safe)"""
        if success is not None:
            self.flow_results_success = success
        self.signals.flow_update_success_label.emit(self.flow_results_success)

    def _flow_update_tile_status(self, tile_index: int, text: str):
        """Emit signal to update tile status (thread-safe)"""
        self.signals.flow_update_tile_status.emit(tile_index, text)

    def _flow_update_task_grid_status(self, task_index: int, status: str, error_msg: str = ""):
        """Emit signal to update Task_Grid row status (thread-safe)"""
        self.signals.flow_update_task_grid_status.emit(task_index, status, error_msg)

    def _flow_update_task_grid_preview(self, task_index: int, image_path: str):
        """Emit signal to update Task_Grid preview column (thread-safe)"""
        self.signals.flow_update_task_grid_preview.emit(task_index, image_path)

    def _flow_set_tile_image(self, tile_index: int, image_path: str):
        """Emit signal to set tile image (thread-safe)"""
        self.signals.flow_set_tile_image.emit(tile_index, image_path)

    def _flow_update_status_text_slot(self, text: str):
        """Slot handler for flow_update_status_text signal"""
        if hasattr(self, "flow_status_label"):
            self.flow_status_label.setText(text)

    def _flow_update_hint_text_slot(self, text: str):
        """Slot handler for flow_update_hint_text signal"""
        if hasattr(self, "flow_result_hint"):
            self.flow_result_hint.setText(text)

    def _flow_update_success_label_slot(self, success: int):
        """Slot handler for flow_update_success_label signal"""
        if hasattr(self, "flow_result_success_label"):
            text = f"{success}/{self.flow_results_total or 1} success" if self.flow_results_total else f"{success} success"
            self.flow_result_success_label.setText(text)

    @staticmethod
    def _parse_friendly_error(error_msg: str) -> str:
        """Parse lỗi từ Google API thành thông báo dễ hiểu cho người dùng Việt Nam."""
        if not error_msg:
            return "Lỗi không xác định"
        msg_lower = error_msg.lower()
        
        # Prompt vi phạm nội dung
        if "vi phạm" in msg_lower or "unsafe" in msg_lower or "public_error_unsafe" in msg_lower:
            return "Prompt vi phạm nội dung"
        # Prompt không hợp lệ (400)
        if "invalid_argument" in msg_lower or "invalid argument" in msg_lower:
            if "unsafe" in msg_lower:
                return "Prompt vi phạm nội dung"
            return "Prompt không hợp lệ (sai format/quá dài)"
        if "không hợp lệ" in msg_lower or "bị từ chối" in msg_lower:
            return "Prompt không hợp lệ"
        # Rate limit
        if "429" in error_msg or "rate limit" in msg_lower or "high traffic" in msg_lower or "resource_exhausted" in msg_lower:
            return "Quá tải, thử lại sau"
        # Server errors
        if "500" in error_msg and ("internal" in msg_lower or "server" in msg_lower):
            return "Google đang lỗi (500)"
        if "502" in error_msg or "bad gateway" in msg_lower:
            return "Lỗi kết nối Google (502)"
        if "503" in error_msg or "unavailable" in msg_lower:
            return "Google tạm ngưng (503)"
        if "504" in error_msg or "gateway timeout" in msg_lower:
            return "Hết thời gian chờ (504)"
        # Cookie/Auth
        if ("cookie" in msg_lower and ("die" in msg_lower or "expired" in msg_lower or "hết hạn" in msg_lower)):
            return "Cookie hết hạn"
        if "403" in error_msg or "forbidden" in msg_lower:
            if "recaptcha" in msg_lower or "captcha" in msg_lower:
                return "Lỗi xác thực reCAPTCHA"
            return "Bị chặn truy cập (403)"
        if "401" in error_msg or "unauthorized" in msg_lower:
            return "Phiên đăng nhập hết hạn"
        # Token
        if "access token" in msg_lower or "token" in msg_lower and "expired" in msg_lower:
            return "Token hết hạn, đang làm mới"
        if "recaptcha" in msg_lower or "captcha" in msg_lower:
            return "Lỗi xác thực reCAPTCHA"
        # Network
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return "Hết thời gian chờ kết nối"
        if "connection" in msg_lower and ("refused" in msg_lower or "error" in msg_lower or "reset" in msg_lower):
            return "Lỗi kết nối mạng"
        # Tất cả cookie die
        if "tất cả" in msg_lower and "cookie" in msg_lower and "die" in msg_lower:
            return "Tất cả cookie đã hết hạn"
        # Không nhận được ảnh
        if "không nhận được" in msg_lower or "no image" in msg_lower:
            return "Không nhận được ảnh từ Google"
        # Proxy
        if "proxy" in msg_lower:
            return "Lỗi kết nối proxy"
        # Fallback: cắt ngắn
        clean = error_msg.strip()
        if len(clean) > 50:
            clean = clean[:47] + "…"
        return clean

    def _flow_update_task_grid_status_slot(self, task_index: int, status: str, error_msg: str):
        """Slot handler: update Task_Grid row background + FlowTaskData status (main thread)."""
        STATUS_COLORS = {
            "pending": "#ffffff",
            "running": "#dbeafe",
            "success": "#dcfce7",
            "error": "#fee2e2",
        }
        STATUS_ICONS = {
            "pending": "",
            "running": "⏳",
            "success": "✅",
            "error": "❌",
        }
        # Update FlowTaskData
        if hasattr(self, "flow_tasks") and 0 <= task_index < len(self.flow_tasks):
            self.flow_tasks[task_index].status = status
            if status == "error":
                self.flow_tasks[task_index].error_message = error_msg
        # Update row background color
        if hasattr(self, "flow_task_grid"):
            row = task_index
            if 0 <= row < self.flow_task_grid.rowCount():
                bg = QColor(STATUS_COLORS.get(status, "#ffffff"))
                icon = STATUS_ICONS.get(status, "")
                for col in range(self.flow_task_grid.columnCount()):
                    item = self.flow_task_grid.item(row, col)
                    if item:
                        item.setBackground(bg)
                # Update Task column (col 1) with status icon - giữ nguyên model info
                task_item = self.flow_task_grid.item(row, 1)
                if task_item:
                    base_text = task_item.text()
                    # Remove old icon prefix
                    for ic in STATUS_ICONS.values():
                        if ic and base_text.startswith(ic + " "):
                            base_text = base_text[len(ic) + 1:]
                            break
                    task_item.setText(f"{icon} {base_text}" if icon else base_text)

                # ✅ CỘT STATUS (col 5) - hiển thị trạng thái chi tiết + lỗi dễ hiểu
                status_item = self.flow_task_grid.item(row, 5)
                if not status_item:
                    status_item = QTableWidgetItem("")
                    self.flow_task_grid.setItem(row, 5, status_item)
                    status_item.setBackground(bg)

                if status == "pending":
                    status_item.setText("⏸ Chờ chạy")
                    status_item.setForeground(QColor("#94a3b8"))
                    status_item.setToolTip("")
                elif status == "running":
                    status_item.setText("🔄 Đang tạo ảnh…")
                    status_item.setForeground(QColor("#2563eb"))
                    status_item.setToolTip("Task đang được xử lý")
                elif status == "success":
                    status_item.setText("✅ Thành công")
                    status_item.setForeground(QColor("#16a34a"))
                    status_item.setToolTip("")
                elif status == "error":
                    friendly = self._parse_friendly_error(error_msg or "")
                    status_item.setText(f"❌ {friendly}")
                    status_item.setForeground(QColor("#dc2626"))
                    # Tooltip hiển thị lỗi gốc đầy đủ
                    full_error = error_msg or "Không rõ lỗi"
                    if len(full_error) > 500:
                        full_error = full_error[:500] + "…"
                    status_item.setToolTip(f"Chi tiết lỗi:\n{full_error}")
                else:
                    status_item.setText(status)
                    status_item.setForeground(QColor("#475569"))

                # Lock/unlock thumbnail widget while running
                thumb = self.flow_task_grid.cellWidget(row, 2)
                if isinstance(thumb, ThumbnailGridWidget):
                    thumb.set_locked(status == "running")
        # Update summary bar
        self._flow_update_summary_bar()

    def _flow_update_task_grid_preview_slot(self, task_index: int, image_path: str):
        """Slot handler: update preview column với ảnh đã tạo (main thread)."""
        try:
            if not hasattr(self, "flow_task_grid"):
                return
            if not hasattr(self, "flow_task_preview_widgets"):
                return
                
            row = task_index
            if 0 <= row < self.flow_task_grid.rowCount():
                # Lấy preview widget
                preview_label = self.flow_task_preview_widgets.get(row)
                if preview_label:
                    # Load và hiển thị ảnh với kích thước cố định
                    img_path = Path(image_path)
                    if img_path.exists():
                        pix = QPixmap(str(img_path.resolve()))
                        if not pix.isNull():
                            # Scale với kích thước cố định 80x56
                            scaled = pix.scaled(80, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            preview_label.setPixmap(scaled)
                            preview_label.setText("")
                            preview_label.setToolTip(str(img_path.resolve()))
                            preview_label.setStyleSheet("QLabel { border-radius: 8px; }")
                            self.log(f"✅ Đã hiển thị preview cho task {row + 1}: {img_path.name}")
                        else:
                            preview_label.setText("Lỗi ảnh")
                    else:
                        preview_label.setText("Không tìm thấy")
        except Exception as e:
            self.log(f"⚠️ Lỗi cập nhật preview: {e}")

    def _flow_update_tile_status_slot(self, tile_index: int, text: str):
        """Slot handler for flow_update_tile_status signal"""
        try:
            # ✅ Cập nhật trong flow_result_tiles nếu có
            if hasattr(self, "flow_result_tiles") and self.flow_result_tiles:
                if 0 <= tile_index < len(self.flow_result_tiles):
                    tile = self.flow_result_tiles[tile_index]
                    status_item = tile.get("status_item")
                    # ✅ Kiểm tra status_item có phải là QTableWidgetItem và có method setText không
                    if status_item and hasattr(status_item, "setText"):
                        try:
                            # ✅ Kiểm tra status_item còn tồn tại không
                            _ = status_item.text()
                            status_item.setText(str(text))
                        except RuntimeError:
                            # status_item đã bị xóa, bỏ qua (không log)
                            pass
                    # Update status label trên card (nếu có)
                    status_label = tile.get("status_label")
                    if status_label:
                        try:
                            status_label.setText(f"Status: {text}")
                        except RuntimeError:
                            pass
                        except Exception as e:
                            # Lỗi khác, log nhưng không crash
                            pass
                    
                    # ✅ Cập nhật trong table nếu đang dùng table view
                    if hasattr(self, "flow_result_table") and self.flow_result_table:
                        job = tile.get("job")
                        if job:
                            # Tìm row trong table dựa trên tile_index
                            for row in range(self.flow_result_table.rowCount()):
                                # Kiểm tra xem row này có tile_index tương ứng không
                                # Bằng cách tìm trong flow_result_tiles hoặc flow_folder_results
                                if row < len(self.flow_result_tiles):
                                    if self.flow_result_tiles[row].get("job", {}).get("tile_index") == tile_index:
                                        status_item_table = self.flow_result_table.item(row, 4)  # Cột Status
                                        if status_item_table:
                                            status_item_table.setText(text)
                                        break
                                
                                # Hoặc tìm trong flow_folder_results
                                if hasattr(self, "flow_folder_results") and self.flow_folder_results:
                                    for folder_key, data in self.flow_folder_results.items():
                                        entries = data.get("entries", [])
                                        for entry in entries:
                                            if entry.get("tile_index") == tile_index:
                                                # Tìm row tương ứng trong table
                                                prompt_item = self.flow_result_table.item(row, 5)
                                                if prompt_item and prompt_item.text().strip() == entry.get("prompt", "").strip():
                                                    status_item_table = self.flow_result_table.item(row, 4)
                                                    if status_item_table:
                                                        status_item_table.setText(text)
                                                    # ✅ Cập nhật entry trong flow_folder_results
                                                    entry["status"] = text
                                                    # ✅ Nếu status là "✅ Tạo ảnh thành công", giữ nguyên retry_count (không reset)
                                                    # để có thể gen lại tiếp nếu muốn
                                                    # ✅ Enable lại nút "Gen lại" nếu status là "✅ Tạo ảnh thành công"
                                                    if "✅ Tạo ảnh thành công" in text or "Success" in text or "Hoàn thành" in text:
                                                        retry_btn = self.flow_result_table.cellWidget(row, 6)
                                                        if retry_btn:
                                                            try:
                                                                retry_btn.setEnabled(True)
                                                            except RuntimeError:
                                                                pass
                                                    break
        except Exception as e:
            self.log(f"❌ Lỗi update tile status: {e}")
            import traceback
            self.log(traceback.format_exc())

    def _flow_apply_pixmap_to_label(self, label: QLabel, image_path: str) -> bool:
        """Apply pixmap to label and handle scaling."""
        try:
            # ✅ Kiểm tra label còn tồn tại không
            if not label:
                return False
            
            # ✅ Kiểm tra label có còn valid không bằng cách thử truy cập một property
            try:
                _ = label.objectName()  # Thử truy cập để kiểm tra object còn tồn tại
            except RuntimeError:
                # Object đã bị xóa
                return False
            
            img_path = Path(image_path)
            if not img_path.exists():
                try:
                    label.setText(f"Không tìm thấy: {img_path.name}")
                except RuntimeError:
                    return False
                return False
            
            pix = QPixmap(str(img_path.resolve()))
            if pix.isNull():
                try:
                    label.setText("Không load được ảnh")
                except RuntimeError:
                    return False
                return False
            
            try:
                label_width = label.width()
                label_height = label.height()
            except RuntimeError:
                return False
            
            if label_width <= 0 or label_height <= 0:
                label_width = 300
                label_height = 300
                try:
                    label.setMinimumSize(label_width, label_height)
                    label_width = max(label.width(), 300)
                    label_height = max(label.height(), 300)
                except RuntimeError:
                    return False
            
            scaled = pix.scaled(
                label_width, 
                label_height, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            try:
                label.setPixmap(scaled)
                label.setText("")
                label.setToolTip(str(img_path.resolve()))
            except RuntimeError:
                return False
            return True
        except RuntimeError as e:
            # Object đã bị xóa, không cần log
            return False
        except Exception as e:
            self.log(f"❌ Lỗi hiển thị ảnh: {e}")
            import traceback
            self.log(f"   Traceback: {traceback.format_exc()}")
            try:
                if label:
                    label.setText("Lỗi hiển thị ảnh")
            except RuntimeError:
                pass
            return False

    def _flow_set_tile_image_slot(self, tile_index: int, image_path: str):
        """Slot handler for flow_set_tile_image signal (runs in main thread)"""
        try:
            # ✅ Debug log
            self.log(f"🔍 DEBUG: _flow_set_tile_image_slot called with tile_index={tile_index}, image_path={image_path}")
            
            if not hasattr(self, "flow_result_tiles") or not self.flow_result_tiles:
                self.log(f"⚠️ DEBUG: flow_result_tiles is empty or None")
                return
            
            if not (0 <= tile_index < len(self.flow_result_tiles)):
                self.log(f"⚠️ DEBUG: tile_index {tile_index} out of range (0-{len(self.flow_result_tiles)-1})")
                return
            
            tile = self.flow_result_tiles[tile_index]
            label = tile.get("image_widget")
            if not label:
                self.log(f"⚠️ DEBUG: image_widget not found in tile {tile_index}")
                return
            
            # ✅ Kiểm tra label còn tồn tại không
            try:
                _ = label.objectName()
            except RuntimeError:
                # Label đã bị xóa, bỏ qua
                return
            
            success = self._flow_apply_pixmap_to_label(label, image_path)
            if success:
                resolved = str(Path(image_path).resolve())
                tile["image_path"] = resolved
                if tile.get("job"):
                    try:
                        tile["job"]["image_path"] = resolved
                        tile["job"]["image_path_resolved"] = resolved
                    except Exception:
                        pass
                self.log(f"✅ Đã hiển thị ảnh trên tile {tile_index + 1}: {Path(resolved).name}")
                
                # ✅ Cập nhật entry trong flow_folder_results với image_path và status mới
                if hasattr(self, "flow_folder_results") and self.flow_folder_results:
                    job = tile.get("job")
                    if job:
                        for folder_key, data in self.flow_folder_results.items():
                            entries = data.get("entries", [])
                            for entry in entries:
                                if entry.get("tile_index") == tile_index:
                                    entry["image_path"] = resolved
                                    entry["status"] = "✅ Tạo ảnh thành công"
                                    # ✅ Giữ nguyên retry_count để có thể gen lại tiếp
                                    # Không reset retry_count về 0
                                    break
                
                path_item = tile.get("path_item")
                if path_item:
                    try:
                        # ✅ Kiểm tra path_item còn tồn tại không
                        _ = path_item.text()
                        path_item.setText(resolved)
                        path_item.setToolTip(resolved)
                    except RuntimeError:
                        # path_item đã bị xóa, bỏ qua
                        pass
                
                # Cập nhật path trên card (nếu có)
                path_label = tile.get("path_label")
                if path_label:
                    try:
                        path_label.setText(f"Image Path: {resolved}")
                        path_label.setToolTip(resolved)
                    except RuntimeError:
                        pass
                
                # Enable nút mở folder khi đã có ảnh
                btn_open = tile.get("open_button")
                if btn_open:
                    try:
                        btn_open.setEnabled(True)
                    except RuntimeError:
                        pass
                
                # ✅ Cập nhật path trong table nếu đang dùng table view
                if hasattr(self, "flow_result_table") and self.flow_result_table:
                    # Tìm row trong table dựa trên tile_index
                    for row in range(self.flow_result_table.rowCount()):
                        if row < len(self.flow_result_tiles):
                            if self.flow_result_tiles[row].get("job", {}).get("tile_index") == tile_index:
                                # Cập nhật path
                                path_item_table = self.flow_result_table.item(row, 2)
                                if path_item_table:
                                    try:
                                        path_item_table.setText(resolved)
                                        path_item_table.setToolTip(resolved)
                                    except RuntimeError:
                                        pass
                                # Cập nhật preview
                                preview_label = self.flow_result_table.cellWidget(row, 1)
                                if preview_label:
                                    try:
                                        self._flow_apply_pixmap_to_label(preview_label, resolved)
                                    except RuntimeError:
                                        pass
                                # Enable lại nút "Gen lại" vì đã hoàn thành
                                retry_btn = self.flow_result_table.cellWidget(row, 6)
                                if retry_btn:
                                    try:
                                        retry_btn.setEnabled(True)
                                    except RuntimeError:
                                        pass
                                break
                
                # ✅ Force update để đảm bảo hiển thị
                try:
                    label.update()
                    if hasattr(self, "flow_result_table"):
                        self.flow_result_table.update()
                        QApplication.processEvents()
                except RuntimeError:
                    pass
        except Exception as e:
            # Không log lỗi nếu object đã bị xóa (đây là tình huống bình thường khi table được refresh)
            pass

    def _flow_toggle_folder_controls(self, visible: bool):
        if hasattr(self, "flow_folder_selector"):
            self.flow_folder_selector.setVisible(visible and bool(self.flow_folder_results))
            self.flow_folder_selector.setEnabled(bool(self.flow_folder_results))
        if hasattr(self, "flow_result_table"):
            # Luôn ẩn table (chỉ dùng cho logic nội bộ), hiển thị grid view
            self.flow_result_table.setVisible(False)

    def _flow_switch_to_grid_view(self):
        # flow_result_view_stack là backward compat (orphan widget), không thao tác
        pass

    def _flow_switch_to_table_view(self):
        # flow_result_view_stack là backward compat (orphan widget), không thao tác
        pass

    def _flow_clear_result_grid(self):
        """Xóa toàn bộ card kết quả đang hiển thị trong grid view."""
        if not hasattr(self, "flow_results_grid"):
            return
        layout = self.flow_results_grid
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

    def _flow_preview_image_from_job(self, job: Dict[str, Any]):
        """Hiển thị ảnh phóng to từ job (nếu có image_path)."""
        try:
            image_path = job.get("image_path") or job.get("saved_path") or job.get("path") or job.get("image_path_resolved")
            if not image_path:
                return
            path_obj = Path(image_path)
            if not path_obj.exists():
                QMessageBox.warning(self, "Không tìm thấy ảnh", f"Không tìm thấy file:\n{image_path}")
                return

            dlg = QDialog(self)
            dlg.setWindowTitle(path_obj.name)
            # ✅ Resize popup bằng với main window
            main_width = self.width() if self.width() > 800 else 1200
            main_height = self.height() if self.height() > 600 else 800
            dlg.resize(main_width, main_height)
            vbox = QVBoxLayout(dlg)
            vbox.setContentsMargins(12, 12, 12, 12)
            vbox.setSpacing(8)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea { border: none; }")
            container = QWidget()
            lay = QVBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            lbl = QLabel()
            lbl.setAlignment(Qt.AlignCenter)
            pix = QPixmap(str(path_obj))
            if not pix.isNull():
                screen_w = QApplication.primaryScreen().availableGeometry().width() if QApplication.primaryScreen() else 1200
                # Tăng chiều rộng hiển thị ~25%
                max_w = min(1500, int(screen_w * 1.125))
                pix = pix.scaledToWidth(max_w, Qt.SmoothTransformation)
                lbl.setPixmap(pix)
            else:
                lbl.setText("Không thể tải ảnh")
            lay.addWidget(lbl)
            scroll.setWidget(container)
            vbox.addWidget(scroll)

            btn_close = QPushButton("Đóng")
            btn_close.clicked.connect(dlg.accept)
            btn_close.setFixedWidth(100)
            btn_close.setStyleSheet("""
                QPushButton {
                    background: #e2e8f0;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: 600;
                }
                QPushButton:hover { background: #cbd5e1; }
            """)
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(btn_close)
            vbox.addLayout(btn_row)
            dlg.exec()
        except Exception as e:
            self.log(f"⚠️ Không xem trước được ảnh: {e}")

    def _flow_preview_image_by_index(self, tile_index: int):
        """Preview ảnh theo tile_index (lấy path mới nhất)."""
        try:
            if not hasattr(self, "flow_result_tiles") or not (0 <= tile_index < len(self.flow_result_tiles)):
                return
            tile = self.flow_result_tiles[tile_index]
            job = tile.get("job", {})
            # Ưu tiên path từ tile (đã cập nhật)
            image_path = tile.get("image_path") or job.get("image_path") or job.get("image_path_resolved")
            if not image_path:
                QMessageBox.information(self, "Chưa có ảnh", "Ảnh chưa sẵn sàng, vui lòng đợi tạo xong.")
                return
            self._flow_preview_image_from_job({"image_path": image_path})
        except Exception as e:
            self.log(f"⚠️ Không xem trước được ảnh (index): {e}")

    def _flow_open_image_folder_from_job(self, job: Dict[str, Any]):
        """Mở folder chứa ảnh (select file) nếu đã có image_path."""
        try:
            image_path = job.get("image_path") or job.get("saved_path") or job.get("path") or job.get("image_path_resolved")
            if not image_path:
                QMessageBox.information(self, "Chưa có ảnh", "Ảnh chưa sẵn sàng, vui lòng đợi tạo xong.")
                return
            self._open_file_location(image_path)
        except Exception as e:
            self.log(f"⚠️ Không mở được folder ảnh: {e}")

    def _flow_open_image_folder_by_index(self, tile_index: int):
        """Mở folder ảnh theo tile_index (path mới nhất)."""
        try:
            if not hasattr(self, "flow_result_tiles") or not (0 <= tile_index < len(self.flow_result_tiles)):
                return
            tile = self.flow_result_tiles[tile_index]
            job = tile.get("job", {})
            image_path = tile.get("image_path") or job.get("image_path") or job.get("image_path_resolved")
            if not image_path:
                QMessageBox.information(self, "Chưa có ảnh", "Ảnh chưa sẵn sàng, vui lòng đợi tạo xong.")
                return
            self._open_file_location(image_path)
        except Exception as e:
            self.log(f"⚠️ Không mở được folder ảnh (index): {e}")

    def _get_video_delay_settings_path(self) -> Path:
        return Path.cwd() / "video_delay_settings.json"

    def _load_video_delay_setting(self):
        try:
            if not hasattr(self, "spin_cookie_delay"):
                return
            settings_path = self._get_video_delay_settings_path()
            if not settings_path.exists():
                return
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_value = int(data.get("cookie_delay_seconds", self.spin_cookie_delay.value()))
            min_val = self.spin_cookie_delay.minimum()
            max_val = self.spin_cookie_delay.maximum()
            saved_value = max(min_val, min(max_val, saved_value))
            self.spin_cookie_delay.setValue(saved_value)
            if hasattr(self, "log"):
                self.log(f"⚙️ Khôi phục delay mỗi cookie: {saved_value}s")
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"⚠️ Không load được video delay setting: {e}")

    def _save_video_delay_setting(self):
        try:
            if not hasattr(self, "spin_cookie_delay"):
                return
            settings_path = self._get_video_delay_settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"cookie_delay_seconds": int(self.spin_cookie_delay.value())}
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if hasattr(self, "log"):
                self.log(f"💾 Đã lưu delay mỗi cookie: {data['cookie_delay_seconds']}s")
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"⚠️ Không lưu được video delay setting: {e}")

    def _get_whisk_delay_settings_path(self) -> Path:
        return Path.cwd() / "whisk_delay_settings.json"

    def _load_whisk_delay_setting(self):
        try:
            if not hasattr(self, "spin_image_delay"):
                return
            settings_path = self._get_whisk_delay_settings_path()
            if not settings_path.exists():
                return
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_value = int(data.get("whisk_delay_seconds", self.spin_image_delay.value()))
            min_val = self.spin_image_delay.minimum()
            max_val = self.spin_image_delay.maximum()
            saved_value = max(min_val, min(max_val, saved_value))
            self.spin_image_delay.setValue(saved_value)
            if hasattr(self, "log"):
                self.log(f"⚙️ Khôi phục Whisk delay: {saved_value}s")
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"⚠️ Không load được Whisk delay setting: {e}")

    def _save_whisk_delay_setting(self):
        try:
            if not hasattr(self, "spin_image_delay"):
                return
            settings_path = self._get_whisk_delay_settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"whisk_delay_seconds": int(self.spin_image_delay.value())}
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if hasattr(self, "log"):
                self.log(f"💾 Đã lưu Whisk delay: {data['whisk_delay_seconds']}s")
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"⚠️ Không lưu được Whisk delay setting: {e}")

    def _get_flow_delay_settings_path(self) -> Path:
        return Path.cwd() / "flow_delay_settings.json"

    def _load_flow_delay_setting(self):
        try:
            if not hasattr(self, "flow_delay_spin"):
                return
            settings_path = self._get_flow_delay_settings_path()
            if not settings_path.exists():
                return
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_value = int(data.get("flow_delay_seconds", self.flow_delay_spin.value()))
            min_val = self.flow_delay_spin.minimum()
            max_val = self.flow_delay_spin.maximum()
            saved_value = max(min_val, min(max_val, saved_value))
            self.flow_delay_spin.setValue(saved_value)
            if hasattr(self, "log"):
                self.log(f"⚙️ Khôi phục Flow delay: {saved_value}s")
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"⚠️ Không load được Flow delay setting: {e}")

    def _save_flow_delay_setting(self):
        try:
            if not hasattr(self, "flow_delay_spin"):
                return
            settings_path = self._get_flow_delay_settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"flow_delay_seconds": int(self.flow_delay_spin.value())}
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if hasattr(self, "log"):
                self.log(f"💾 Đã lưu Flow delay: {data['flow_delay_seconds']}s")
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"⚠️ Không lưu được Flow delay setting: {e}")

    def _flow_update_folder_selector(self, select_folder: Optional[str] = None):
        if not hasattr(self, "flow_folder_selector"):
            return
        combo = self.flow_folder_selector
        combo.blockSignals(True)
        combo.clear()
        if not self.flow_folder_results:
            combo.blockSignals(False)
            combo.setVisible(False)
            return
        combo.addItem("Tất cả folder", "__all__")
        for key, data in self.flow_folder_results.items():
            label = data.get("label") or Path(key).name
            combo.addItem(label, key)
        combo.blockSignals(False)
        target = select_folder or self.flow_current_folder_view or "__all__"
        idx = combo.findData(target)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self.flow_current_folder_view = target if target != "__all__" else None
        elif combo.count() > 0:
            combo.setCurrentIndex(0)
            data = combo.itemData(0)
            self.flow_current_folder_view = None if data == "__all__" else data

    def _flow_refresh_result_table(self, folder_key: Optional[str] = None):
        if not hasattr(self, "flow_result_table"):
            return
        table = self.flow_result_table
        
        # If we have active jobs (currently running), don't clear the table
        if hasattr(self, "flow_active_jobs") and self.flow_active_jobs and self.flow_is_running:
            # Keep current active display during generation
            return
        
        # ✅ NẾU CÓ flow_result_tiles từ generation, sử dụng pagination thay vì refresh table
        if hasattr(self, "flow_result_tiles") and self.flow_result_tiles:
            # Chỉ update folder filter và gọi pagination
            if folder_key and folder_key != "__all__":
                # Tìm folder_label từ folder_key
                folder_data = self.flow_folder_results.get(folder_key, {})
                folder_label = folder_data.get("label", "")
                self.flow_current_folder_filter = folder_label
            else:
                self.flow_current_folder_filter = None
            self.log(f"📋 Hiển thị tất cả kết quả")
            self._flow_update_pagination()
            return
            
        table.setRowCount(0)
        if not self.flow_folder_results:
            return
        # ✅ Chỉ reset tiles khi không có tiles từ generation
        # self.flow_result_tiles = []  # KHÔNG reset tiles ở đây
        entries: List[Dict[str, Any]] = []
        if folder_key and folder_key != "__all__":
            data = self.flow_folder_results.get(folder_key)
            if data:
                entries = data.get("entries", [])
        else:
            for data in self.flow_folder_results.values():
                entries.extend(data.get("entries", []))
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                folder_item = QTableWidgetItem(entry.get("folder_label", ""))
                table.setItem(row, 0, folder_item)
                preview_label = QLabel()
                preview_label.setAlignment(Qt.AlignCenter)
                preview_label.setFixedSize(140, 100)
                image_path = entry.get("image_path")
                if image_path:
                    self._flow_apply_pixmap_to_label(preview_label, image_path)
                else:
                    preview_label.setText("No image")
                table.setCellWidget(row, 1, preview_label)
                path_item = QTableWidgetItem(entry.get("image_path", ""))
                image_path_tooltip = entry.get("image_path", "")
                path_item.setToolTip(image_path_tooltip)
                table.setItem(row, 2, path_item)
                seed_value = entry.get("seed")
                table.setItem(row, 3, QTableWidgetItem(str(seed_value) if seed_value else ""))
                status_text = entry.get("status", "")
                table.setItem(row, 4, QTableWidgetItem(status_text))
                prompt_item = QTableWidgetItem(entry.get("prompt", ""))
                prompt_tooltip = entry.get("prompt", "")
                prompt_item.setToolTip(prompt_tooltip)
                table.setItem(row, 5, prompt_item)
                
                # ✅ Thêm nút "Gen lại" vào cột Action
                retry_count = entry.get("retry_count", 0)
                # ✅ Kiểm tra status hoàn thành: "Done", "Success", "Hoàn thành", "✅ Tạo ảnh thành công", hoặc có "✅"
                is_completed = status_text and (
                    "Done" in status_text or 
                    "Success" in status_text or 
                    "Hoàn thành" in status_text or 
                    "✅ Tạo ảnh thành công" in status_text or
                    "✅" in status_text
                )
                is_failed = status_text and ("Fail" in status_text or "Error" in status_text or "Lỗi" in status_text)
                
                # ✅ Enable nút nếu: (đã hoàn thành) hoặc (đã fail và retry_count < 10)
                # Nếu đã hoàn thành, luôn enable nút để có thể gen lại tiếp
                can_retry = is_completed or (is_failed and retry_count < 10)
                
                retry_btn = QPushButton("Gen lại")
                retry_btn.setEnabled(can_retry)
                retry_btn.setStyleSheet("""
                    QPushButton {
                        background: #3b82f6;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        padding: 6px 12px;
                        font-weight: 500;
                    }
                    QPushButton:hover:enabled {
                        background: #2563eb;
                    }
                    QPushButton:disabled {
                        background: #cbd5e1;
                        color: #64748b;
                    }
                """)
                
                # Lưu entry data vào button để dùng khi click
                entry_data = entry.copy()
                entry_data["row_index"] = row
                retry_btn.clicked.connect(lambda checked, data=entry_data: self._flow_retry_single_image(data))
                
                table.setCellWidget(row, 6, retry_btn)
                table.setRowHeight(row, 110)
        finally:
            table.setUpdatesEnabled(True)

    def on_flow_folder_selector_changed(self, index: int):
        if index < 0 or not hasattr(self, "flow_folder_selector"):
            return
        data = self.flow_folder_selector.itemData(index)
        if data == "__all__":
            self.flow_current_folder_view = None
        else:
            self.flow_current_folder_view = data
        self._flow_refresh_result_table(self.flow_current_folder_view or "__all__")

    def _flow_store_completed_folder(self, batch_context: Optional[Dict[str, Any]]):
        if not batch_context or batch_context.get("mode") != "Folder-Structure":
            return
        file_path = batch_context.get("file_path")
        if not file_path:
            return
        folder_key = str(Path(file_path).resolve())
        jobs_copy = [job.copy() for job in getattr(self, "flow_active_jobs", [])]
        data = {
            "label": batch_context.get("label", Path(folder_key).name),
            "jobs": jobs_copy,
            "image_paths": {},
            "statuses": {},
            "success": self.flow_results_success,
            "total": self.flow_results_total,
            "entries": [],
        }
        for tile in getattr(self, "flow_result_tiles", []):
            job = tile.get("job")
            if not job:
                continue
            idx = job.get("tile_index")
            if idx is None:
                continue
            image_path = tile.get("image_path")
            if image_path:
                data["image_paths"][idx] = image_path
            status_item = tile.get("status_item")
            status_text = status_item.text() if status_item else ""
            if status_text:
                data["statuses"][idx] = status_text
            entry = {
                "folder_key": folder_key,
                "folder_label": data["label"],
                "prompt": job.get("prompt", ""),
                "seed": job.get("seed"),
                "status": status_text,
                "image_path": image_path,
                "tile_index": idx,
                "retry_count": job.get("retry_count", 0),  # ✅ Lưu retry_count
                "job_data": job,  # ✅ Lưu job data để retry
            }
            data["entries"].append(entry)
        self.flow_folder_results[folder_key] = data
        self._flow_update_folder_selector(select_folder=folder_key)

    def _flow_retry_single_image_from_job(self, job_data: Dict[str, Any]):
        """Gen lại một ảnh từ job data (khi click từ table row)"""
        try:
            # Tạo entry_data từ job_data
            entry_data = {
                "prompt": job_data.get("prompt", ""),
                "seed": job_data.get("seed"),
                "retry_count": job_data.get("retry_count", 0),
                "tile_index": job_data.get("tile_index"),
                "folder_key": None,  # Sẽ tìm trong flow_folder_results
                "folder_label": job_data.get("folder_label", "Run"),
            }
            
            # Tìm folder_key từ flow_folder_results
            if hasattr(self, "flow_folder_results") and self.flow_folder_results:
                for folder_key, data in self.flow_folder_results.items():
                    entries = data.get("entries", [])
                    for entry in entries:
                        if entry.get("tile_index") == entry_data["tile_index"]:
                            entry_data["folder_key"] = folder_key
                            entry_data.update(entry)
                            break
                    if entry_data["folder_key"]:
                        break
            
            self._flow_retry_single_image(entry_data)
        except Exception as e:
            self.log(f"❌ Lỗi retry single image from job: {e}")
            import traceback
            self.log(traceback.format_exc())

    def _flow_retry_single_image(self, entry_data: Dict[str, Any]):
        """Gen lại một ảnh riêng lẻ từ entry data"""
        try:
            if self.flow_is_running or self.flow_batch_active:
                QMessageBox.information(self, "Flow đang chạy", "Đang có một lượt tạo ảnh Flow khác, vui lòng đợi hoàn tất.")
                return
            
            if not (self.cookie_value or self.cookies_list):
                QMessageBox.warning(self, "Thiếu cookie", "Vui lòng nhập cookie tại tab Video trước khi chạy Flow.")
                return
            
            # Lấy thông tin từ entry
            prompt = entry_data.get("prompt", "")
            seed = entry_data.get("seed")
            retry_count = entry_data.get("retry_count", 0)
            tile_index = entry_data.get("tile_index")
            folder_key = entry_data.get("folder_key")
            
            if not prompt:
                QMessageBox.warning(self, "Thiếu dữ liệu", "Không tìm thấy prompt để gen lại.")
                return
            
            # Kiểm tra retry_count
            if retry_count >= 6:
                QMessageBox.warning(self, "Đã vượt quá số lần retry", "Đã retry 6 lần, không thể gen lại nữa.")
                return
            
            # Tăng retry_count
            retry_count += 1
            
            # Lấy model, aspect, reference paths từ UI hoặc từ entry_data
            model_code = self.flow_model_combo.currentData() if hasattr(self, "flow_model_combo") else "GEM_PIX_2"
            aspect_ratio = self.flow_aspect_combo.currentData() if hasattr(self, "flow_aspect_combo") else "IMAGE_ASPECT_RATIO_LANDSCAPE"
            
            # ✅ Restore reference paths từ entry_data nếu có, không thì dùng từ UI
            reference_paths = entry_data.get("reference_paths", list(self.flow_reference_paths))
            if not reference_paths:
                reference_paths = list(self.flow_reference_paths)
            
            # ✅ Restore output_dir từ entry_data nếu có
            output_dir = entry_data.get("output_dir")
            if not output_dir:
                output_dir = self._get_flow_output_dir()
            else:
                output_dir = Path(output_dir)
            
            # Tạo job mới
            import time
            import random
            timestamp = int(time.time() * 1000)
            if not seed or seed <= 0:
                seed = random.randint(1, 999999)
            
            job = {
                "prompt": prompt,
                "prompt_idx": 0,
                "variation_idx": 0,
                "seed": seed,
                "session_id": f";{timestamp}",
                "retry_count": retry_count,
                "tile_index": tile_index,  # Giữ nguyên tile_index để update đúng vị trí
                "reference_paths": reference_paths,  # ✅ Lưu reference paths vào job
                "file_stem": entry_data.get("file_stem"),  # ✅ Lưu file_stem nếu có
            }
            
            # ✅ Cập nhật entry trong flow_folder_results
            if folder_key and folder_key in self.flow_folder_results:
                data = self.flow_folder_results[folder_key]
                entries = data.get("entries", [])
                for entry in entries:
                    if entry.get("tile_index") == tile_index:
                        entry["retry_count"] = retry_count
                        entry["status"] = "Đang gen lại..."
                        entry["image_path"] = None
                        break
            
            # ✅ Cập nhật trực tiếp trong table (KHÔNG refresh toàn bộ để tránh clear)
            if hasattr(self, "flow_result_table") and self.flow_result_table:
                target_row = None
                # Tìm row dựa trên tile_index trong flow_result_tiles
                if hasattr(self, "flow_result_tiles") and self.flow_result_tiles:
                    for idx, tile in enumerate(self.flow_result_tiles):
                        tile_job = tile.get("job")
                        if tile_job and tile_job.get("tile_index") == tile_index:
                            target_row = tile.get("row", idx)
                            break
                
                # Nếu không tìm thấy trong tiles, tìm trong table bằng prompt và folder_label
                if target_row is None:
                    folder_label = entry_data.get("folder_label", "Run")
                    for row in range(self.flow_result_table.rowCount()):
                        prompt_item = self.flow_result_table.item(row, 5)
                        folder_item = self.flow_result_table.item(row, 0)
                        if (prompt_item and prompt_item.text().strip() == prompt.strip() and
                            folder_item and folder_item.text() == folder_label):
                            target_row = row
                            break
                
                # Cập nhật row nếu tìm thấy
                if target_row is not None and target_row < self.flow_result_table.rowCount():
                    # Cập nhật status
                    status_item = self.flow_result_table.item(target_row, 4)
                    if status_item:
                        try:
                            status_item.setText("Đang gen lại...")
                        except RuntimeError:
                            pass
                    # Clear image preview
                    preview_label = self.flow_result_table.cellWidget(target_row, 1)
                    if preview_label:
                        try:
                            preview_label.setText("Đang chờ…")
                            preview_label.setPixmap(QPixmap())
                        except RuntimeError:
                            pass
                    # Clear image path
                    path_item = self.flow_result_table.item(target_row, 2)
                    if path_item:
                        try:
                            path_item.setText("")
                        except RuntimeError:
                            pass
                    # Disable retry button
                    retry_btn = self.flow_result_table.cellWidget(target_row, 6)
                    if retry_btn:
                        try:
                            retry_btn.setEnabled(False)
                        except RuntimeError:
                            pass
            
            # Thêm job vào active jobs
            if not hasattr(self, "flow_active_jobs"):
                self.flow_active_jobs = []
            self.flow_active_jobs.append(job)
            
            self.flow_is_running = True
            self._flow_enable_run_button(False)
            self._flow_update_status_text(f"Đang gen lại ảnh (lần {retry_count}/10)...")
            
            # Gọi flow worker để gen lại (chỉ gen 1 job)
            import threading
            worker = threading.Thread(
                target=self._flow_generation_worker,
                args=([prompt], 1, [job], model_code, aspect_ratio, reference_paths, output_dir, None),
                daemon=True,
            )
            worker.start()
            
        except Exception as e:
            self.log(f"❌ Lỗi retry single image: {e}")
            import traceback
            self.log(traceback.format_exc())
            QMessageBox.warning(self, "Lỗi", f"Không thể gen lại ảnh: {e}")

    def _flow_show_prompt_context_menu(self, position):
        """Hiển thị context menu khi right-click vào prompt column"""
        try:
            item = self.flow_result_table.itemAt(position)
            if not item:
                return
            
            row = item.row()
            col = item.column()
            
            # Chỉ hiển thị menu khi click vào cột Prompt (cột 5)
            if col != 5:
                return
            
            prompt_item = self.flow_result_table.item(row, 5)
            if not prompt_item:
                return
            
            prompt_text = prompt_item.text()
            if not prompt_text:
                return
            
            # Tạo context menu
            menu = QMenu(self)
            retry_prompt_action = menu.addAction("🔄 Gen lại prompt này")
            retry_prompt_action.triggered.connect(lambda: self._flow_retry_prompt(prompt_text))
            
            # Hiển thị menu
            menu.exec_(self.flow_result_table.viewport().mapToGlobal(position))
        except Exception as e:
            self.log(f"❌ Lỗi show prompt context menu: {e}")

    def _flow_retry_prompt(self, prompt_text: str):
        """Gen lại tất cả ảnh của một prompt"""
        try:
            if self.flow_is_running or self.flow_batch_active:
                QMessageBox.information(self, "Flow đang chạy", "Đang có một lượt tạo ảnh Flow khác, vui lòng đợi hoàn tất.")
                return
            
            if not (self.cookie_value or self.cookies_list):
                QMessageBox.warning(self, "Thiếu cookie", "Vui lòng nhập cookie tại tab Video trước khi chạy Flow.")
                return
            
            if not prompt_text:
                QMessageBox.warning(self, "Thiếu dữ liệu", "Không tìm thấy prompt để gen lại.")
                return
            
            # Tìm tất cả entries có cùng prompt
            entries_to_retry = []
            if hasattr(self, "flow_folder_results") and self.flow_folder_results:
                for folder_key, data in self.flow_folder_results.items():
                    entries = data.get("entries", [])
                    for entry in entries:
                        if entry.get("prompt", "").strip() == prompt_text.strip():
                            retry_count = entry.get("retry_count", 0)
                            if retry_count < 10:  # Chỉ retry nếu chưa vượt quá 10 lần
                                entries_to_retry.append((folder_key, entry))
            
            if not entries_to_retry:
                QMessageBox.information(self, "Không có ảnh để gen lại", "Không tìm thấy ảnh nào của prompt này hoặc đã vượt quá 10 lần retry.")
                return
            
            # Lấy model, aspect, reference paths từ UI
            model_code = self.flow_model_combo.currentData() if hasattr(self, "flow_model_combo") else "GEM_PIX_2"
            aspect_ratio = self.flow_aspect_combo.currentData() if hasattr(self, "flow_aspect_combo") else "IMAGE_ASPECT_RATIO_LANDSCAPE"
            reference_paths = list(self.flow_reference_paths)
            output_dir = self._get_flow_output_dir()
            
            # Tạo jobs cho tất cả entries
            import time
            import random
            timestamp = int(time.time() * 1000)
            jobs = []
            
            for folder_key, entry in entries_to_retry:
                seed = entry.get("seed")
                if not seed or seed <= 0:
                    seed = random.randint(1, 999999)
                
                retry_count = entry.get("retry_count", 0) + 1
                tile_index = entry.get("tile_index")
                
                job = {
                    "prompt": prompt_text,
                    "prompt_idx": 0,
                    "variation_idx": 0,
                    "seed": seed,
                    "session_id": f";{timestamp + len(jobs)}",
                    "retry_count": retry_count,
                    "tile_index": tile_index,
                    "folder_label": entry.get("folder_label", "Run"),
                }
                jobs.append(job)
                
                # ✅ Cập nhật entry trong flow_folder_results
                if folder_key in self.flow_folder_results:
                    data = self.flow_folder_results[folder_key]
                    entries = data.get("entries", [])
                    for e in entries:
                        if e.get("tile_index") == tile_index:
                            e["retry_count"] = retry_count
                            e["status"] = "Đang gen lại..."
                            e["image_path"] = None
                            break
            
            if not jobs:
                return
            
            # ✅ Cập nhật trực tiếp trong table (KHÔNG refresh toàn bộ để tránh clear)
            if hasattr(self, "flow_result_table") and self.flow_result_table:
                for folder_key, entry in entries_to_retry:
                    tile_index = entry.get("tile_index")
                    folder_label = entry.get("folder_label", "Run")
                    target_row = None
                    
                    # Tìm row dựa trên tile_index trong flow_result_tiles
                    if hasattr(self, "flow_result_tiles") and self.flow_result_tiles:
                        for idx, tile in enumerate(self.flow_result_tiles):
                            tile_job = tile.get("job")
                            if tile_job and tile_job.get("tile_index") == tile_index:
                                target_row = tile.get("row", idx)
                                break
                    
                    # Nếu không tìm thấy trong tiles, tìm trong table bằng prompt và folder_label
                    if target_row is None:
                        for row in range(self.flow_result_table.rowCount()):
                            prompt_item = self.flow_result_table.item(row, 5)
                            folder_item = self.flow_result_table.item(row, 0)
                            if (prompt_item and prompt_item.text().strip() == prompt_text.strip() and
                                folder_item and folder_item.text() == folder_label):
                                target_row = row
                                break
                    
                    # Cập nhật row nếu tìm thấy
                    if target_row is not None and target_row < self.flow_result_table.rowCount():
                        # Cập nhật status
                        status_item = self.flow_result_table.item(target_row, 4)
                        if status_item:
                            try:
                                status_item.setText("Đang gen lại...")
                            except RuntimeError:
                                pass
                        # Clear image preview
                        preview_label = self.flow_result_table.cellWidget(target_row, 1)
                        if preview_label:
                            try:
                                preview_label.setText("Đang chờ…")
                                preview_label.setPixmap(QPixmap())
                            except RuntimeError:
                                pass
                        # Clear image path
                        path_item = self.flow_result_table.item(target_row, 2)
                        if path_item:
                            try:
                                path_item.setText("")
                            except RuntimeError:
                                pass
                        # Disable retry button
                        retry_btn = self.flow_result_table.cellWidget(target_row, 6)
                        if retry_btn:
                            try:
                                retry_btn.setEnabled(False)
                            except RuntimeError:
                                pass
            
            # Thêm jobs vào active jobs
            if not hasattr(self, "flow_active_jobs"):
                self.flow_active_jobs = []
            self.flow_active_jobs.extend(jobs)
            
            self.flow_is_running = True
            self._flow_enable_run_button(False)
            self._flow_update_status_text(f"Đang gen lại {len(jobs)} ảnh của prompt...")
            
            # Gọi flow worker để gen lại
            import threading
            worker = threading.Thread(
                target=self._flow_generation_worker,
                args=([prompt_text], len(jobs), jobs, model_code, aspect_ratio, reference_paths, output_dir, None),
                daemon=True,
            )
            worker.start()
            
        except Exception as e:
            self.log(f"❌ Lỗi retry prompt: {e}")
            import traceback
            self.log(traceback.format_exc())
            QMessageBox.warning(self, "Lỗi", f"Không thể gen lại prompt: {e}")

    def _flow_enable_run_button_slot(self, enabled: bool):
        """Slot handler for flow_enable_run_button signal (runs in main thread)"""
        if hasattr(self, "btn_flow_run"):
            self.btn_flow_run.setEnabled(enabled)
        # ✅ Enable/disable cả nút btn_run_selected (toolbar)
        if hasattr(self, "btn_run_selected"):
            self.btn_run_selected.setEnabled(enabled)
        # ✅ Enable/disable nút dừng ngược lại với nút run
        if hasattr(self, "btn_flow_stop"):
            self.btn_flow_stop.setEnabled(not enabled)
        if hasattr(self, "btn_flow_stop_toolbar"):
            self.btn_flow_stop_toolbar.setEnabled(not enabled)
            self.log(f"🔘 Flow run button: {'ENABLED' if enabled else 'DISABLED'} (flow_is_running={self.flow_is_running}, batch_active={self.flow_batch_active})")

    def _flow_enable_run_button(self, enabled: bool):
        """Emit signal to enable/disable run button (thread-safe)"""
        self.signals.flow_enable_run_button.emit(enabled)

    def _show_flow_success_popup_slot(self, success_count: int):
        """Slot handler để hiển thị popup thành công Banana Pro (chạy trên main thread)"""
        try:
            if success_count > 0:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("🎉 Hoàn thành!")
                msg.setText(f"Đã tạo thành công {success_count} ảnh Banana Pro!")
                msg.setInformativeText("Ảnh đã được tải về thư mục đầu ra.")
                msg.exec()
        except Exception:
            pass

    def _show_error_popup_slot(self, title: str, message: str):
        """Slot handler để hiển thị popup lỗi cho người dùng (chạy trên main thread)"""
        try:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle(title)
            msg.setText(message)
            msg.exec()
        except Exception:
            pass

    def on_flow_stop_clicked(self):
        """Xử lý khi nhấn nút dừng tạo ảnh Banana Pro"""
        if not self.flow_is_running and not self.flow_batch_active:
            QMessageBox.information(self, "Thông báo", "Không có quá trình tạo ảnh nào đang chạy.")
            return
        
        reply = QMessageBox.question(
            self, "Xác nhận dừng",
            "Bạn có chắc muốn dừng quá trình tạo ảnh Banana Pro?\n\n"
            "⚠️ Các ảnh đang được tạo sẽ bị hủy bỏ.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # ✅ Set stop_event để dừng worker
            if hasattr(self, 'stop_event'):
                self.stop_event.set()
                self.log("🛑 Đã set stop_event - đang dừng tạo ảnh Banana Pro...")
            
            # ✅ Set flags để dừng flow
            self.flow_is_running = False
            self.flow_batch_active = False
            
            # ✅ Disable nút dừng, enable nút run
            if hasattr(self, "btn_flow_stop"):
                self.btn_flow_stop.setEnabled(False)
            if hasattr(self, "btn_flow_stop_toolbar"):
                self.btn_flow_stop_toolbar.setEnabled(False)
            self._flow_enable_run_button(True)
            
            # ✅ Update status
            self._flow_update_status_text("Đã dừng")
            self._flow_update_hint_text("Quá trình tạo ảnh đã được dừng.")
            # ✅ Unlock grid khi dừng
            self._flow_lock_grid(False)
            self.log("🛑 Đã dừng tạo ảnh Banana Pro")

    def _flow_finish(self, message: str):
        self.flow_is_running = False
        if not self.flow_batch_active:
            self._flow_enable_run_button(True)
            # ✅ Unlock grid khi hoàn tất
            self._flow_lock_grid(False)
        self._flow_update_hint_text(message)

    def _flow_handle_error(self, message: str):
        self.log(f"❌ Flow error: {message}")
        self._flow_finish("Có lỗi xảy ra khi tạo ảnh Flow.")
        if hasattr(self, "flow_status_label"):
            QTimer.singleShot(0, lambda: self.flow_status_label.setText("Lỗi"))

    def _upload_flow_references(self, client: LabsFlowClient, references: List[str]) -> List[Dict[str, Any]]:
        """Upload reference images và cache THEO COOKIE"""
        inputs: List[Dict[str, Any]] = []
        
        # ✅ Lấy cookie hash từ client để cache theo cookie
        cookie_hash = getattr(client, '_cookie_hash', None)
        if not cookie_hash:
            cookie_hash = LabsFlowClient._get_cookie_hash(client.cookies if hasattr(client, 'cookies') else {})
        
        # ✅ Khởi tạo cache cho cookie này nếu chưa có
        if cookie_hash not in self.reference_image_media_ids:
            self.reference_image_media_ids[cookie_hash] = {}
        cookie_cache = self.reference_image_media_ids[cookie_hash]
        
        for path in references:
            self._flow_update_hint_text(f"Đang upload ảnh tham chiếu (cookie {cookie_hash[:8]}...): {Path(path).name}")
            
            # ✅ Check cache THEO COOKIE trước
            path_abs = str(Path(path).resolve())
            if path_abs in cookie_cache:
                media_id = cookie_cache[path_abs]
                self.log(f"♻️ Flow reference từ cache (cookie {cookie_hash[:8]}...): {Path(path).name} → {media_id[:50]}...")
            else:
                # Upload với cookie này - dùng Flow-specific endpoint để lấy plain media ID
                media_id = client.upload_flow_image(path)
                if media_id:
                    # ✅ Cache THEO COOKIE
                    cookie_cache[path_abs] = media_id
                    self.log(f"✅ Flow reference uploaded (cookie {cookie_hash[:8]}...): {Path(path).name} → {media_id[:50]}...")
                else:
                    self.log(f"❌ Upload reference thất bại (cookie {cookie_hash[:8]}...): {Path(path).name} (media_id = None)")
                    continue
            
            # Validate media_id format (should be a string and not empty)
            if isinstance(media_id, str) and media_id.strip():
                inputs.append({
                    "name": media_id.strip(),
                    "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                })
            else:
                self.log(f"❌ Media ID không hợp lệ cho {Path(path).name}: {media_id}")
        
        if inputs:
            self.log(f"📋 Tổng cộng {len(inputs)} reference image(s) đã upload/cache thành công (cookie {cookie_hash[:8]}...)")
        return inputs

    def _flow_upload_references_for_cookie(self, cookie_str: str, reference_paths: List[str], model_code: str) -> List[str]:
        """Upload reference images cho một cookie cụ thể và trả về list media IDs (dùng cache)"""
        try:
            cookies = _parse_cookie_string(cookie_str)
            client = LabsFlowClient(cookies)
            if not client.fetch_access_token():
                self.log(f"⚠️ Không fetch được token cho cookie để upload references")
                return []
            
            # Upload references với cache
            inputs = self._upload_flow_references(client, reference_paths)
            
            # Trả về list media IDs (chỉ lấy name field)
            media_ids = [inp["name"] for inp in inputs if inp.get("name")]
            return media_ids
        except Exception as e:
            self.log(f"❌ Lỗi upload references cho cookie: {e}")
            return []

    def _save_flow_image(self, client: LabsFlowClient, image_info: Dict[str, Any], output_dir: Path, job: Dict[str, Any]) -> Optional[Path]:
        try:
            # ✅ Hỗ trợ đường dẫn dài trên Windows (dùng long path prefix)
            import platform
            import os
            
            # Chuyển sang absolute path
            output_dir = Path(output_dir).resolve()
            
            if platform.system() == "Windows":
                # Kiểm tra nếu đường dẫn dài hơn 260 chars (Windows MAX_PATH limit)
                output_dir_str = str(output_dir)
                if len(output_dir_str) > 260 and not output_dir_str.startswith("\\\\?\\"):
                    # Thêm long path prefix \\?\ để hỗ trợ đường dẫn dài (chỉ dùng cho Windows)
                    # Lưu ý: \\?\ chỉ hoạt động với absolute path
                    output_dir = Path("\\\\?\\" + output_dir_str)
            
            # Tạo thư mục (hỗ trợ đường dẫn dài)
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except (OSError, FileNotFoundError) as e:
                # Nếu lỗi do đường dẫn dài, thử lại với long path prefix (Windows)
                if platform.system() == "Windows" and not str(output_dir).startswith("\\\\?\\"):
                    output_dir_str = str(Path(output_dir).resolve())
                    output_dir = Path("\\\\?\\" + output_dir_str)
                    output_dir.mkdir(parents=True, exist_ok=True)
                else:
                    raise
            
            slug = re.sub(r"[^a-z0-9]+", "_", job["prompt"].lower())[:40] or "prompt"
            base_name = f"flow_p{job['prompt_idx'] + 1}_v{job['variation_idx'] + 1}_{job['seed']}_{slug}"
            target_path = output_dir / f"{base_name}.png"
            
            # ✅ Hỗ trợ đường dẫn dài cho target_path trên Windows
            if platform.system() == "Windows":
                target_path_str = str(target_path)
                # Nếu output_dir đã có long path prefix, target_path cũng sẽ tự động có
                # Nhưng nếu target_path vẫn dài, đảm bảo có prefix
                if len(target_path_str) > 260 and not target_path_str.startswith("\\\\?\\"):
                    target_path = Path("\\\\?\\" + target_path_str)

            def _maybe_upsample(temp_path: Path, final_path: Path) -> Optional[Path]:
                """Nếu user chọn 2K/4K, dùng mediaId từ response hoặc upload, lưu file mới (thay thế ảnh gốc)."""
                try:
                    choice = None
                    if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo:
                        choice = self.flow_upsample_combo.currentData()
                    if not choice or choice == "none":
                        return None  # Không upscale, giữ ảnh gốc

                    # ✅ Ưu tiên dùng mediaId từ image_info (đã extract từ response)
                    media_id = image_info.get("mediaId") if isinstance(image_info, dict) else None
                    
                    # Nếu không có trong image_info, mới upload lại
                    if not media_id:
                        self.log(f"📤 Upsample: Không có mediaId từ response, đang upload ảnh: {temp_path.name}")
                        media_id = client.upload_flow_image(str(temp_path))
                        if not media_id:
                            self.log("⚠️ Upsample: không lấy được mediaId, dùng ảnh gốc")
                            return None
                        self.log(f"✅ Upsample: Đã lấy mediaId từ upload: {media_id[:80]}...")
                    else:
                        self.log(f"✅ Upsample: Dùng mediaId từ response: {media_id[:80]}...")

                    self.log(f"🚀 Upsample: Gọi API upsample với resolution={choice}")
                    upsample_resp = client.upsample_image(
                        media_id,
                        target_resolution=choice,
                        project_id=getattr(client, "flow_project_id", None),
                    )
                    if not upsample_resp:
                        self.log("⚠️ Upsample: API trả về rỗng, dùng ảnh gốc")
                        return None

                    encoded = None
                    if isinstance(upsample_resp, dict):
                        encoded = upsample_resp.get("encodedImage") or upsample_resp.get("image", {}).get("encodedImage")
                    if not encoded:
                        self.log("⚠️ Upsample: không tìm thấy encodedImage trong response, dùng ảnh gốc")
                        return None

                    data_str = str(encoded)
                    missing_padding = len(data_str) % 4
                    if missing_padding:
                        data_str += "=" * (4 - missing_padding)
                    decoded = base64.b64decode(data_str)
                    if not decoded:
                        self.log("⚠️ Upsample: decoded rỗng, dùng ảnh gốc")
                        return None

                    # ✅ Lưu ảnh upscale vào final_path (thay thế ảnh gốc)
                    with open(final_path, "wb") as f:
                        f.write(decoded)
                    self.log(f"🖼️ Flow image upsampled ({'2K' if '2K' in choice else '4K'}): {final_path.name}")
                    
                    return final_path
                except Exception as e:
                    self.log(f"⚠️ Upsample lỗi: {e}")
                    return None  # Lỗi thì giữ ảnh gốc

            info_type = image_info.get("type")
            if info_type == "inline":
                mime = (image_info.get("mime_type") or "image/png").lower()
                if "jpeg" in mime or "jpg" in mime:
                    target_path = target_path.with_suffix(".jpg")
                elif "webp" in mime:
                    target_path = target_path.with_suffix(".webp")
                data = image_info.get("data")
                if not data:
                    return None
                try:
                    # Try to decode base64 data (handle padding issues)
                    data_str = data if isinstance(data, str) else str(data)
                    # Add padding if needed
                    missing_padding = len(data_str) % 4
                    if missing_padding:
                        data_str += '=' * (4 - missing_padding)
                    decoded = base64.b64decode(data_str)
                    if len(decoded) == 0:
                        self.log(f"⚠️ Decoded data is empty for {target_path.name}")
                        return None
                    
                    # ✅ Kiểm tra xem có chọn upscale không
                    choice = None
                    if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo:
                        choice = self.flow_upsample_combo.currentData()
                    
                    # Nếu có chọn upscale, không lưu ảnh gốc, chỉ lưu ảnh upscale
                    if choice and choice != "none":
                        # Lưu tạm vào temp file để upsample (cần file để upload nếu không có mediaId)
                        temp_path = target_path.with_suffix(".tmp")
                        with open(temp_path, "wb") as f:
                            f.write(decoded)
                        # Upsample và lưu vào target_path
                        upsampled = _maybe_upsample(temp_path, target_path)
                        if upsampled and upsampled.exists():
                            # Xóa temp file
                            if temp_path.exists():
                                temp_path.unlink()
                            return upsampled
                        else:
                            # Upsample lỗi, lưu ảnh gốc
                            if temp_path.exists():
                                temp_path.rename(target_path)
                            self.log(f"🖼️ Flow image saved (inline): {target_path.name} ({len(decoded)} bytes)")
                            return target_path
                    else:
                        # Không upscale, lưu ảnh gốc
                        with open(target_path, "wb") as f:
                            f.write(decoded)
                        self.log(f"🖼️ Flow image saved (inline): {target_path.name} ({len(decoded)} bytes)")
                        return target_path
                except Exception as decode_err:
                    self.log(f"❌ Không decode được base64: {str(decode_err)[:100]}")
                    # Log first 100 chars of data for debugging
                    data_preview = data_str[:100] if isinstance(data_str, str) else str(data_str)[:100]
                    self.log(f"   Data preview: {data_preview}...")
                    return None
            if info_type == "data_url":
                data_url = image_info.get("data")
                if not data_url or "," not in data_url:
                    return None
                header, payload = data_url.split(",", 1)
                suffix = ".png"
                header_lower = header.lower()
                if "jpeg" in header_lower or "jpg" in header_lower:
                    suffix = ".jpg"
                elif "webp" in header_lower:
                    suffix = ".webp"
                target_path = target_path.with_suffix(suffix)
                
                # ✅ Kiểm tra xem có chọn upscale không
                choice = None
                if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo:
                    choice = self.flow_upsample_combo.currentData()
                
                # Nếu có chọn upscale, không lưu ảnh gốc, chỉ lưu ảnh upscale
                if choice and choice != "none":
                    # Lưu tạm vào temp file để upsample (cần file để upload nếu không có mediaId)
                    temp_path = target_path.with_suffix(".tmp")
                    with open(temp_path, "wb") as f:
                        f.write(base64.b64decode(payload))
                    # Upsample và lưu vào target_path
                    upsampled = _maybe_upsample(temp_path, target_path)
                    if upsampled and upsampled.exists():
                        # Xóa temp file
                        if temp_path.exists():
                            temp_path.unlink()
                        return upsampled
                    else:
                        # Upsample lỗi, lưu ảnh gốc
                        if temp_path.exists():
                            temp_path.rename(target_path)
                        self.log(f"🖼️ Flow image saved: {target_path.name}")
                        return target_path
                else:
                    # Không upscale, lưu ảnh gốc
                    with open(target_path, "wb") as f:
                        f.write(base64.b64decode(payload))
                    self.log(f"🖼️ Flow image saved: {target_path.name}")
                    return target_path
            if info_type == "url":
                url = image_info.get("url")
                if not url:
                    return None
                suffix = Path(url.split("?")[0]).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                    target_path = target_path.with_suffix(suffix)
                # ✅ Kiểm tra xem có chọn upscale không
                choice = None
                if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo:
                    choice = self.flow_upsample_combo.currentData()
                
                # Nếu có chọn upscale, download vào temp file trước
                if choice and choice != "none":
                    temp_path = target_path.with_suffix(".tmp")
                    if self._download_flow_image(client, url, temp_path):
                        # Upsample và lưu vào target_path
                        upsampled = _maybe_upsample(temp_path, target_path)
                        if upsampled and upsampled.exists():
                            # Xóa temp file
                            if temp_path.exists():
                                temp_path.unlink()
                            return upsampled
                        else:
                            # Upsample lỗi, lưu ảnh gốc
                            if temp_path.exists():
                                temp_path.rename(target_path)
                            self.log(f"🖼️ Flow image downloaded: {target_path.name}")
                            return target_path
                    return None
                else:
                    # Không upscale, download ảnh gốc
                    if self._download_flow_image(client, url, target_path):
                        self.log(f"🖼️ Flow image downloaded: {target_path.name}")
                        return target_path
                    return None
            return None
        except Exception as e:
            self.log(f"❌ Lỗi lưu ảnh Flow: {e}")
            return None

    def _download_flow_image(self, client: LabsFlowClient, url: str, target_path: Path) -> bool:
        try:
            # ✅ Hỗ trợ đường dẫn dài trên Windows
            import platform
            if platform.system() == "Windows":
                target_path = Path(target_path).resolve()
                target_path_str = str(target_path)
                if len(target_path_str) > 260 and not target_path_str.startswith("\\\\?\\"):
                    target_path = Path("\\\\?\\" + target_path_str)
            
            # ✅ flow-content.google là signed URL - chỉ cần User-Agent, không cần Bearer/Origin
            # Dùng aisandbox headers cho googleapis.com, dùng headers đơn giản cho flow-content.google
            if "flow-content.google" in url or "flow-content.googleapis.com" in url:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                    "Referer": "https://labs.google/",
                }
            else:
                headers = client._aisandbox_headers()
                headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}

            with client.session.get(url, headers=headers, timeout=120, stream=True) as resp:
                resp.raise_for_status()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return target_path.exists() and target_path.stat().st_size > 0
        except Exception as e:
            self.log(f"⚠️ Không tải được ảnh từ signedUri: {str(e)[:120]}")
            return False

    def _create_renew_cookie_callback(self, cookie_str: str, cookies_result: Optional[Dict[str, Any]] = None):
        """Tạo callback để renew cookie khi bị chặn - dùng chung cho cả Flow và Extend"""
        # Lưu reference đến cookies_list để có thể lấy cookie tiếp theo
        cookies_list = self.cookies_list if hasattr(self, 'cookies_list') else []
        
        def renew_cookie_callback(cookie_hash: str, old_cookies: Dict[str, str]) -> Optional[Dict[str, str]]:
            try:
                # Tìm cookie mới từ cookies_result (so sánh với cookie_str gốc) - cho Flow mode
                if cookies_result:
                    for email, cookies_list_item in cookies_result.items():
                        if isinstance(cookies_list_item, str):
                            test_cookies = _parse_cookie_string(cookies_list_item)
                            test_hash = LabsFlowClient._get_cookie_hash(test_cookies)
                            if test_hash == cookie_hash:
                                # Tìm cookie mới cho email này
                                new_cookies_list = cookies_result.get(email)
                                if new_cookies_list:
                                    if isinstance(new_cookies_list, str):
                                        new_cookies = _parse_cookie_string(new_cookies_list)
                                    elif isinstance(new_cookies_list, list):
                                        new_cookies = {}
                                        for c in new_cookies_list:
                                            if isinstance(c, dict):
                                                new_cookies[c.get('name', '')] = c.get('value', '')

                                    # Kiểm tra xem cookie mới có khác cookie cũ không
                                    if new_cookies and new_cookies != old_cookies:
                                        self.log(f"  ✅ [Renew Cookie] Đã lấy cookie mới cho {email} (hash: {cookie_hash[:8]}...)")
                                        return new_cookies

                # ✅ Extend mode: Thử lấy cookie tiếp theo từ cookies_list
                if cookies_list and len(cookies_list) > 1:
                    self.log(f"  🔄 [Renew Cookie] Đang thử lấy cookie mới từ cookies_list...")
                    
                    # Tìm index của cookie hiện tại
                    current_idx = -1
                    for idx, c in enumerate(cookies_list):
                        test_cookies = _parse_cookie_string(c)
                        test_hash = LabsFlowClient._get_cookie_hash(test_cookies)
                        if test_hash == cookie_hash:
                            current_idx = idx
                            break
                    
                    # Lấy cookie tiếp theo
                    if current_idx >= 0:
                        next_idx = (current_idx + 1) % len(cookies_list)
                        next_cookie_str = cookies_list[next_idx]
                        next_cookies = _parse_cookie_string(next_cookie_str)
                        
                        if next_cookies and next_cookies != old_cookies:
                            self.log(f"  ✅ [Renew Cookie] Đã lấy cookie mới (index: {next_idx}, hash: {LabsFlowClient._get_cookie_hash(next_cookies)[:8]}...)")
                            return next_cookies
                
                self.log(f"  ⚠️ [Renew Cookie] Không tìm thấy cookie mới cho hash: {cookie_hash[:8]}...")
                return None
            except Exception as e:
                self.log(f"  ✗ [Renew Cookie] Lỗi renew cookie: {e}")
                import traceback
                self.log(traceback.format_exc())
                return None
        return renew_cookie_callback

    def _flow_generation_worker(
        self,
        prompts: List[str],
        variants: int,
        jobs: List[Dict[str, Any]],
        model_code: str,
        aspect_ratio: str,
        reference_paths: List[str],
        output_dir: Path,
        batch_context: Optional[Dict[str, Any]] = None,
    ):
        batch_success = False
        try:
            # ✅ ĐA COOKIE: Khởi tạo available cookies giống Whisk
            available_cookies = []
            if self.cookies_list:
                available_cookies = self.cookies_list
            elif self.cookie_value:
                available_cookies = [self.cookie_value]
            
            if not available_cookies:
                self._flow_handle_error("Vui lòng nhập cookie trước khi chạy Flow.")
                return
            
            num_cookies = len(available_cookies)
            self.log(f"🔑 Flow sử dụng {num_cookies} cookie(s) với round-robin distribution")

            # ✅ Dùng cookie đầu tiên cho upload reference images và setup
            main_client = self._build_client_from_cookie_str(available_cookies[0], cookie_index=0)

            # Đăng ký callback cho cookie đầu tiên
            main_cookie_hash = main_client._cookie_hash
            LabsFlowClient.register_renew_cookie_callback(main_cookie_hash, self._create_renew_cookie_callback(available_cookies[0], None))
            if not main_client:
                self._flow_handle_error("Vui lòng nhập cookie trước khi chạy Flow.")
                return
            if not main_client.fetch_access_token():
                self._flow_handle_error("Không thể lấy access token từ Labs.")
                return

            # Thread-safe cookie counter cho round-robin
            import threading
            from collections import Counter
            cookie_lock = threading.Lock()
            cookie_counter = Counter()

            # ✅ Dùng main_client cho upload reference images (nếu cần)
            client = main_client
            
            # ✅ Multiple-to-Image: Load và map images từ folders
            if self.current_flow_mode == "Multiple-to-Image":
                self.log("📤 Flow Multiple-to-Image mode detected - Loading images from folders...")
                self.flow_m2i_image_mapping = {}  # Clear previous mapping
                
                # Load images từ 3 folders
                subject_folder = self.flow_subject_folder.text().strip()
                scene_folder = self.flow_scene_folder.text().strip()
                style_folder = self.flow_style_folder.text().strip()
                
                # Load và sort images từ mỗi folder
                subject_images = []
                scene_images = []
                style_images = []
                
                image_exts = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']
                
                if subject_folder and Path(subject_folder).exists():
                    for ext in image_exts:
                        subject_images.extend(Path(subject_folder).glob(ext))
                    subject_images = natural_sort_paths(subject_images)
                    self.log(f"📁 Flow Subject folder: {len(subject_images)} ảnh")
                
                if scene_folder and Path(scene_folder).exists():
                    for ext in image_exts:
                        scene_images.extend(Path(scene_folder).glob(ext))
                    scene_images = natural_sort_paths(scene_images)
                    self.log(f"📁 Flow Scene folder: {len(scene_images)} ảnh")
                
                if style_folder and Path(style_folder).exists():
                    for ext in image_exts:
                        style_images.extend(Path(style_folder).glob(ext))
                    style_images = natural_sort_paths(style_images)
                    self.log(f"📁 Flow Style folder: {len(style_images)} ảnh")
                
                # Map images theo prompt index (0-based)
                max_images = max(len(subject_images), len(scene_images), len(style_images))
                if max_images == 0:
                    self.log("⚠️ ⚠️ ⚠️ WARNING: Không có ảnh nào trong các folder!")
                    self.log("💡 Hãy chọn ít nhất 1 folder chứa ảnh Subject/Scene/Style")
                    # Fallback to Normal mode
                    reference_inputs = []
                else:
                    # Map images cho từng prompt (index bắt đầu từ 0)
                    for prompt_idx in range(len(prompts)):
                        image_idx = prompt_idx  # 0-based index
                        mapping = {}
                        
                        if image_idx < len(subject_images):
                            mapping['subject_path'] = str(subject_images[image_idx].resolve())
                        if image_idx < len(scene_images):
                            mapping['scene_path'] = str(scene_images[image_idx].resolve())
                        if image_idx < len(style_images):
                            mapping['style_path'] = str(style_images[image_idx].resolve())
                        
                        # Chỉ thêm mapping nếu có ít nhất 1 ảnh
                        if mapping:
                            self.flow_m2i_image_mapping[prompt_idx] = mapping
                            self.log(f"📋 Flow mapped prompt {prompt_idx}: Subject={bool(mapping.get('subject_path'))}, Scene={bool(mapping.get('scene_path'))}, Style={bool(mapping.get('style_path'))}")
                    
                    self.log(f"✅ Flow đã map {len(self.flow_m2i_image_mapping)} prompts với images")
                    
                    # Upload tất cả images và cache media IDs THEO COOKIE
                    self.log("📤 Đang upload tất cả Flow images từ folders...")
                    # ✅ Lấy cookie hash từ client để cache theo cookie
                    cookie_hash = getattr(client, '_cookie_hash', None)
                    if not cookie_hash:
                        # ✅ LabsFlowClient đã được import ở đầu file, không cần import lại
                        cookie_hash = LabsFlowClient._get_cookie_hash(client.cookies if hasattr(client, 'cookies') else {})
                    
                    # ✅ Khởi tạo cache cho cookie này nếu chưa có
                    if cookie_hash not in self.reference_image_media_ids:
                        self.reference_image_media_ids[cookie_hash] = {}
                    cookie_cache = self.reference_image_media_ids[cookie_hash]
                    
                    for prompt_idx, mapping in self.flow_m2i_image_mapping.items():
                        # Upload Subject
                        if 'subject_path' in mapping:
                            subject_path = mapping['subject_path']
                            subject_path_abs = str(Path(subject_path).resolve())
                            # ✅ Kiểm tra cache THEO COOKIE
                            if subject_path_abs in cookie_cache:
                                mapping['subject_mgid'] = cookie_cache[subject_path_abs]
                                self.log(f"♻️ Flow Subject {prompt_idx} từ cache (cookie {cookie_hash[:8]}...): {Path(subject_path).name}")
                            else:
                                self.log(f"📤 Uploading Flow Subject {prompt_idx} (cookie {cookie_hash[:8]}...): {Path(subject_path).name}...")
                                mgid = client.upload_flow_image(subject_path)
                                if mgid:
                                    cookie_cache[subject_path_abs] = mgid  # ✅ Lưu vào cache của cookie này
                                    mapping['subject_mgid'] = mgid
                                    self.log(f"✅ Flow Subject {prompt_idx} uploaded")
                                else:
                                    self.log(f"❌ Failed to upload Flow Subject {prompt_idx}")
                        
                        # Upload Scene
                        if 'scene_path' in mapping:
                            scene_path = mapping['scene_path']
                            scene_path_abs = str(Path(scene_path).resolve())
                            # ✅ Kiểm tra cache THEO COOKIE
                            if scene_path_abs in cookie_cache:
                                mapping['scene_mgid'] = cookie_cache[scene_path_abs]
                                self.log(f"♻️ Flow Scene {prompt_idx} từ cache (cookie {cookie_hash[:8]}...): {Path(scene_path).name}")
                            else:
                                self.log(f"📤 Uploading Flow Scene {prompt_idx} (cookie {cookie_hash[:8]}...): {Path(scene_path).name}...")
                                mgid = client.upload_flow_image(scene_path)
                                if mgid:
                                    cookie_cache[scene_path_abs] = mgid  # ✅ Lưu vào cache của cookie này
                                    mapping['scene_mgid'] = mgid
                                    self.log(f"✅ Flow Scene {prompt_idx} uploaded")
                                else:
                                    self.log(f"❌ Failed to upload Flow Scene {prompt_idx}")
                        
                        # Upload Style
                        if 'style_path' in mapping:
                            style_path = mapping['style_path']
                            style_path_abs = str(Path(style_path).resolve())
                            # ✅ Kiểm tra cache THEO COOKIE
                            if style_path_abs in cookie_cache:
                                mapping['style_mgid'] = cookie_cache[style_path_abs]
                                self.log(f"♻️ Flow Style {prompt_idx} từ cache (cookie {cookie_hash[:8]}...): {Path(style_path).name}")
                            else:
                                self.log(f"📤 Uploading Flow Style {prompt_idx} (cookie {cookie_hash[:8]}...): {Path(style_path).name}...")
                                mgid = client.upload_flow_image(style_path)
                                if mgid:
                                    cookie_cache[style_path_abs] = mgid  # ✅ Lưu vào cache của cookie này
                                    mapping['style_mgid'] = mgid
                                    self.log(f"✅ Flow Style {prompt_idx} uploaded")
                                else:
                                    self.log(f"❌ Failed to upload Flow Style {prompt_idx}")
                    
                    self.log(f"✅ Flow đã upload và cache images cho {len(self.flow_m2i_image_mapping)} prompts")
                    # Reference inputs sẽ được tạo theo từng prompt trong loop
                    reference_inputs = []  # Will be created per prompt
            elif self.current_flow_mode == "Folder-Structure":
                # Folder Structure mode: upload references từ reference_paths (đã được set từ folder con)
                self.log(f"📤 Flow Folder Structure mode - Uploading {len(reference_paths)} reference images với TẤT CẢ cookies...")
                # ✅ Upload với từng cookie để cache riêng
                for cookie_idx in range(num_cookies):
                    cookie_client = self._build_client_from_cookie_str(available_cookies[cookie_idx], cookie_index=cookie_idx)
                    if cookie_client and cookie_client.fetch_access_token():
                        self._upload_flow_references(cookie_client, reference_paths)
                        self.log(f"✅ Cookie #{cookie_idx + 1}: Đã upload/cache {len(reference_paths)} ảnh tham chiếu")
                # Dùng reference_inputs từ cookie đầu tiên cho logic gen (sẽ dùng cache khi gen)
                reference_inputs = self._upload_flow_references(client, reference_paths)
                self.log(f"✅ Flow Folder Structure: Đã upload/cache {len(reference_paths)} ảnh với tất cả {num_cookies} cookie(s) - Sẽ map prompt với ảnh khi tạo job")
            else:
                # Normal mode: upload references với TẤT CẢ cookies
                # ✅ Thu thập tất cả ảnh unique từ per-row (flow_tasks) + global reference_paths
                all_ref_paths = set()
                if reference_paths:
                    all_ref_paths.update(reference_paths)
                if hasattr(self, 'flow_tasks'):
                    for t in self.flow_tasks:
                        if t.reference_images:
                            all_ref_paths.update(t.reference_images)
                all_ref_paths_list = list(all_ref_paths)
                self.log(f"📤 Flow Normal mode - Uploading {len(all_ref_paths_list)} unique reference images với TẤT CẢ cookies...")
                # ✅ Upload với từng cookie để cache riêng
                for cookie_idx in range(num_cookies):
                    cookie_client = self._build_client_from_cookie_str(available_cookies[cookie_idx], cookie_index=cookie_idx)
                    if cookie_client and cookie_client.fetch_access_token():
                        self._upload_flow_references(cookie_client, all_ref_paths_list)
                        self.log(f"✅ Cookie #{cookie_idx + 1}: Đã upload/cache {len(all_ref_paths_list)} ảnh tham chiếu")
                # Dùng reference_inputs từ cookie đầu tiên cho logic gen (sẽ dùng cache khi gen)
                reference_inputs = self._upload_flow_references(client, all_ref_paths_list)
                self.log(f"✅ Flow Normal: Đã upload/cache với tất cả {num_cookies} cookie(s)")
            
            total_jobs = len(jobs)
            completed = 0
            success = 0
            
            # ✅ Banana Pro: Gốc = 3/cookie, 2K-4K = 1/cookie
            per_cookie_concurrent = self._get_flow_concurrency_per_cookie()
            max_concurrent = max(1, num_cookies * per_cookie_concurrent)
            quality_label = self.flow_upsample_combo.currentText() if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo else "Gốc"
            self.log(
                f"⚙️ Flow: Nối đuôi với {max_concurrent} công việc đồng thời "
                f"({num_cookies} cookie(s) × {per_cookie_concurrent} - {quality_label})"
            )
            # ✅ BỎ DELAY - Không còn delay giữa các prompt (nối đuôi liên tục)

            # ✅ ĐA COOKIE ROUND-ROBIN: Xử lý từng job với cookie riêng (giống Whisk)
            # Sử dụng ThreadPoolExecutor để xử lý đồng thời với round-robin cookie distribution
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import time
            
            def process_single_flow_job(job_data):
                """Process single Flow job với quy trình cookie mới (giống Text-to-Video)"""
                job = job_data
                job_idx = job.get("tile_index", 0)
                prompt_idx = job.get("prompt_idx", 0)
                
                # ✅ Trạng thái retry cho job này
                failed_cookies_429 = set()  # Cookies bị 429/high-traffic
                failed_cookies_die = set()  # Cookies die (403, 401, fetch token fail)
                # ✅ Lưu retry_non_429 vào job dictionary để không bị reset khi đổi cookie (tránh vòng lặp vô hạn)
                if "_retry_non_429" not in job:
                    job["_retry_non_429"] = 0
                retry_non_429 = job["_retry_non_429"]  # Lấy từ job dictionary
                max_non_429_retries = 6
                
                # ✅ Track số lần retry cho cookie hiện tại (để biết khi nào cần restart context)
                if "_cookie_retry_count" not in job:
                    job["_cookie_retry_count"] = {}  # {cookie_index: retry_count}
                
                # ✅ Track xem cookie đã được restart chưa (sau 6 lần retry)
                if "_cookie_restarted" not in job:
                    job["_cookie_restarted"] = set()  # {cookie_index} - cookies đã được restart
                
                def select_cookie_client():
                    """Chọn cookie theo round-robin, ưu tiên cookie chưa bị 429/die, và fetch được token"""
                    # ✅ Check stop_event trước khi chọn cookie
                    if self.stop_event.is_set():
                        return None, None
                    
                    # Lấy starting index theo round-robin (thread-safe)
                    with cookie_lock:
                        start = cookie_counter["count"] % len(available_cookies)
                        cookie_counter["count"] += 1
                    
                    # Tạo thứ tự candidate: ưu tiên cookie còn sống (không 429, không die)
                    ordered_indices = [(start + shift) % len(available_cookies) for shift in range(len(available_cookies))]
                    # Ưu tiên: cookie còn sống > cookie 429 > cookie die
                    alive = [i for i in ordered_indices if i not in failed_cookies_429 and i not in failed_cookies_die]
                    only_429 = [i for i in ordered_indices if i in failed_cookies_429 and i not in failed_cookies_die]
                    dead = [i for i in ordered_indices if i in failed_cookies_die]
                    
                    for idx in alive + only_429 + dead:
                        # ✅ Check stop_event trong vòng lặp chọn cookie
                        if self.stop_event.is_set():
                            return None, None
                        
                        cookie_str = available_cookies[idx]
                        job_client = self._build_client_from_cookie_str(cookie_str, cookie_index=idx)
                        if not job_client:
                            failed_cookies_die.add(idx)
                            continue
                        
                        # Đăng ký callback renew cookie cho cookie này
                        job_cookie_hash = job_client._cookie_hash
                        LabsFlowClient.register_renew_cookie_callback(job_cookie_hash, self._create_renew_cookie_callback(cookie_str, None))
                        try:
                            if job_client.fetch_access_token():
                                # ✅ Cookie fetch token thành công → remove khỏi failed_cookies_die nếu có
                                if idx in failed_cookies_die:
                                    failed_cookies_die.remove(idx)
                                    self.log(f"✅ Flow job {job_idx}: Cookie {idx+1} đã sống lại (fetch token thành công)")
                                return job_client, idx
                            else:
                                # ✅ Fetch token fail → đánh dấu cookie die
                                error_msg = job_client.last_error_detail or job_client.last_error or "Fetch token failed"
                                self.log(f"⚠️ Flow job {job_idx}: Cookie {idx+1} không fetch được token: {error_msg[:100]}")
                                failed_cookies_die.add(idx)
                        except Exception as e:
                            # ✅ Exception khi fetch token → đánh dấu cookie die
                            err_str = str(e)[:100]
                            self.log(f"⚠️ Flow job {job_idx}: Lỗi fetch token với cookie {idx+1}: {err_str}")
                            failed_cookies_die.add(idx)
                    
                    # Kiểm tra xem còn cookie nào sống không
                    alive_count = len(available_cookies) - len(failed_cookies_die)
                    if alive_count == 0:
                        self._flow_update_tile_status(job_idx, "🛑 Tất cả cookie đều die")
                        self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                        return None, None
                    else:
                        # Vẫn còn cookie sống nhưng không fetch được token ngay → thử lại sau
                        self.log(f"⚠️ Flow job {job_idx}: Còn {alive_count} cookie(s) sống nhưng không fetch được token ngay, sẽ thử lại")
                        return None, None
                
                while True:
                    # ✅ Check stop_event trước khi xử lý
                    if self.stop_event.is_set():
                        self.log(f"⏸️ Flow job {job_idx} dừng do stop event")
                        self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                        return None
                    
                    try:
                        job_client, cookie_index = select_cookie_client()
                        if not job_client:
                            # Không còn cookie hợp lệ → dừng job
                            return None
                        
                        # ✅ Track số lần retry cho cookie hiện tại (khởi tạo nếu chưa có)
                        if cookie_index not in job["_cookie_retry_count"]:
                            job["_cookie_retry_count"][cookie_index] = 0
                        cookie_retry_count = job["_cookie_retry_count"][cookie_index]
                        
                        self.log(f"🌊 Flow job {job_idx} (prompt {prompt_idx}): Dùng cookie {cookie_index+1}/{num_cookies}")
                        self._flow_update_tile_status(job_idx, f"🎯 Đang gọi API (cookie {cookie_index+1})…")
                    
                        # Build request cho job này
                        requests_payload = []
                        
                        # Submit log (không critical)
                        try:
                            job_client.submit_flow_image_log(job.get("session_id"))
                        except Exception as log_err:
                            self.log(f"⚠️ Flow log lỗi cho job {job_idx}: {log_err}")
                        
                        # ✅ Multiple-to-Image: Lấy images từ mapping theo prompt_index
                        image_inputs = []
                        if self.current_flow_mode == "Multiple-to-Image":
                            if prompt_idx in self.flow_m2i_image_mapping:
                                mapping = self.flow_m2i_image_mapping[prompt_idx]
                                subject_mgid = mapping.get('subject_mgid')
                                scene_mgid = mapping.get('scene_mgid')
                                style_mgid = mapping.get('style_mgid')
                                
                                if subject_mgid:
                                    image_inputs.append({
                                        "name": subject_mgid.strip(),
                                        "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                                    })
                                if scene_mgid:
                                    image_inputs.append({
                                        "name": scene_mgid.strip(),
                                        "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                                    })
                                if style_mgid:
                                    image_inputs.append({
                                        "name": style_mgid.strip(),
                                        "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                                    })
                                
                                self.log(f"  📎 Job {job_idx} M2I: Subject={bool(subject_mgid)}, Scene={bool(scene_mgid)}, Style={bool(style_mgid)}")
                        elif self.current_flow_mode == "Folder-Structure":
                            # ✅ LOGIC MỚI: Folder-Structure mode - Map prompt với ảnh dựa trên tên
                            # ✅ Lấy prompt_text TRƯỚC khi dùng
                            prompt_text = str(job.get("prompt", "")).strip()
                            if not prompt_text:
                                self.log(f"⚠️ Job {job_idx} có prompt rỗng, bỏ qua")
                                return None
                            
                            all_images = batch_context.get("all_images", [])
                            if all_images:
                                # Map prompt với ảnh
                                mapped_images = self._map_prompt_to_images(prompt_text, all_images, default_count=3)
                                self.log(f"  🗺️ Job {job_idx}: Prompt map với {len(mapped_images)} ảnh: {[img.name for img in mapped_images]}")
                                
                                # ✅ Lưu reference paths vào job để hiển thị trên card
                                job["reference_paths"] = [str(img.resolve()) for img in mapped_images]
                                
                                # Lấy media_id từ cache CỦA COOKIE ĐANG DÙNG
                                job_cookie_hash = getattr(job_client, '_cookie_hash', None)
                                if not job_cookie_hash:
                                    job_cookie_hash = LabsFlowClient._get_cookie_hash(job_client.cookies if hasattr(job_client, 'cookies') else {})
                                
                                cookie_cache = self.reference_image_media_ids.get(job_cookie_hash, {})
                                
                                for img_path in mapped_images:
                                    img_path_abs = str(img_path.resolve())
                                    media_id = cookie_cache.get(img_path_abs)
                                    if media_id:
                                        image_inputs.append({
                                            "name": media_id.strip(),
                                            "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                                        })
                                        self.log(f"  📎 Job {job_idx} (cookie {job_cookie_hash[:8]}...): Dùng cache cho {img_path.name}")
                                    else:
                                        self.log(f"  ⚠️ Job {job_idx} (cookie {job_cookie_hash[:8]}...): Không tìm thấy cache cho {img_path.name}, bỏ qua")
                            else:
                                self.log(f"  ⚠️ Job {job_idx}: Không có ảnh để map")
                                job["reference_paths"] = []
                        else:
                            # Normal mode: lấy media_id từ cache CỦA COOKIE ĐANG DÙNG (job_client)
                            # ✅ Ưu tiên per-row reference images từ flow_tasks, fallback sang global reference_paths
                            grid_row = job.get("task_grid_row", prompt_idx)
                            per_row_refs = []
                            if hasattr(self, 'flow_tasks') and 0 <= grid_row < len(self.flow_tasks):
                                per_row_refs = self.flow_tasks[grid_row].reference_images or []
                            effective_refs = per_row_refs if per_row_refs else reference_paths
                            
                            if effective_refs:
                                # ✅ Lấy cookie hash từ job_client để lấy cache đúng
                                job_cookie_hash = getattr(job_client, '_cookie_hash', None)
                                if not job_cookie_hash:
                                    job_cookie_hash = LabsFlowClient._get_cookie_hash(job_client.cookies if hasattr(job_client, 'cookies') else {})
                                
                                # ✅ Lấy cache của cookie này
                                job_cookie_cache = self.reference_image_media_ids.get(job_cookie_hash, {})
                                
                                # ✅ Lấy media_id từ cache của cookie này cho từng reference path
                                for ref_path in effective_refs:
                                    ref_path_abs = str(Path(ref_path).resolve())
                                    if ref_path_abs in job_cookie_cache:
                                        media_id = job_cookie_cache[ref_path_abs]
                                        image_inputs.append({
                                            "name": media_id.strip(),
                                            "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                                        })
                                        self.log(f"  📎 Job {job_idx} (cookie {job_cookie_hash[:8]}...): Dùng cache cho {Path(ref_path).name}")
                                    else:
                                        # ✅ Thử upload ngay nếu chưa có trong cache
                                        self.log(f"  📤 Job {job_idx} (cookie {job_cookie_hash[:8]}...): Upload ảnh {Path(ref_path).name}...")
                                        uploaded_media_id = job_client.upload_flow_image(ref_path)
                                        if uploaded_media_id and isinstance(uploaded_media_id, str) and uploaded_media_id.strip():
                                            # Cache lại
                                            if job_cookie_hash not in self.reference_image_media_ids:
                                                self.reference_image_media_ids[job_cookie_hash] = {}
                                            self.reference_image_media_ids[job_cookie_hash][ref_path_abs] = uploaded_media_id
                                            image_inputs.append({
                                                "name": uploaded_media_id.strip(),
                                                "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                                            })
                                            self.log(f"  ✅ Job {job_idx} (cookie {job_cookie_hash[:8]}...): Uploaded {Path(ref_path).name}")
                                        else:
                                            self.log(f"  ⚠️ Job {job_idx} (cookie {job_cookie_hash[:8]}...): Upload thất bại cho {Path(ref_path).name}")
                            
                            # ✅ Validate prompt cho Normal mode (prompt_text chưa được định nghĩa)
                            if 'prompt_text' not in locals():
                                prompt_text = str(job.get("prompt", "")).strip()
                                if not prompt_text:
                                    self.log(f"⚠️ Job {job_idx} có prompt rỗng, bỏ qua")
                                    return None
                        
                        client_context = {}
                        # Token Flow image được inject một lần trong generate_flow_images() rồi mirror vào từng request.

                        # ✅ Thêm sessionId, projectId, và tool vào clientContext của mỗi request (theo curl example)
                        client_context["sessionId"] = f";{int(time.time() * 1000)}"
                        
                        # ✅ Lấy projectId từ job_client
                        project_id = getattr(job_client, 'flow_project_id', None)
                        if project_id:
                            client_context["projectId"] = project_id
                        
                        # ✅ Thêm tool (theo curl example là "PINHOLE")
                        client_context["tool"] = "PINHOLE"
                        
                        # ✅ Thêm userPaygateTier (giống generate_videos)
                        client_context["userPaygateTier"] = "PAYGATE_TIER_TWO"

                        # ✅ Đảm bảo imageInputs là array (theo curl example)
                        if image_inputs is None:
                            image_inputs = []
                        
                        # ✅ Tạo request_item với thứ tự field giống curl example: seed, imageModelName, imageAspectRatio, prompt, imageInputs
                        request_item = {
                            "clientContext": client_context,
                        }
                        
                        # ✅ Add seed trước (theo curl example)
                        seed_val = job.get("seed")
                        if seed_val is not None:
                            try:
                                seed_int = int(seed_val)
                                if 1 <= seed_int <= 999999:
                                    request_item["seed"] = seed_int
                            except (ValueError, TypeError):
                                pass
                        
                        # ✅ Thêm các field còn lại theo thứ tự curl example
                        request_item["imageModelName"] = str(model_code)
                        request_item["imageAspectRatio"] = str(aspect_ratio)
                        request_item["structuredPrompt"] = {"parts": [{"text": prompt_text}]}
                        # ✅ Chỉ thêm imageInputs khi có ảnh tham chiếu (tránh gửi [] gây lỗi 500)
                        if image_inputs:
                            request_item["imageInputs"] = image_inputs
                        
                        requests_payload.append(request_item)
                    
                        # ✅ Check stop_event trước khi gọi API
                        if self.stop_event.is_set():
                            self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi gọi API)")
                            self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                            return None
                    
                        # ✅ Gửi request với cookie riêng của job này
                        self.log(f"📤 Flow job {job_idx}: Gửi request với cookie {cookie_index+1}")
                        api_result = job_client.generate_flow_images(requests_payload)

                        # ✅ Debug: Log error detail ngay sau khi gọi API
                        if not api_result:
                            debug_error = job_client.last_error_detail or job_client.last_error or "Unknown error"
                            self.log(f"🔍 [DEBUG API] job_client.last_error_detail: {debug_error}")
                        
                        # ✅ Check stop_event sau khi gọi API
                        if self.stop_event.is_set():
                            self.log(f"⏸️ Flow job {job_idx} dừng do stop event (sau khi gọi API)")
                            self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                            return None
                        
                        # ✅ Nếu job này đã chạy thành công ít nhất 1 lần trước đó, áp dụng delay người dùng cấu hình
                        # để tạo khoảng cách giữa các prompt trong CÙNG 1 cookie.
                        try:
                            delay_seconds = 0
                            if hasattr(self, "flow_delay_spin"):
                                delay_seconds = int(self.flow_delay_spin.value())
                            # Chỉ delay nếu delay_seconds > 0 và đây KHÔNG phải là lần retry do lỗi
                            if delay_seconds > 0 and retry_non_429 == 0:
                                self.log(f"⏳ Flow job {job_idx}: Chờ {delay_seconds}s trước khi xử lý prompt tiếp theo cho cookie {cookie_index+1}")
                                for _ in range(delay_seconds):
                                    if self.stop_event.is_set():
                                        self.log("⏹️ Stop event được set trong khi delay, dừng job.")
                                        break
                                    time.sleep(1)
                        except Exception as _delay_err:
                            # Không để delay làm crash job, chỉ log nhẹ
                            try:
                                self.log(f"⚠️ Flow delay error (job {job_idx}): {_delay_err}")
                            except Exception:
                                pass
                        
                        if not api_result:
                            error_detail = job_client.last_error_detail or job_client.last_error or "API trả về lỗi"
                            error_str = str(error_detail).lower()

                            # ✅ Nếu là lỗi prompt vi phạm quy tắc / INVALID_ARGUMENT → phân biệt rõ nguyên nhân
                            if ("invalid_argument" in error_str
                                or "public_error_unsafe_generation" in error_str
                                or "prompt vi phạm quy tắc" in error_str
                                or "prompt bị từ chối" in error_str):
                                # Phân biệt: unsafe content vs lỗi format/cú pháp prompt
                                is_unsafe = ("public_error_unsafe_generation" in error_str
                                             or "unsafe" in error_str
                                             or "vi phạm quy tắc nội dung" in error_str)
                                if is_unsafe:
                                    user_msg = (
                                        "Prompt vi phạm quy tắc nội dung của Google "
                                        "(400 INVALID_ARGUMENT - PUBLIC_ERROR_UNSAFE_GENERATION). "
                                        "Vui lòng chỉnh sửa nội dung prompt cho phù hợp rồi chạy lại."
                                    )
                                    tile_msg = "❌ Prompt vi phạm nội dung"
                                else:
                                    user_msg = (
                                        "Prompt bị từ chối bởi Google (400 INVALID_ARGUMENT). "
                                        "Có thể do prompt quá dài, chứa ký tự đặc biệt, hoặc format không hợp lệ. "
                                        "Vui lòng kiểm tra và chỉnh sửa prompt rồi chạy lại."
                                    )
                                    tile_msg = "❌ Prompt không hợp lệ"
                                self.log(f"⚠️ Flow job {job_idx}: {user_msg}")
                                self._flow_update_tile_status(job_idx, tile_msg)
                                return {
                                    "job": job,
                                    "image_path": None,
                                    "success": False,
                                    "error": user_msg,
                                }
                            
                            # ✅ Nếu là lỗi 500 Internal Server Error từ Google → báo lỗi rõ ràng và bỏ qua task
                            if ("500" in error_str and "internal" in error_str) or "lỗi tạm thời từ google labs" in error_str:
                                user_msg = (
                                    "500 Internal Server Error - Lỗi tạm thời từ phía Google Labs. "
                                    "Vui lòng chờ vài giây rồi thử chạy lại."
                                )
                                self.log(f"⚠️ Flow job {job_idx}: {user_msg}")
                                self._flow_update_tile_status(job_idx, "❌ Lỗi Server Google (500)")
                                return {
                                    "job": job,
                                    "image_path": None,
                                    "success": False,
                                    "error": user_msg,
                                }
                            
                            # ✅ Nếu là lỗi 502/503/504 (Gateway Error, Service Unavailable, Gateway Timeout) → báo lỗi rõ ràng
                            if ("502" in error_str or "503" in error_str or "504" in error_str) and (
                                "bad gateway" in error_str or "unavailable" in error_str or "timeout" in error_str
                            ):
                                user_msg = (
                                    "Lỗi kết nối tạm thời với Google Labs (502/503/504). "
                                    "Vui lòng chờ vài giây rồi thử chạy lại."
                                )
                                self.log(f"⚠️ Flow job {job_idx}: {user_msg}")
                                self._flow_update_tile_status(job_idx, "❌ Lỗi kết nối Google (502/503/504)")
                                return {
                                    "job": job,
                                    "image_path": None,
                                    "success": False,
                                    "error": user_msg,
                                }
                            
                            # ✅ Phân biệt lỗi 429/high traffic vs cookie die vs lỗi khác
                            if self._check_is_429_or_high_traffic(str(error_detail)):
                                failed_cookies_429.add(cookie_index)
                                # Nếu tất cả cookie đều đã bị 429, chờ lâu hơn và reset danh sách để thử lại
                                if len(failed_cookies_429) >= len(available_cookies):
                                    self.log("⏳ Flow: Tất cả cookie đều 429/high-traffic, chờ 12s rồi thử lại toàn bộ")
                                    # ✅ Check stop_event trong delay
                                    for _ in range(12):
                                        if self.stop_event.is_set():
                                            self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trong delay 429)")
                                            self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                            return None
                                        time.sleep(1)
                                    failed_cookies_429.clear()
                                    continue
                                self.log(f"⚠️ Flow job {job_idx}: Cookie {cookie_index+1} bị 429/high-traffic, sẽ đổi cookie sau 6s")
                                self._flow_update_tile_status(job_idx, "⏳ 429 / High traffic, đổi cookie khác sau 6s…")
                                
                                # ✅ Check stop_event trong delay
                                for _ in range(6):
                                    if self.stop_event.is_set():
                                        self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trong delay 429)")
                                        self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                        return None
                                    time.sleep(1)
                                # ✅ KHÔNG reset retry_non_429 khi đổi cookie - giữ nguyên để tránh vòng lặp vô hạn
                                # retry_non_429 đã được lưu trong job dictionary, không cần reset
                                
                                # ✅ Check stop_event trước khi đổi cookie
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do 429)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue  # Thử lại với cookie khác

                            # ✅ Debug log cho 401 - xem có vào đây không
                            if "401" in error_str or "unauthorized" in error_str:
                                self.log(f"🔍 [DEBUG 401] error_detail: {error_detail[:200]}")
                                self.log(f"🔍 [DEBUG 401] error_str contains: 401={('401' in error_str)}, unauthorized={('unauthorized' in error_str)}")

                            elif ("403" in error_str or "401" in error_str or
                                  "forbidden" in error_str or "unauthorized" in error_str or
                                  "cookie" in error_str and ("die" in error_str or "expired" in error_str or "invalid" in error_str)):
                                # ✅ Cookie die (403, 401, forbidden, unauthorized, cookie expired/invalid)
                                failed_cookies_die.add(cookie_index)
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} DIE ({error_detail[:100]}) → đổi cookie khác")
                                self._on_403_detected(job_idx)
                                
                                # Kiểm tra xem còn cookie nào sống không
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                # ✅ Reset retry_non_429 khi đổi cookie do die (cookie mới có thể work)
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                
                                # ✅ Check stop_event trước khi đổi cookie
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue  # Thử lại với cookie khác
                            else:
                                # Lỗi khác (không phải 429, không phải cookie die)
                                retry_non_429 += 1
                                job["_retry_non_429"] = retry_non_429  # ✅ Lưu vào job dictionary
                                
                                # ✅ Track số lần retry cho cookie hiện tại
                                job["_cookie_retry_count"][cookie_index] += 1
                                cookie_retry_count = job["_cookie_retry_count"][cookie_index]
                                
                                # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                                if cookie_retry_count >= 2 and cookie_index not in job["_cookie_restarted"]:
                                    self.log(f"🔄 Flow job {job_idx}: Cookie {cookie_index+1} đã retry 6 lần → restart BrowserContext (renew cookie)")
                                    self._flow_update_tile_status(job_idx, f"🔄 Restart BrowserContext (retry 6/6)")
                                    
                                    # Gọi renew cookie và restart context
                                    try:
                                        cookie_hash = job_client._cookie_hash if hasattr(job_client, '_cookie_hash') else None
                                        
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
                                                    old_cookies=job_client.cookies if hasattr(job_client, 'cookies') else {},
                                                    proxy_config=getattr(job_client, 'proxy_config', None),
                                                    user_agent=getattr(job_client, 'user_agent', ''),
                                                    get_new_cookies_callback=get_new_cookies_callback,
                                                )
                                                
                                                if new_cookies:
                                                    # ✅ Update cookies trong client hiện tại
                                                    job_client.cookies = new_cookies
                                                    # Re-fetch token với cookie mới
                                                    if job_client.fetch_access_token():
                                                        job["_cookie_restarted"].add(cookie_index)
                                                        job["_cookie_retry_count"][cookie_index] = 0  # Reset counter sau khi restart
                                                        self.log(f"✅ Flow job {job_idx}: Cookie {cookie_index+1} đã được renew và restart thành công")
                                                    else:
                                                        self.log(f"⚠️ Flow job {job_idx}: Cookie {cookie_index+1} renew thành công nhưng fetch token fail")
                                                else:
                                                    self.log(f"⚠️ Flow job {job_idx}: Không thể renew cookie {cookie_index+1}")
                                            else:
                                                self.log(f"⚠️ Flow job {job_idx}: Không có callback để renew cookie {cookie_index+1}")
                                    except Exception as renew_err:
                                        self.log(f"⚠️ Flow job {job_idx}: Lỗi khi renew cookie {cookie_index+1}: {renew_err}")
                                        import traceback
                                        self.log(traceback.format_exc())
                                    
                                    # ✅ Check stop_event trước khi retry sau khi renew cookie
                                    if self.stop_event.is_set():
                                        self.log(f"⏸️ Flow job {job_idx} dừng do stop event (sau khi renew cookie)")
                                        self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                        return None
                                    
                                    # Tiếp tục retry với cookie (có thể đã được renew)
                                    continue
                                
                                # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → đánh dấu cookie die
                                if cookie_retry_count >= 3 and cookie_index in job["_cookie_restarted"]:
                                    self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} đã restart nhưng vẫn lỗi sau lần thứ 7 → đánh dấu die")
                                    failed_cookies_die.add(cookie_index)
                                    
                                    # Kiểm tra xem còn cookie nào sống không
                                    alive_count = len(available_cookies) - len(failed_cookies_die)
                                    if alive_count == 0:
                                        self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                        self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                        return None
                                    
                                    self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                    # ✅ Reset retry_non_429 khi đổi cookie do die (cookie mới có thể work)
                                    job["_retry_non_429"] = 0
                                    retry_non_429 = 0
                                    continue  # Thử lại với cookie khác
                                
                                short_err = str(error_detail)[:120]
                                if retry_non_429 <= max_non_429_retries:
                                    self.log(f"⚠️ Flow job {job_idx}: Lỗi không phải 429 ({short_err}) → retry {retry_non_429}/{max_non_429_retries} với cùng cookie {cookie_index+1} (cookie retry: {cookie_retry_count})")
                                    self._flow_update_tile_status(job_idx, f"⚠️ Lỗi, retry {retry_non_429}/{max_non_429_retries}…")
                                    
                                    # ✅ Check stop_event trước khi retry
                                    if self.stop_event.is_set():
                                        self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi retry lỗi non-429)")
                                        self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                        return None
                                    
                                    continue
                                else:
                                    # Sau max retries với lỗi không phải 429 → đánh dấu cookie die và đổi cookie
                                    self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} lỗi sau {max_non_429_retries} lần retry → đánh dấu die và đổi cookie")
                                    failed_cookies_die.add(cookie_index)
                                    
                                    # Kiểm tra xem còn cookie nào sống không
                                    alive_count = len(available_cookies) - len(failed_cookies_die)
                                    if alive_count == 0:
                                        self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                        self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                        return None
                                    
                                    self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                    # ✅ Reset retry_non_429 khi đổi cookie do die
                                    job["_retry_non_429"] = 0
                                    retry_non_429 = 0
                                    continue  # Thử lại với cookie khác
                        
                        # Extract và parse images
                        immediate_payloads, pending_operations = job_client.extract_flow_media_payloads(api_result)
                        payloads_to_parse = []
                        if immediate_payloads:
                            payloads_to_parse.extend(immediate_payloads)
                        else:
                            payloads_to_parse.append(api_result)

                        if pending_operations:
                            self.log(f"⏳ Flow job {job_idx}: Chờ {len(pending_operations)} operation(s)")
                            self._flow_update_tile_status(job_idx, "⏳ Flow đang xử lý…")
                            
                            # ✅ Check stop_event trước khi poll
                            if self.stop_event.is_set():
                                self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi poll operations)")
                                self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                return None
                            
                            polled_payloads = job_client.poll_flow_operations(pending_operations, stop_event=self.stop_event)
                            
                            # ✅ Check stop_event sau khi poll
                            if self.stop_event.is_set():
                                self.log(f"⏸️ Flow job {job_idx} dừng do stop event (sau khi poll operations)")
                                self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                return None
                            
                            if polled_payloads:
                                payloads_to_parse.extend(polled_payloads)

                        # ✅ Check stop_event trước khi parse images
                        if self.stop_event.is_set():
                            self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi parse images)")
                            self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                            return None
                        
                        # Parse images
                        all_images = []
                        for payload in payloads_to_parse:
                            # ✅ Check stop_event trong vòng lặp parse
                            if self.stop_event.is_set():
                                self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trong khi parse images)")
                                self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                return None
                            
                            parsed = job_client.parse_flow_image_response(payload)
                            if parsed:
                                all_images.extend(parsed)
                        
                        if not all_images:
                            # Không có ảnh → coi là lỗi non-429, áp dụng retry 6 lần
                            retry_non_429 += 1
                            job["_retry_non_429"] = retry_non_429  # ✅ Lưu vào job dictionary
                            
                            # ✅ Track số lần retry cho cookie hiện tại
                            job["_cookie_retry_count"][cookie_index] += 1
                            cookie_retry_count = job["_cookie_retry_count"][cookie_index]
                            
                            # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                            if cookie_retry_count == 6 and cookie_index not in job["_cookie_restarted"]:
                                self.log(f"🔄 Flow job {job_idx}: Cookie {cookie_index+1} đã retry 6 lần (không nhận được ảnh) → restart BrowserContext (renew cookie)")
                                self._flow_update_tile_status(job_idx, f"🔄 Restart BrowserContext (retry 6/6)")
                                
                                # Gọi renew cookie và restart context
                                try:
                                    cookie_hash = job_client._cookie_hash if hasattr(job_client, '_cookie_hash') else None
                                    
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
                                                old_cookies=job_client.cookies if hasattr(job_client, 'cookies') else {},
                                                proxy_config=getattr(job_client, 'proxy_config', None),
                                                user_agent=getattr(job_client, 'user_agent', ''),
                                                get_new_cookies_callback=get_new_cookies_callback,
                                            )
                                            
                                            if new_cookies:
                                                # ✅ Update cookies trong client hiện tại
                                                job_client.cookies = new_cookies
                                                # Re-fetch token với cookie mới
                                                if job_client.fetch_access_token():
                                                    job["_cookie_restarted"].add(cookie_index)
                                                    job["_cookie_retry_count"][cookie_index] = 0  # Reset counter sau khi restart
                                                    self.log(f"✅ Flow job {job_idx}: Cookie {cookie_index+1} đã được renew và restart thành công")
                                                else:
                                                    self.log(f"⚠️ Flow job {job_idx}: Cookie {cookie_index+1} renew thành công nhưng fetch token fail")
                                            else:
                                                self.log(f"⚠️ Flow job {job_idx}: Không thể renew cookie {cookie_index+1}")
                                        else:
                                            self.log(f"⚠️ Flow job {job_idx}: Không có callback để renew cookie {cookie_index+1}")
                                except Exception as renew_err:
                                    self.log(f"⚠️ Flow job {job_idx}: Lỗi khi renew cookie {cookie_index+1}: {renew_err}")
                                    import traceback
                                    self.log(traceback.format_exc())
                                
                                # Tiếp tục retry với cookie (có thể đã được renew)
                                continue
                            
                            # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → đánh dấu cookie die
                            if cookie_retry_count >= 7 and cookie_index in job["_cookie_restarted"]:
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} đã restart nhưng vẫn không nhận được ảnh sau lần thứ 7 → đánh dấu die")
                                failed_cookies_die.add(cookie_index)
                                
                                # Kiểm tra xem còn cookie nào sống không
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                # ✅ Reset retry_non_429 khi đổi cookie do die
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                
                                # ✅ Check stop_event trước khi đổi cookie
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue  # Thử lại với cookie khác
                            
                            if retry_non_429 <= max_non_429_retries:
                                self.log(f"⚠️ Flow job {job_idx}: Không nhận được dữ liệu ảnh → retry {retry_non_429}/{max_non_429_retries} (cookie retry: {cookie_retry_count})")
                                self._flow_update_tile_status(job_idx, f"⚠️ Không nhận được ảnh, retry {retry_non_429}/{max_non_429_retries}…")
                                
                                # ✅ Check stop_event trước khi retry
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi retry không nhận được ảnh)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue
                            else:
                                # Sau max retries không nhận được ảnh → đánh dấu cookie die và đổi cookie
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} không nhận được ảnh sau {max_non_429_retries} lần retry → đánh dấu die và đổi cookie")
                                failed_cookies_die.add(cookie_index)
                                
                                # Kiểm tra xem còn cookie nào sống không
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                # ✅ Reset retry_non_429 khi đổi cookie do die
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                
                                # ✅ Check stop_event trước khi đổi cookie
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue  # Thử lại với cookie khác
                        
                        # Lấy ảnh đầu tiên (Flow thường trả về 1 ảnh per request)
                        image_info = all_images[0] if all_images else None
                        if not image_info:
                            # Không có ảnh trong response → track retry và restart nếu cần
                            retry_non_429 += 1
                            job["_retry_non_429"] = retry_non_429
                            
                            # ✅ Track số lần retry cho cookie hiện tại
                            job["_cookie_retry_count"][cookie_index] += 1
                            cookie_retry_count = job["_cookie_retry_count"][cookie_index]
                            
                            # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                            if cookie_retry_count == 6 and cookie_index not in job["_cookie_restarted"]:
                                self.log(f"🔄 Flow job {job_idx}: Cookie {cookie_index+1} đã retry 6 lần (không có ảnh) → restart BrowserContext (renew cookie)")
                                self._flow_update_tile_status(job_idx, f"🔄 Restart BrowserContext (retry 6/6)")
                                
                                # Gọi renew cookie và restart context
                                try:
                                    cookie_hash = job_client._cookie_hash if hasattr(job_client, '_cookie_hash') else None
                                    
                                    if cookie_hash:
                                        get_new_cookies_callback = None
                                        if hasattr(LabsFlowClient, '_recaptcha_renew_cookie_callbacks'):
                                            get_new_cookies_callback = LabsFlowClient._recaptcha_renew_cookie_callbacks.get(cookie_hash)
                                        
                                        if get_new_cookies_callback:
                                            new_cookies = LabsFlowClient._renew_cookie_and_restart_context(
                                                browser=LabsFlowClient._recaptcha_worker_browser if hasattr(LabsFlowClient, '_recaptcha_worker_browser') else None,
                                                cookie_hash=cookie_hash,
                                                old_cookies=job_client.cookies if hasattr(job_client, 'cookies') else {},
                                                proxy_config=getattr(job_client, 'proxy_config', None),
                                                user_agent=getattr(job_client, 'user_agent', ''),
                                                get_new_cookies_callback=get_new_cookies_callback,
                                            )
                                            
                                            if new_cookies:
                                                job_client.cookies = new_cookies
                                                if job_client.fetch_access_token():
                                                    job["_cookie_restarted"].add(cookie_index)
                                                    job["_cookie_retry_count"][cookie_index] = 0
                                                    self.log(f"✅ Flow job {job_idx}: Cookie {cookie_index+1} đã được renew và restart thành công")
                                                else:
                                                    self.log(f"⚠️ Flow job {job_idx}: Cookie {cookie_index+1} renew thành công nhưng fetch token fail")
                                            else:
                                                self.log(f"⚠️ Flow job {job_idx}: Không thể renew cookie {cookie_index+1}")
                                        else:
                                            self.log(f"⚠️ Flow job {job_idx}: Không có callback để renew cookie {cookie_index+1}")
                                except Exception as renew_err:
                                    self.log(f"⚠️ Flow job {job_idx}: Lỗi khi renew cookie {cookie_index+1}: {renew_err}")
                                    import traceback
                                    self.log(traceback.format_exc())
                                
                                continue
                            
                            # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → đánh dấu cookie die
                            if cookie_retry_count >= 7 and cookie_index in job["_cookie_restarted"]:
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} đã restart nhưng vẫn không có ảnh sau lần thứ 7 → đánh dấu die")
                                failed_cookies_die.add(cookie_index)
                                
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                continue
                            
                            # Nếu chưa đến 6 lần hoặc chưa restart, đánh dấu die ngay
                            self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} không có ảnh trong response → đánh dấu die và đổi cookie")
                            failed_cookies_die.add(cookie_index)
                            
                            # Kiểm tra xem còn cookie nào sống không
                            alive_count = len(available_cookies) - len(failed_cookies_die)
                            if alive_count == 0:
                                self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                return None
                            
                            self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                            # ✅ Reset retry_non_429 khi đổi cookie do die
                            job["_retry_non_429"] = 0
                            retry_non_429 = 0
                            
                            # ✅ Check stop_event trước khi đổi cookie
                            if self.stop_event.is_set():
                                self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                return None
                            
                            continue  # Thử lại với cookie khác
                        
                        # ✅ Extract mediaId từ response để dùng cho upsample (không cần upload lại)
                        flow_media_id = None
                        for payload in payloads_to_parse:
                            extracted_id = job_client.extract_flow_media_id(payload)
                            if extracted_id:
                                flow_media_id = extracted_id
                                break
                        if flow_media_id:
                            image_info["mediaId"] = flow_media_id
                            self.log(f"✅ Flow job {job_idx}: Đã extract mediaId từ response: {flow_media_id[:50]}...")
                        
                        # ✅ Check stop_event trước khi lưu ảnh
                        if self.stop_event.is_set():
                            self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi lưu ảnh)")
                            self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                            return None
                        
                        # Lưu ảnh
                        saved_path = self._save_flow_image(job_client, image_info, output_dir, job)
                        
                        # ✅ Check stop_event sau khi lưu ảnh
                        if self.stop_event.is_set():
                            self.log(f"⏸️ Flow job {job_idx} dừng do stop event (sau khi lưu ảnh)")
                            self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                            return None
                        
                        if saved_path:
                            saved_path_abs = Path(saved_path).resolve()
                            if saved_path_abs.exists():
                                self.log(f"✅ Flow job {job_idx}: Đã lưu ảnh: {saved_path_abs.name}")
                                return {
                                    "job": job,
                                    "image_path": str(saved_path_abs),
                                    "success": True
                                }
                            else:
                                self.log(f"❌ Flow job {job_idx}: File không tồn tại sau khi lưu")
                                self._flow_update_tile_status(job_idx, "❌ File không tồn tại")
                                return None
                        else:
                            # Lưu ảnh lỗi → count như lỗi non-429
                            retry_non_429 += 1
                            job["_retry_non_429"] = retry_non_429  # ✅ Lưu vào job dictionary
                            
                            # ✅ Track số lần retry cho cookie hiện tại
                            job["_cookie_retry_count"][cookie_index] += 1
                            cookie_retry_count = job["_cookie_retry_count"][cookie_index]
                            
                            # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                            if cookie_retry_count == 6 and cookie_index not in job["_cookie_restarted"]:
                                self.log(f"🔄 Flow job {job_idx}: Cookie {cookie_index+1} đã retry 6 lần (không lưu được ảnh) → restart BrowserContext (renew cookie)")
                                self._flow_update_tile_status(job_idx, f"🔄 Restart BrowserContext (retry 6/6)")
                                
                                # Gọi renew cookie và restart context
                                try:
                                    cookie_hash = job_client._cookie_hash if hasattr(job_client, '_cookie_hash') else None
                                    
                                    if cookie_hash:
                                        get_new_cookies_callback = None
                                        if hasattr(LabsFlowClient, '_recaptcha_renew_cookie_callbacks'):
                                            get_new_cookies_callback = LabsFlowClient._recaptcha_renew_cookie_callbacks.get(cookie_hash)
                                        
                                        if get_new_cookies_callback:
                                            new_cookies = LabsFlowClient._renew_cookie_and_restart_context(
                                                browser=LabsFlowClient._recaptcha_worker_browser if hasattr(LabsFlowClient, '_recaptcha_worker_browser') else None,
                                                cookie_hash=cookie_hash,
                                                old_cookies=job_client.cookies if hasattr(job_client, 'cookies') else {},
                                                proxy_config=getattr(job_client, 'proxy_config', None),
                                                user_agent=getattr(job_client, 'user_agent', ''),
                                                get_new_cookies_callback=get_new_cookies_callback,
                                            )
                                            
                                            if new_cookies:
                                                job_client.cookies = new_cookies
                                                if job_client.fetch_access_token():
                                                    job["_cookie_restarted"].add(cookie_index)
                                                    job["_cookie_retry_count"][cookie_index] = 0
                                                    self.log(f"✅ Flow job {job_idx}: Cookie {cookie_index+1} đã được renew và restart thành công")
                                                else:
                                                    self.log(f"⚠️ Flow job {job_idx}: Cookie {cookie_index+1} renew thành công nhưng fetch token fail")
                                            else:
                                                self.log(f"⚠️ Flow job {job_idx}: Không thể renew cookie {cookie_index+1}")
                                        else:
                                            self.log(f"⚠️ Flow job {job_idx}: Không có callback để renew cookie {cookie_index+1}")
                                except Exception as renew_err:
                                    self.log(f"⚠️ Flow job {job_idx}: Lỗi khi renew cookie {cookie_index+1}: {renew_err}")
                                    import traceback
                                    self.log(traceback.format_exc())
                                
                                continue
                            
                            # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → đánh dấu cookie die
                            if cookie_retry_count >= 7 and cookie_index in job["_cookie_restarted"]:
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} đã restart nhưng vẫn không lưu được ảnh sau lần thứ 7 → đánh dấu die")
                                failed_cookies_die.add(cookie_index)
                                
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                continue
                            
                            if retry_non_429 <= max_non_429_retries:
                                self.log(f"⚠️ Flow job {job_idx}: Không lưu được ảnh → retry {retry_non_429}/{max_non_429_retries} (cookie retry: {cookie_retry_count})")
                                self._flow_update_tile_status(job_idx, f"⚠️ Không lưu được ảnh, retry {retry_non_429}/{max_non_429_retries}…")
                                
                                # ✅ Check stop_event trước khi retry
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi retry không lưu được ảnh)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue
                            else:
                                # Sau max retries không lưu được ảnh → đánh dấu cookie die và đổi cookie
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} không lưu được ảnh sau {max_non_429_retries} lần retry → đánh dấu die và đổi cookie")
                                failed_cookies_die.add(cookie_index)
                                
                                # Kiểm tra xem còn cookie nào sống không
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                # ✅ Reset retry_non_429 khi đổi cookie do die
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                
                                # ✅ Check stop_event trước khi đổi cookie
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue  # Thử lại với cookie khác
                        
                    except Exception as e:
                        # Bắt lỗi chung, phân loại 429 vs cookie die vs non-429
                        err_str = str(e)
                        err_lower = err_str.lower()
                        
                        if self._check_is_429_or_high_traffic(err_str):
                            failed_cookies_429.add(cookie_index)
                            self.log(f"⚠️ Flow job {job_idx}: Exception 429/high-traffic với cookie {cookie_index+1}: {err_str[:120]}")
                            self._flow_update_tile_status(job_idx, "⏳ 429 / High traffic, đổi cookie khác sau 6s…")
                            
                            # ✅ Check stop_event trong delay
                            for _ in range(6):
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trong delay 429 exception)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                time.sleep(1)
                            
                            # ✅ KHÔNG reset retry_non_429 khi đổi cookie - giữ nguyên để tránh vòng lặp vô hạn
                            continue
                        elif ("403" in err_lower or "401" in err_lower or
                              "forbidden" in err_lower or "unauthorized" in err_lower or
                              "cookie" in err_lower and ("die" in err_lower or "expired" in err_lower or "invalid" in err_lower)):
                            # ✅ Cookie die từ exception → đánh dấu và đổi cookie ngay
                            failed_cookies_die.add(cookie_index)
                            self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} DIE từ exception ({err_str[:100]}) → đổi cookie khác")
                            self._on_403_detected(job_idx)
                            
                            # Kiểm tra xem còn cookie nào sống không
                            alive_count = len(available_cookies) - len(failed_cookies_die)
                            if alive_count == 0:
                                self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                return None
                            
                            self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                            # ✅ Reset retry_non_429 khi đổi cookie do die
                            job["_retry_non_429"] = 0
                            retry_non_429 = 0
                            
                            # ✅ Check stop_event trước khi đổi cookie
                            if self.stop_event.is_set():
                                self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                return None
                            
                            continue  # Thử lại với cookie khác
                        else:
                            # Lỗi khác (không phải 429, không phải cookie die)
                            retry_non_429 += 1
                            job["_retry_non_429"] = retry_non_429  # ✅ Lưu vào job dictionary
                            
                            # ✅ Track số lần retry cho cookie hiện tại
                            job["_cookie_retry_count"][cookie_index] += 1
                            cookie_retry_count = job["_cookie_retry_count"][cookie_index]
                            
                            # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                            if cookie_retry_count == 6 and cookie_index not in job["_cookie_restarted"]:
                                self.log(f"🔄 Flow job {job_idx}: Cookie {cookie_index+1} đã retry 6 lần (exception) → restart BrowserContext (renew cookie)")
                                self._flow_update_tile_status(job_idx, f"🔄 Restart BrowserContext (retry 6/6)")
                                
                                # Gọi renew cookie và restart context
                                try:
                                    cookie_hash = job_client._cookie_hash if hasattr(job_client, '_cookie_hash') else None
                                    
                                    if cookie_hash:
                                        get_new_cookies_callback = None
                                        if hasattr(LabsFlowClient, '_recaptcha_renew_cookie_callbacks'):
                                            get_new_cookies_callback = LabsFlowClient._recaptcha_renew_cookie_callbacks.get(cookie_hash)
                                        
                                        if get_new_cookies_callback:
                                            new_cookies = LabsFlowClient._renew_cookie_and_restart_context(
                                                browser=LabsFlowClient._recaptcha_worker_browser if hasattr(LabsFlowClient, '_recaptcha_worker_browser') else None,
                                                cookie_hash=cookie_hash,
                                                old_cookies=job_client.cookies if hasattr(job_client, 'cookies') else {},
                                                proxy_config=getattr(job_client, 'proxy_config', None),
                                                user_agent=getattr(job_client, 'user_agent', ''),
                                                get_new_cookies_callback=get_new_cookies_callback,
                                            )
                                            
                                            if new_cookies:
                                                job_client.cookies = new_cookies
                                                if job_client.fetch_access_token():
                                                    job["_cookie_restarted"].add(cookie_index)
                                                    job["_cookie_retry_count"][cookie_index] = 0
                                                    self.log(f"✅ Flow job {job_idx}: Cookie {cookie_index+1} đã được renew và restart thành công")
                                                else:
                                                    self.log(f"⚠️ Flow job {job_idx}: Cookie {cookie_index+1} renew thành công nhưng fetch token fail")
                                            else:
                                                self.log(f"⚠️ Flow job {job_idx}: Không thể renew cookie {cookie_index+1}")
                                        else:
                                            self.log(f"⚠️ Flow job {job_idx}: Không có callback để renew cookie {cookie_index+1}")
                                except Exception as renew_err:
                                    self.log(f"⚠️ Flow job {job_idx}: Lỗi khi renew cookie {cookie_index+1}: {renew_err}")
                                    import traceback
                                    self.log(traceback.format_exc())
                                
                                continue
                            
                            # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → đánh dấu cookie die
                            if cookie_retry_count >= 7 and cookie_index in job["_cookie_restarted"]:
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} đã restart nhưng vẫn lỗi exception sau lần thứ 7 → đánh dấu die")
                                failed_cookies_die.add(cookie_index)
                                
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                continue
                            
                            short_err = err_str[:120]
                            if retry_non_429 <= max_non_429_retries:
                                self.log(f"⚠️ Flow job {job_idx}: Lỗi exception ({short_err}) → retry {retry_non_429}/{max_non_429_retries} (cookie retry: {cookie_retry_count})")
                                self._flow_update_tile_status(job_idx, f"⚠️ Lỗi, retry {retry_non_429}/{max_non_429_retries}…")
                                
                                # ✅ Check stop_event trước khi retry
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi retry exception)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue
                            else:
                                # Sau max retries với lỗi không phải 429/die → đánh dấu cookie die và đổi cookie
                                self.log(f"💀 Flow job {job_idx}: Cookie {cookie_index+1} lỗi exception sau {max_non_429_retries} lần retry → đánh dấu die và đổi cookie")
                                failed_cookies_die.add(cookie_index)
                                
                                # Kiểm tra xem còn cookie nào sống không
                                alive_count = len(available_cookies) - len(failed_cookies_die)
                                if alive_count == 0:
                                    self.log(f"🛑 Flow job {job_idx}: Tất cả {len(available_cookies)} cookie(s) đều die")
                                    self._flow_update_tile_status(job_idx, f"🛑 Tất cả cookie die")
                                    return None
                                
                                self._flow_update_tile_status(job_idx, f"💀 Cookie {cookie_index+1} die, đổi sang cookie khác (còn {alive_count} cookie sống)…")
                                # ✅ Reset retry_non_429 khi đổi cookie do die
                                job["_retry_non_429"] = 0
                                retry_non_429 = 0
                                
                                # ✅ Check stop_event trước khi đổi cookie
                                if self.stop_event.is_set():
                                    self.log(f"⏸️ Flow job {job_idx} dừng do stop event (trước khi đổi cookie do die)")
                                    self._flow_update_tile_status(job_idx, "⏸️ Đã dừng")
                                    return None
                                
                                continue  # Thử lại với cookie khác
            
            # ✅ Xử lý jobs với ThreadPoolExecutor - NỐI ĐUÔI (giống tab video)
            quality_label = self.flow_upsample_combo.currentText() if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo else "Gốc"
            self.log(
                f"🚀 Flow bắt đầu xử lý {len(jobs)} job(s) với {max_concurrent} công việc đồng thời "
                f"({num_cookies} cookie(s) × {per_cookie_concurrent} - {quality_label})"
            )
            
            # ✅ BỎ DELAY - Submit tất cả jobs ngay lập tức (nối đuôi liên tục)
            with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                # Submit tất cả tasks vào executor (sẽ tự động giới hạn concurrent)
                future_to_job = {}
                for job in jobs:
                    if self.stop_event.is_set():
                        break
                    # ── Mark task as "running" in Task Grid ──
                    grid_row = job.get("task_grid_row", job.get("prompt_idx", -1))
                    if grid_row >= 0:
                        self._flow_update_task_grid_status(grid_row, "running")
                    future = executor.submit(process_single_flow_job, job)
                    future_to_job[future] = job
                
                # Xử lý kết quả khi job hoàn thành
                for future in as_completed(future_to_job):
                    job = future_to_job[future]
                    grid_row = job.get("task_grid_row", job.get("prompt_idx", -1))
                    try:
                        result = future.result()
                        if result and result.get("success"):
                            success += 1
                            # ✅ Track status thành công vào job để retry chỉ chạy lại các prompt lỗi
                            job["status"] = "success"
                            job["image_path"] = result["image_path"]
                            self._flow_update_success_label(success)
                            image_path = result["image_path"]
                            self._flow_set_tile_image(job["tile_index"], image_path)
                            self._flow_update_tile_status(job["tile_index"], "✅ Tạo ảnh thành công")
                            # ── Mark task as "success" in Task Grid ──
                            if grid_row >= 0:
                                self._flow_update_task_grid_status(grid_row, "success")
                                # ── Update preview column ──
                                self._flow_update_task_grid_preview(grid_row, image_path)
                        else:
                            # ✅ Track status lỗi vào job để retry chỉ chạy lại các prompt lỗi
                            job["status"] = "failed"
                            self.log(f"❌ Flow job {job.get('tile_index', '?')} thất bại")
                            # ── Mark task as "error" in Task Grid ──
                            if grid_row >= 0:
                                err = result.get("error", "Không rõ lỗi") if result else "Không có kết quả"
                                self._flow_update_task_grid_status(grid_row, "error", str(err))
                    except Exception as e:
                        # ✅ Track status lỗi vào job để retry chỉ chạy lại các prompt lỗi
                        job["status"] = "failed"
                        self.log(f"❌ Flow job {job.get('tile_index', '?')} exception: {e}")
                        # ── Mark task as "error" in Task Grid ──
                        if grid_row >= 0:
                            self._flow_update_task_grid_status(grid_row, "error", str(e)[:200])
                    
                    completed += 1
                    self._flow_update_status_text(f"Đã xử lý {completed}/{total_jobs} ảnh Flow")
                    
                    if self.stop_event.is_set():
                        break
            
            # ✅ Code cũ đã được thay thế bằng round-robin multi-cookie ở trên

            # ✅ Thành công khi TẤT CẢ jobs thành công
            if success:
                batch_success = success == total_jobs
                if batch_success:
                    finish_msg = "Đã xử lý xong tất cả prompt Flow."
                    status_msg = "Hoàn tất"
                    if batch_context and batch_context.get("label"):
                        finish_msg = f"Đã xử lý xong file {batch_context['label']}."
                        status_msg = f"Hoàn tất {batch_context['label']}"
                    self._flow_finish(finish_msg)
                    self._flow_update_status_text(status_msg)
                else:
                    # Có ảnh thành công nhưng chưa đủ → coi là lỗi để user chạy lại file
                    self._flow_handle_error(f"Tạo được {success}/{total_jobs} ảnh, còn {total_jobs - success} ảnh lỗi.")
            else:
                self._flow_handle_error("Không tạo được ảnh nào, vui lòng kiểm tra log.")
        except Exception as e:
            self._flow_handle_error(str(e))
        finally:
            # Đảm bảo flow_is_running được set về False
            self.flow_is_running = False
            self._flow_worker_done(batch_success, batch_context)

    def _flow_retry_failed_worker(self, retry_context: Dict[str, Any]):
        """Worker thread để xử lý retry các prompt lỗi - chỉ chạy lại prompt bị lỗi, giữ nguyên tile_index và output_dir"""
        all_failed_jobs = retry_context.get("all_failed_jobs", [])
        file_to_jobs_mapping = retry_context.get("file_to_jobs_mapping", {})
        failed_files = retry_context.get("failed_files", [])
        model_code = retry_context.get("model_code", "GEM_PIX_2")
        aspect_ratio = retry_context.get("aspect_ratio", "IMAGE_ASPECT_RATIO_LANDSCAPE")
        reference_paths = retry_context.get("reference_paths", [])
        
        total_jobs = len(all_failed_jobs)
        success = 0
        completed = 0
        
        self.log(f"🔄 Retry worker bắt đầu: {total_jobs} prompt(s) lỗi")
        
        try:
            # Prepare cookies
            cookies_to_use = []
            if self.cookies_list:
                cookies_to_use = self.cookies_list.copy()
            elif self.cookie_value:
                cookies_to_use = [self.cookie_value]
            
            if not cookies_to_use:
                self._flow_handle_error("Không có cookie để retry!")
                return
            
            self.log(f"🍪 Sử dụng {len(cookies_to_use)} cookie(s) để retry")
            
            # ✅ Upload reference images (dùng lại cache nếu có) - upload cho từng cookie
            upload_results = {}
            for cookie in cookies_to_use:
                # ✅ Lấy reference paths từ job đầu tiên hoặc từ context
                # Nếu job có reference_paths riêng, sẽ upload riêng cho job đó
                if reference_paths:
                    result = self._flow_upload_references_for_cookie(cookie, reference_paths, model_code)
                    upload_results[cookie] = result
                else:
                    upload_results[cookie] = []
            
            # ✅ Xử lý từng job với round-robin cookies
            with ThreadPoolExecutor(max_workers=min(len(cookies_to_use), 4)) as executor:
                future_to_job = {}
                
                for i, job in enumerate(all_failed_jobs):
                    if self.stop_event.is_set():
                        break
                    
                    cookie = cookies_to_use[i % len(cookies_to_use)]
                    
                    # ✅ Lấy output_dir từ mapping - sử dụng file_stem đã lưu trong job
                    file_stem = job.get("file_stem")
                    
                    if file_stem and file_stem in self.flow_file_output_mapping:
                        output_dir = self.flow_file_output_mapping[file_stem]
                    else:
                        output_dir = self._get_flow_output_dir()
                    
                    # ✅ Reference paths cho job này - restore từ job hoặc dùng từ context
                    job_refs = job.get("reference_paths", reference_paths)
                    
                    # ✅ Nếu job có reference_paths riêng, upload riêng cho cookie này
                    if job_refs and job_refs != reference_paths:
                        # Upload riêng cho job này với cookie này
                        job_media_ids = self._flow_upload_references_for_cookie(cookie, job_refs, model_code)
                        media_ids = job_media_ids
                        self.log(f"🔄 Retry job {job.get('tile_index')}: Upload {len(job_refs)} reference images riêng (cookie {cookie[:20]}...)")
                    else:
                        # Dùng media IDs đã upload chung
                        media_ids = upload_results.get(cookie, [])
                    
                    # Update tile status
                    tile_index = job.get("tile_index")
                    if tile_index is not None:
                        self._flow_update_tile_status(tile_index, "🔄 Đang retry…")
                    
                    # Submit job
                    future = executor.submit(
                        self._flow_process_single_job,
                        job,
                        cookie,
                        media_ids,
                        model_code,
                        aspect_ratio,
                        output_dir,
                    )
                    future_to_job[future] = job
                
                # Thu thập kết quả
                for future in as_completed(future_to_job):
                    job = future_to_job[future]
                    tile_index = job.get("tile_index")
                    file_stem = job.get("file_stem")
                    try:
                        result = future.result()
                        if result and result.get("success"):
                            success += 1
                            # Update job copy status
                            job["status"] = "success"
                            job["image_path"] = result["image_path"]
                            
                            # ✅ QUAN TRỌNG: Sync status về job gốc trong mapping
                            if file_stem and tile_index is not None:
                                original_jobs = self.flow_file_job_mapping.get(file_stem, [])
                                for orig_job in original_jobs:
                                    if orig_job.get("tile_index") == tile_index:
                                        orig_job["status"] = "success"
                                        orig_job["image_path"] = result["image_path"]
                                        break
                            
                            self._flow_update_success_label(success)
                            self._flow_set_tile_image(tile_index, result["image_path"])
                            self._flow_update_tile_status(tile_index, "✅ Retry thành công")
                        else:
                            job["status"] = "failed"
                            self.log(f"❌ Retry job {tile_index} vẫn lỗi")
                            self._flow_update_tile_status(tile_index, "❌ Retry thất bại")
                    except Exception as e:
                        job["status"] = "failed"
                        self.log(f"❌ Retry job {tile_index} exception: {e}")
                    
                    completed += 1
                    self._flow_update_status_text(f"Retry: {completed}/{total_jobs} ({success} thành công)")
                    
                    if self.stop_event.is_set():
                        break
            
            # ✅ Kiểm tra kết quả
            if success == total_jobs:
                self._flow_finish(f"Retry thành công tất cả {total_jobs} prompt!")
                # Clear failed files vì đã retry thành công hết
                self.flow_failed_files = []
            elif success > 0:
                remaining = total_jobs - success
                self._flow_handle_error(f"Retry: {success}/{total_jobs} thành công, còn {remaining} lỗi")
            else:
                self._flow_handle_error("Retry thất bại tất cả, vui lòng kiểm tra log.")
                
        except Exception as e:
            self._flow_handle_error(f"Retry error: {e}")
        finally:
            self.flow_is_running = False
            self.flow_batch_active = False
            self.flow_batch_queue = []
            
            # Enable buttons
            self._flow_enable_run_button(True)
            if hasattr(self, "btn_flow_retry_failed"):
                # Kiểm tra còn failed files không
                remaining_failed = self._check_flow_failed_files_from_table()
                if remaining_failed:
                    self.btn_flow_retry_failed.setEnabled(True)
                    self.log(f"⚠️ Còn {len(remaining_failed)} file(s) có prompt lỗi")
                else:
                    self.btn_flow_retry_failed.setEnabled(False)
            
            # Update batch table status
            for file_path in failed_files:
                file_stem = file_path.stem
                jobs = self.flow_file_job_mapping.get(file_stem, [])
                failed_count = sum(1 for j in jobs if j.get("status") != "success")
                total_count = len(jobs)
                
                if failed_count == 0:
                    self._update_flow_batch_status(file_path, "✅ Hoàn tất")
                else:
                    self._update_flow_batch_status(file_path, f"❌ Còn {failed_count}/{total_count} lỗi")

    def _check_flow_failed_files_from_table(self) -> List[Path]:
        """Kiểm tra còn files nào có prompt lỗi dựa trên flow_file_job_mapping"""
        failed_files = []
        
        # Duyệt qua tất cả files trong table
        for row in range(self.flow_batch_table.rowCount()):
            file_item = self.flow_batch_table.item(row, 0)
            data = file_item.data(Qt.ItemDataRole.UserRole) if file_item else None

            # Nếu UserRole chưa được gán (dữ liệu cũ), fallback sang cột tên file
            if not data:
                name_item = self.flow_batch_table.item(row, 1)
                file_name = name_item.text().strip() if name_item else ""
                for p in getattr(self, "flow_batch_files", []):
                    if p.name == file_name:
                        data = str(p)
                        break

            if not data:
                continue
            
            file_path = Path(data)
            file_stem = file_path.stem
            
            # Kiểm tra trong job mapping
            jobs = self.flow_file_job_mapping.get(file_stem, [])
            if jobs:
                # Có job nào chưa success không?
                has_failed = any(j.get("status") != "success" for j in jobs)
                if has_failed:
                    failed_files.append(file_path)
        
        return failed_files

    def on_flow_add_reference(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn ảnh tham chiếu",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)"
        )
        if files:
            self.flow_reference_paths.extend(files)
            self.refresh_flow_reference_list()
            self.log(f"🖼️ Flow references: {len(self.flow_reference_paths)} file(s)")

    def on_flow_clear_reference(self):
        if not self.flow_reference_paths:
            return
        self.flow_reference_paths = []
        self.refresh_flow_reference_list()
        self.log("🧹 Đã xóa danh sách ảnh tham chiếu Flow")

    def on_flow_mode_change(self):
        """Switch between Normal, Multiple-to-Image, and Folder-Structure modes for Flow"""
        if self.rb_flow_normal.isChecked():
            self.current_flow_mode = "Normal"
            self.flow_ref_normal_card.setVisible(False)
            self.flow_ref_multiple_card.setVisible(False)
            self.flow_ref_folder_structure_card.setVisible(False)
            # ✅ Hiện lại nguồn prompt khi chọn mode Thường
            if hasattr(self, 'flow_source_card'):
                self.flow_source_card.setVisible(True)
        elif self.rb_flow_multiple.isChecked():
            self.current_flow_mode = "Multiple-to-Image"
            self.flow_ref_normal_card.setVisible(False)
            self.flow_ref_multiple_card.setVisible(True)
            self.flow_ref_folder_structure_card.setVisible(False)
            # ✅ Hiện nguồn prompt cho mode Multiple
            if hasattr(self, 'flow_source_card'):
                self.flow_source_card.setVisible(True)
        elif self.rb_flow_folder_structure.isChecked():
            self.current_flow_mode = "Folder-Structure"
            self.flow_ref_normal_card.setVisible(False)
            self.flow_ref_multiple_card.setVisible(False)
            self.flow_ref_folder_structure_card.setVisible(True)
            # ✅ ẨN nguồn prompt khi chọn Folder Structure (vì prompt nằm trong folder con)
            if hasattr(self, 'flow_source_card'):
                self.flow_source_card.setVisible(False)
        self.log(f"Flow mode: {self.current_flow_mode}")

    def browse_flow_subject_folder(self):
        """Browse folder chứa ảnh Subject cho Flow Multiple-to-Image"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa ảnh Subject"
        )
        if folder_path:
            self.flow_subject_folder.setText(folder_path)
            # Count images
            image_exts = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']
            images = []
            for ext in image_exts:
                images.extend(Path(folder_path).glob(ext))
            images = natural_sort_paths(images)
            self.log(f"📁 Flow Subject folder: {Path(folder_path).name} ({len(images)} ảnh)")

    def browse_flow_scene_folder(self):
        """Browse folder chứa ảnh Scene cho Flow Multiple-to-Image"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa ảnh Scene"
        )
        if folder_path:
            self.flow_scene_folder.setText(folder_path)
            # Count images
            image_exts = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']
            images = []
            for ext in image_exts:
                images.extend(Path(folder_path).glob(ext))
            images = natural_sort_paths(images)
            self.log(f"📁 Flow Scene folder: {Path(folder_path).name} ({len(images)} ảnh)")

    def browse_flow_style_folder(self):
        """Browse folder chứa ảnh Style cho Flow Multiple-to-Image"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa ảnh Style"
        )
        if folder_path:
            self.flow_style_folder.setText(folder_path)
            # Count images
            image_exts = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']
            images = []
            for ext in image_exts:
                images.extend(Path(folder_path).glob(ext))
            images = natural_sort_paths(images)
            self.log(f"📁 Flow Style folder: {Path(folder_path).name} ({len(images)} ảnh)")

    def browse_flow_folder_structure(self):
        """Browse folder cha cho Flow Folder Structure mode"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Chọn folder cha chứa các folder con"
        )
        if not folder_path:
            return
        
        # ✅ Clear toàn bộ state trước khi load folder structure mới
        self._clear_flow_batch_state()
        
        # ✅ Validate: Clear file/folder txt inputs khi chọn folder structure
        if hasattr(self, "flow_prompt_file_input"):
            self.flow_prompt_file_input.clear()
        if hasattr(self, "flow_prompt_folder_input"):
            self.flow_prompt_folder_input.clear()
        
            self.flow_folder_structure_path = Path(folder_path)
            self.flow_folder_structure_input.setText(folder_path)
            self._scan_folder_structure_subfolders()
            self.log(f"📁 Flow Folder Structure: {self.flow_folder_structure_path.name}")

    def _scan_folder_structure_subfolders(self):
        """Quét các file .txt và folder cùng tên trong folder cha, tự động map"""
        if not self.flow_folder_structure_path or not self.flow_folder_structure_path.exists():
            return
        
        self.flow_folder_structure_subfolders = []
        table = self.flow_folder_structure_table
        table.setRowCount(0)
        
        # ✅ LOGIC MỚI: Tìm tất cả file .txt trong folder cha
        txt_files = sorted(self.flow_folder_structure_path.glob("*.txt"))
        self.log(f"🔍 Bắt đầu scan {len(txt_files)} file .txt trong {self.flow_folder_structure_path.name}")
        
        # Lấy danh sách tất cả folder trong folder cha
        all_folders = {f.name: f for f in self.flow_folder_structure_path.iterdir() if f.is_dir()}
        
        def normalize_name(name: str) -> str:
            """Normalize tên để so sánh: bỏ extension, khoảng trắng, lowercase"""
            # Bỏ extension nếu có
            name = Path(name).stem
            # Bỏ khoảng trắng, lowercase
            return name.replace(" ", "").replace("_", "").lower()
        
        # Với mỗi file .txt, tìm folder cùng tên
        for txt_file in txt_files:
            txt_name = txt_file.stem  # Tên file không có extension (ví dụ: "1.txt" → "1")
            self.log(f"🔍 Đang tìm folder cho file: {txt_file.name}")
            
            # Tìm folder có tên tương ứng
            matched_folder = None
            normalized_txt = normalize_name(txt_name)
            
            # Thử match với các pattern:
            # 1. Tên chính xác: "1.txt" → "1" hoặc "folder 1" hoặc "folder1"
            # 2. Tên có prefix "folder": "1.txt" → "folder 1" hoặc "folder1"
            # 3. Tên có prefix khác: "1.txt" → "1_images", "1_refs", etc.
            
            for folder_name, folder_path in all_folders.items():
                normalized_folder = normalize_name(folder_name)
                
                # Match chính xác
                if normalized_folder == normalized_txt:
                    matched_folder = folder_path
                    self.log(f"   ✅ Tìm thấy folder khớp: {folder_name}")
                    break
                
                # Match với pattern "folder{name}" hoặc "{name}folder"
                if normalized_folder == f"folder{normalized_txt}" or normalized_folder == f"{normalized_txt}folder":
                    matched_folder = folder_path
                    self.log(f"   ✅ Tìm thấy folder khớp (pattern): {folder_name}")
                    break
            
            if not matched_folder:
                self.log(f"   ⚠️ Không tìm thấy folder cho '{txt_file.name}', bỏ qua")
                continue
            
            # Đếm số ảnh trong folder (tìm trực tiếp trong folder, không cần folder con)
            image_exts = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.gif', '*.webp']
            images = []
            for ext in image_exts:
                images.extend(matched_folder.glob(ext))
            images = natural_sort_paths(images)
            
            if not images:
                self.log(f"   ⚠️ Folder '{matched_folder.name}' không có ảnh hợp lệ, bỏ qua")
                continue
            
            # Đọc prompts từ file .txt
            prompts = self._load_prompts_from_file(txt_file)
            
            if not prompts:
                self.log(f"   ⚠️ File '{txt_file.name}' không có prompt hợp lệ, bỏ qua")
                continue
            
            # Log để debug
            self.log(f"✅ Map thành công: {txt_file.name} ↔ {matched_folder.name}")
            self.log(f"   - Folder ảnh: {matched_folder.name}, {len(images)} ảnh")
            self.log(f"   - File prompts: {txt_file.name}, {len(prompts)} prompts")
            
            # ✅ Lưu thông tin (path là folder cha, image_folder là folder ảnh đã match)
            subfolder_info = {
                "path": self.flow_folder_structure_path,  # Folder cha
                "image_folder": matched_folder,  # Folder ảnh đã match
                "txt_file": txt_file,  # File .txt
                "images": images,  # Danh sách ảnh
                "prompts": prompts,  # Danh sách prompts
                "num_images": len(images),
                "num_prompts": len(prompts),
                "pair_name": txt_name,  # Tên cặp (để hiển thị)
            }
            self.flow_folder_structure_subfolders.append(subfolder_info)
            
            # Thêm vào table
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            # Hiển thị tên cặp (ví dụ: "1.txt ↔ folder 1")
            pair_display = f"{txt_file.name} ↔ {matched_folder.name}"
            table.setItem(row, 1, QTableWidgetItem(pair_display))
            table.setItem(row, 2, QTableWidgetItem(str(len(images))))
            table.setItem(row, 3, QTableWidgetItem(str(len(prompts))))
        
        if self.flow_folder_structure_subfolders:
            self.log(f"📋 Flow Folder Structure: Phát hiện {len(self.flow_folder_structure_subfolders)} cặp file .txt ↔ folder hợp lệ")
        else:
            self.log(f"⚠️ Flow Folder Structure: Không tìm thấy cặp file .txt ↔ folder hợp lệ")

    def _map_prompt_to_images(self, prompt: str, images: List[Path], default_count: int = 3) -> List[Path]:
        """
        Map prompt với ảnh dựa trên tên file.
        - Tìm các từ trong prompt match với tên file ảnh (bỏ extension)
        - Nếu có match → dùng ảnh đó
        - Nếu không có match → fallback lấy ảnh theo thứ tự natural sort (mặc định 3 ảnh đầu)
        
        Args:
            prompt: Text prompt
            images: Danh sách ảnh (đã sort natural)
            default_count: Số ảnh mặc định nếu không có match
        
        Returns:
            Danh sách ảnh đã map
        """
        if not images:
            return []
        
        # Normalize prompt: lowercase, bỏ dấu câu
        import re
        prompt_normalized = prompt.lower()
        # Bỏ các ký tự đặc biệt, chỉ giữ chữ và số
        prompt_words = re.findall(r'\b\w+\b', prompt_normalized)
        
        # Tạo dict: tên file (normalized) -> Path
        image_name_map = {}
        for img in images:
            img_name_normalized = img.stem.lower().strip()
            image_name_map[img_name_normalized] = img
        
        # Tìm ảnh match với các từ trong prompt
        matched_images = []
        used_names = set()
        
        for word in prompt_words:
            # Bỏ qua từ quá ngắn (1-2 ký tự)
            if len(word) < 3:
                continue
            
            # Tìm exact match
            if word in image_name_map and word not in used_names:
                matched_images.append(image_name_map[word])
                used_names.add(word)
                continue
            
            # Tìm partial match (tên file chứa từ này hoặc ngược lại)
            for img_name, img_path in image_name_map.items():
                if img_name in used_names:
                    continue
                # Check nếu từ nằm trong tên file hoặc tên file nằm trong từ
                if word in img_name or img_name in word:
                    matched_images.append(img_path)
                    used_names.add(img_name)
                    break
        
        # Nếu có match → trả về ảnh đã match
        if matched_images:
            return matched_images
        
        # Fallback: lấy ảnh theo thứ tự natural sort (mặc định 3 ảnh đầu)
        return images[:default_count]

    def update_flow_result_tiles(self, prompts: List[str], variants: int, base_seed: Optional[int], folder_label: Optional[str] = None, batch_context: Optional[Dict[str, Any]] = None, task_grid_rows: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        jobs = self._build_flow_jobs(prompts, variants, base_seed, task_grid_rows=task_grid_rows)
        
        # ✅ LOGIC MỚI: Map prompt với ảnh ngay khi tạo jobs cho Folder-Structure mode
        if batch_context and batch_context.get("mode") == "Folder-Structure":
            all_images = batch_context.get("all_images", [])
            if all_images:
                for job in jobs:
                    prompt_text = job.get("prompt", "").strip()
                    if prompt_text:
                        mapped_images = self._map_prompt_to_images(prompt_text, all_images, default_count=3)
                        # ✅ Lưu reference_paths vào job để hiển thị trên card
                        job["reference_paths"] = [str(img.resolve()) for img in mapped_images]
        
        self._prepare_flow_result_rows(jobs, folder_label or "Run")
        return jobs

    def on_flow_run_clicked(self):
        self.log(f"🔘 Flow run button clicked - flow_is_running={self.flow_is_running}, flow_batch_active={self.flow_batch_active}")
        
        if self.flow_is_running or self.flow_batch_active:
            QMessageBox.information(self, "Flow đang chạy", "Đang có một lượt tạo ảnh Flow khác, vui lòng đợi hoàn tất.")
            return
        
        if not (self.cookie_value or self.cookies_list):
            QMessageBox.warning(self, "Thiếu cookie", "Vui lòng nhập cookie tại tab Video trước khi chạy Flow.")
            return
        
        # ✅ Reset stop_event khi bắt đầu flow mới
        if hasattr(self, 'stop_event'):
            self.stop_event.clear()
            self.log("🔄 Đã reset stop_event - sẵn sàng tạo ảnh mới")

        self.log(f"🔍 Flow mode: {self.current_flow_mode}, batch_files: {len(self.flow_batch_files) if hasattr(self, 'flow_batch_files') else 0}")
        
        self.update_flow_prompt_count()
        self._flow_switch_to_table_view()
        self._flow_toggle_folder_controls(True)
        # ✅ Reset table và tiles khi bắt đầu run mới (chỉ reset ở đây, không reset trong _prepare_flow_result_rows)
        if hasattr(self, "flow_result_table"):
            self.flow_result_table.setRowCount(0)
            # Ẩn table, chỉ dùng grid
            self.flow_result_table.setVisible(False)
        # Xóa các card cũ trong grid
        self._flow_clear_result_grid()
        # Reset tiles và counters khi bắt đầu run mới
        if hasattr(self, "flow_result_tiles"):
            self.flow_result_tiles = []
        if hasattr(self, "flow_active_jobs"):
            self.flow_active_jobs = []
        self.flow_results_success = 0
        self.flow_results_total = 0
        self.flow_folder_results = {}
        self.flow_current_folder_view = None
        # ✅ Disable nút retry ngay khi bắt đầu run mới - chỉ enable sau khi TẤT CẢ batch hoàn tất
        if hasattr(self, "btn_flow_retry_failed"):
            self.btn_flow_retry_failed.setEnabled(False)
        variants = self.flow_variations_spin.value() if hasattr(self, "flow_variations_spin") else 1
        model_code = self.flow_model_combo.currentData() if hasattr(self, "flow_model_combo") else "GEM_PIX_2"
        aspect_ratio = self.flow_aspect_combo.currentData() if hasattr(self, "flow_aspect_combo") else "IMAGE_ASPECT_RATIO_LANDSCAPE"
        reference_paths = list(self.flow_reference_paths)
        output_dir = self._get_flow_output_dir()

        # Folder Structure mode
        if self.current_flow_mode == "Folder-Structure":
            if not self.flow_folder_structure_path or not self.flow_folder_structure_path.exists():
                QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng chọn folder cha cho Folder Structure mode.")
                return
            
            if not self.flow_folder_structure_subfolders:
                QMessageBox.warning(self, "Thiếu dữ liệu", "Không tìm thấy folder con hợp lệ. Mỗi folder con cần có folder 'image' và file .txt.")
                return
            
            self.flow_folder_results = {}
            self.flow_current_folder_view = None
            self._flow_update_folder_selector()
            self._flow_toggle_folder_controls(True)
            if hasattr(self, "flow_result_table"):
                self.flow_result_table.setRowCount(0)
                self.flow_result_table.setVisible(True)
            
            self.flow_batch_queue = list(range(len(self.flow_folder_structure_subfolders)))
            self.flow_batch_params = {
                "variants": variants,
                "model_code": model_code,
                "aspect_ratio": aspect_ratio,
                "reference_paths": [],
                "output_root": None,
                "mode": "Folder-Structure",
            }
            self.flow_batch_active = True
            self._flow_enable_run_button(False)
            self._flow_update_status_text("Đang chuẩn bị Folder Structure Flow…")
            self._flow_update_hint_text(f"Hệ thống sẽ xử lý {len(self.flow_batch_queue)} folder con lần lượt.")
            self.log(f"📁 Flow Folder Structure start: {len(self.flow_batch_queue)} folder con")
            self._start_next_flow_batch()
            return

        # ✅ Batch mode: nhiều file .txt (folder chứa nhiều file)
        if self.flow_batch_files and len(self.flow_batch_files) > 1:
            self.flow_batch_queue = [Path(p) for p in self.flow_batch_files]
            self.flow_batch_params = {
                "variants": variants,
                "model_code": model_code,
                "aspect_ratio": aspect_ratio,
                "reference_paths": reference_paths,
                "output_root": output_dir,
            }
            self.flow_batch_active = True
            self._flow_enable_run_button(False)
            self._flow_update_status_text("Đang chuẩn bị batch Flow…")
            self._flow_update_hint_text("Hệ thống sẽ xử lý từng file .txt lần lượt.")
            self.log(f"📁 Flow batch start: {len(self.flow_batch_queue)} file .txt")
            self._start_next_flow_batch()
            return

        # ✅ Normal/Single-file mode: Lấy prompts từ Task Grid (đã populate khi load TXT)
        if not hasattr(self, "flow_tasks") or not self.flow_tasks:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng chọn file .txt để load prompt vào bảng trước khi chạy.")
            return

        # Collect prompts và reference images từ flow_tasks
        prompts = [t.prompt for t in self.flow_tasks if t.prompt.strip()]
        if not prompts:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Không có prompt hợp lệ trong bảng.")
            return

        # ✅ Lấy reference images từ từng task (user có thể đã thêm ảnh riêng cho mỗi task)
        # Nếu task có ảnh riêng, dùng ảnh đó; nếu không, dùng ảnh chung từ left panel
        task_has_individual_refs = any(t.reference_images for t in self.flow_tasks)
        if not task_has_individual_refs:
            # Dùng ảnh chung từ left panel cho tất cả tasks
            for t in self.flow_tasks:
                t.reference_images = list(reference_paths)

        base_seed = self.flow_tasks[0].seed if self.flow_tasks else random.randint(1, 999999)
        self.flow_last_seed = base_seed

        # ✅ Xác định output_dir: lưu vào folder cùng tên file .txt
        if hasattr(self, "flow_current_txt_file") and self.flow_current_txt_file:
            file_stem = self.flow_current_txt_file.stem
            output_dir = output_dir / file_stem
            output_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"📁 Output dir: {output_dir} (theo tên file {file_stem}.txt)")

        # ✅ Lock grid khi bắt đầu chạy
        self._flow_lock_grid(True)

        # Reset task statuses to pending
        for i, t in enumerate(self.flow_tasks):
            t.status = "pending"
            self._flow_update_task_grid_status_slot(i, "pending", "")

        self.log(f"🚀 Flow run: {len(prompts)} prompt(s) từ grid, refs per task")
        
        # Build batch_context nếu có file
        batch_context = None
        if hasattr(self, "flow_current_txt_file") and self.flow_current_txt_file:
            batch_context = {
                "file_path": self.flow_current_txt_file,
                "label": self.flow_current_txt_file.name,
                "total_prompts": len(prompts),
            }

        self._start_flow_generation(
            prompts,
            variants,
            model_code,
            aspect_ratio,
            reference_paths,
            output_dir,
            base_seed,
            batch_context=batch_context,
        )

    def _flow_create_tasks_from_prompts(self, prompts, model_code, aspect_ratio, reference_paths, base_seed):
        """Parse prompts và tạo FlowTaskData + Task_Row trong flow_task_grid."""
        # Clear existing tasks
        self.flow_tasks.clear()
        self.flow_task_grid.setRowCount(0)

        # Model display name mapping
        model_names = {"NARWHAL": "Banana Pro 2", "GEM_PIX_2": "Banana Pro", "GEM_PIX": "Gem Pix", "IMAGEN_3_5": "Imagen 4"}
        model_display = model_names.get(model_code, model_code)

        # Aspect display
        aspect_names = {
            "IMAGE_ASPECT_RATIO_LANDSCAPE": "16:9",
            "IMAGE_ASPECT_RATIO_PORTRAIT": "9:16",
            "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE": "4:3",
            "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR": "3:4",
            "IMAGE_ASPECT_RATIO_SQUARE": "1:1"
        }
        aspect_display = aspect_names.get(aspect_ratio, "16:9")

        for i, prompt in enumerate(prompts):
            prompt = prompt.strip()
            if not prompt:
                continue
            idx = len(self.flow_tasks) + 1
            task = FlowTaskData(
                index=idx,
                prompt=prompt,
                model_code=model_code,
                aspect_ratio=aspect_ratio,
                seed=base_seed + i,
                reference_images=list(reference_paths),
                status="pending",
            )
            self.flow_tasks.append(task)

            # Add row to grid
            row = self.flow_task_grid.rowCount()
            self.flow_task_grid.insertRow(row)

            # Col 0: # (index)
            stt_item = QTableWidgetItem(str(idx))
            stt_item.setTextAlignment(Qt.AlignCenter)
            stt_item.setForeground(QColor("#64748b"))
            self.flow_task_grid.setItem(row, 0, stt_item)

            # Col 1: Trạng thái (model + aspect + status)
            status_label = f"{model_display} | {aspect_display}"
            status_item = QTableWidgetItem(status_label)
            status_item.setForeground(QColor("#475569"))
            self.flow_task_grid.setItem(row, 1, status_item)

            # Thumbnail grid
            thumb = ThumbnailGridWidget(row, max_images=15, thumbnail_size=40, columns=5)
            if reference_paths:
                thumb.add_images(list(reference_paths))
            thumb.images_changed.connect(self._on_flow_thumbnail_changed)
            thumb.height_hint_changed.connect(self._on_flow_thumbnail_height_changed)
            self.flow_task_grid.setCellWidget(row, 2, thumb)
            self.flow_task_grid.setRowHeight(row, max(64, thumb.minimumHeight() + 10))

            # Col 3: Preview (ảnh đã tạo) - placeholder widget
            preview_label = QLabel("Chờ...")
            preview_label.setAlignment(Qt.AlignCenter)
            preview_label.setStyleSheet("""
                QLabel {
                    background: #f1f5f9;
                    border-radius: 8px;
                    color: #94a3b8;
                    font-size: 11px;
                }
            """)
            preview_label.setFixedSize(80, 56)
            preview_label.setProperty("row_index", row)
            preview_label.setProperty("preview_type", "task_grid")
            self.flow_task_grid.setCellWidget(row, 3, preview_label)
            # Lưu reference để cập nhật sau
            if not hasattr(self, "flow_task_preview_widgets"):
                self.flow_task_preview_widgets = {}
            self.flow_task_preview_widgets[row] = preview_label

            # Prompt (Col 4)
            prompt_item = QTableWidgetItem(prompt)
            prompt_item.setToolTip(prompt)
            self.flow_task_grid.setItem(row, 4, prompt_item)

            # Col 5: Status (trạng thái chi tiết)
            status_detail_item = QTableWidgetItem("⏸ Chờ chạy")
            status_detail_item.setForeground(QColor("#94a3b8"))
            self.flow_task_grid.setItem(row, 5, status_detail_item)

        self._flow_update_summary_bar()

    def _on_flow_thumbnail_changed(self, row_index, image_paths):
        """Callback khi thumbnail thay đổi - cập nhật FlowTaskData."""
        if 0 <= row_index < len(self.flow_tasks):
            self.flow_tasks[row_index].reference_images = list(image_paths)
        if hasattr(self, "flow_task_grid") and 0 <= row_index < self.flow_task_grid.rowCount():
            thumb = self.flow_task_grid.cellWidget(row_index, 2)
            if isinstance(thumb, ThumbnailGridWidget):
                self.flow_task_grid.setRowHeight(row_index, max(64, thumb.minimumHeight() + 10))

    def _on_flow_thumbnail_height_changed(self, row_index: int, suggested_height: int):
        if hasattr(self, "flow_task_grid") and 0 <= row_index < self.flow_task_grid.rowCount():
            self.flow_task_grid.setRowHeight(row_index, max(64, suggested_height + 10))

    def _flow_update_summary_bar(self):
        """Cập nhật summary status bar dựa trên flow_tasks."""
        total = len(self.flow_tasks)
        running = sum(1 for t in self.flow_tasks if t.status == "running")
        success = sum(1 for t in self.flow_tasks if t.status == "success")
        error = sum(1 for t in self.flow_tasks if t.status == "error")
        self.flow_status_total.setText(f"Tổng: {total}")
        self.flow_status_running.setText(f"Đang chạy: {running}")
        self.flow_status_success.setText(f"Thành công: {success}")
        self.flow_status_error.setText(f"Lỗi: {error}")

    def _flow_lock_grid(self, locked: bool):
        """Lock/unlock toàn bộ grid khi đang chạy: disable thêm ảnh, xóa, sửa."""
        if hasattr(self, "flow_task_grid"):
            # Lock all thumbnail widgets
            for i in range(self.flow_task_grid.rowCount()):
                thumb = self.flow_task_grid.cellWidget(i, 2)
                if isinstance(thumb, ThumbnailGridWidget):
                    thumb.set_locked(locked)
        # Lock/unlock toolbar buttons
        if hasattr(self, "btn_add_images"):
            self.btn_add_images.setEnabled(not locked)
        if hasattr(self, "btn_delete_selected"):
            self.btn_delete_selected.setEnabled(not locked)
        if hasattr(self, "btn_delete_all"):
            self.btn_delete_all.setEnabled(not locked)
        if hasattr(self, "btn_import_images_all"):
            self.btn_import_images_all.setEnabled(not locked)
        if hasattr(self, "btn_clear_images_all"):
            self.btn_clear_images_all.setEnabled(not locked)

    def _flow_reindex_stt(self):
        """Re-index STT column sau khi xóa rows."""
        for i in range(self.flow_task_grid.rowCount()):
            item = self.flow_task_grid.item(i, 0)
            if item:
                item.setText(str(i + 1))
            if i < len(self.flow_tasks):
                self.flow_tasks[i].index = i + 1

    def _on_flow_delete_selected(self):
        """Xóa selected rows, re-index STT."""
        selected = self.flow_task_grid.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, "Thông báo", "Chưa chọn task nào.")
            return
        rows = sorted([idx.row() for idx in selected], reverse=True)
        for row in rows:
            self.flow_task_grid.removeRow(row)
            if row < len(self.flow_tasks):
                self.flow_tasks.pop(row)
        self._flow_reindex_stt()
        # Update thumbnail row_index references
        for i in range(self.flow_task_grid.rowCount()):
            w = self.flow_task_grid.cellWidget(i, 2)
            if isinstance(w, ThumbnailGridWidget):
                w.row_index = i
        self._flow_update_summary_bar()

    def _on_flow_delete_all(self):
        """Xóa hết tasks sau khi confirm."""
        if self.flow_task_grid.rowCount() == 0:
            return
        reply = QMessageBox.question(
            self, "Xác nhận", "Bạn có chắc muốn xóa tất cả task?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.flow_task_grid.setRowCount(0)
            self.flow_tasks.clear()
            self._flow_update_summary_bar()

    def _on_flow_add_images(self):
        """Thêm ảnh tham chiếu vào selected tasks."""
        selected = self.flow_task_grid.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, "Thông báo", "Chưa chọn task nào.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh tham chiếu", "",
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if not files:
            return
        for idx in selected:
            row = idx.row()
            w = self.flow_task_grid.cellWidget(row, 2)
            if isinstance(w, ThumbnailGridWidget):
                w.add_images(files)

    def _on_flow_import_images_all(self):
        """Import ảnh tham chiếu cho TẤT CẢ tasks trong grid."""
        if self.flow_task_grid.rowCount() == 0:
            QMessageBox.information(self, "Thông báo", "Chưa có task nào trong bảng.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh tham chiếu cho tất cả prompt", "",
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if not files:
            return
        count = 0
        for row in range(self.flow_task_grid.rowCount()):
            w = self.flow_task_grid.cellWidget(row, 2)
            if isinstance(w, ThumbnailGridWidget):
                w.add_images(files)
                count += 1
        self.log(f"📷 Đã import {len(files)} ảnh cho {count} task(s)")

    def _on_flow_clear_images_all(self):
        """Xóa tất cả ảnh tham chiếu khỏi TẤT CẢ tasks trong grid."""
        if self.flow_task_grid.rowCount() == 0:
            return
        reply = QMessageBox.question(
            self, "Xác nhận", "Bạn có chắc muốn xóa ảnh tham chiếu của tất cả prompt?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        count = 0
        for row in range(self.flow_task_grid.rowCount()):
            w = self.flow_task_grid.cellWidget(row, 2)
            if isinstance(w, ThumbnailGridWidget):
                w.image_paths.clear()
                w._rebuild_layout()
                w.images_changed.emit(w.row_index, [])
                count += 1
        self.log(f"🗑 Đã xóa ảnh tham chiếu của {count} task(s)")

    def _on_flow_run_selected(self):
        """Chạy chỉ selected tasks."""
        selected = self.flow_task_grid.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(self, "Thông báo", "Chưa chọn task nào.")
            return
        if self.flow_is_running or self.flow_batch_active:
            QMessageBox.information(self, "Flow đang chạy", "Đang có một lượt tạo ảnh Flow khác, vui lòng đợi hoàn tất.")
            return
        rows = sorted([idx.row() for idx in selected])
        prompts = []
        for row in rows:
            if row < len(self.flow_tasks):
                self.flow_tasks[row].status = "pending"
                prompts.append(self.flow_tasks[row].prompt)
                # Visually reset row to pending
                self._flow_update_task_grid_status_slot(row, "pending", "")
        if not prompts:
            return
        variants = self.flow_variations_spin.value() if hasattr(self, "flow_variations_spin") else 1
        model_code = self.flow_model_combo.currentData() if hasattr(self, "flow_model_combo") else "GEM_PIX_2"
        aspect_ratio = self.flow_aspect_combo.currentData() if hasattr(self, "flow_aspect_combo") else "IMAGE_ASPECT_RATIO_LANDSCAPE"
        reference_paths = list(self.flow_reference_paths)
        output_dir = self._get_flow_output_dir()
        base_seed = random.randint(1, 999999)
        self.log(f"🚀 Flow run selected: {len(prompts)} task(s) (rows: {rows})")
        self._start_flow_generation(prompts, variants, model_code, aspect_ratio, reference_paths, output_dir, base_seed, task_grid_rows=rows)

    def _on_flow_retry_failed(self):
        """Chạy lại chỉ tasks có status 'error'."""
        error_tasks = [t for t in self.flow_tasks if t.status == "error"]
        if not error_tasks:
            QMessageBox.information(self, "Thông báo", "Không có task lỗi nào để chạy lại.")
            return
        if self.flow_is_running or self.flow_batch_active:
            QMessageBox.information(self, "Flow đang chạy", "Đang có một lượt tạo ảnh Flow khác, vui lòng đợi hoàn tất.")
            return
        prompts = []
        rows = []
        for i, t in enumerate(self.flow_tasks):
            if t.status == "error":
                t.status = "pending"
                prompts.append(t.prompt)
                rows.append(i)
                # Visually reset row to pending
                self._flow_update_task_grid_status_slot(i, "pending", "")
        self._flow_update_summary_bar()
        variants = self.flow_variations_spin.value() if hasattr(self, "flow_variations_spin") else 1
        model_code = self.flow_model_combo.currentData() if hasattr(self, "flow_model_combo") else "GEM_PIX_2"
        aspect_ratio = self.flow_aspect_combo.currentData() if hasattr(self, "flow_aspect_combo") else "IMAGE_ASPECT_RATIO_LANDSCAPE"
        reference_paths = list(self.flow_reference_paths)
        output_dir = self._get_flow_output_dir()
        base_seed = random.randint(1, 999999)
        self.log(f"🔄 Flow retry failed: {len(prompts)} task(s) (rows: {rows})")
        self._start_flow_generation(prompts, variants, model_code, aspect_ratio, reference_paths, output_dir, base_seed, task_grid_rows=rows)

    def _is_flow_high_quality_mode(self):
        """Banana Pro 2K/4K chạy nặng hơn nên chỉ dùng 1 concurrent mỗi cookie."""
        if not hasattr(self, "flow_upsample_combo") or not self.flow_upsample_combo:
            return False
        choice = self.flow_upsample_combo.currentData()
        return choice in ("UPSAMPLE_IMAGE_RESOLUTION_2K", "UPSAMPLE_IMAGE_RESOLUTION_4K")

    def _get_flow_concurrency_per_cookie(self):
        return max(1, int(self.get_threads_per_cookie_limit(default=1, force_refresh=True)))

    def update_flow_concurrent_range(self):
        """Cập nhật range của flow_concurrent_spin theo số cookies và chất lượng Banana Pro."""
        if not hasattr(self, "flow_concurrent_spin"):
            return
        
        # Đếm số cookies
        num_cookies = 0
        if self.cookies_list:
            num_cookies = len(self.cookies_list)
        elif self.cookie_value:
            num_cookies = 1
        
        per_cookie_concurrent = self._get_flow_concurrency_per_cookie()
        max_concurrent = num_cookies * per_cookie_concurrent
        if max_concurrent < 1:
            max_concurrent = 1
        elif max_concurrent > 30:  # Giới hạn tối đa
            max_concurrent = 30
        
        # Cập nhật range và value
        current_value = self.flow_concurrent_spin.value()
        self.flow_concurrent_spin.setRange(1, max_concurrent)
        if current_value > max_concurrent:
            self.flow_concurrent_spin.setValue(max_concurrent)
        
        quality_label = self.flow_upsample_combo.currentText() if hasattr(self, "flow_upsample_combo") and self.flow_upsample_combo else "Gốc"
        self.flow_concurrent_spin.setToolTip(
            f"Số prompt xử lý đồng thời (1-{max_concurrent}, 1 cookie = {per_cookie_concurrent} concurrent, {quality_label})"
        )
        self.log(
            f"⚙️ Flow concurrent range: 1-{max_concurrent} "
            f"(dựa trên {num_cookies} cookie(s) × {per_cookie_concurrent} - {quality_label})"
        )

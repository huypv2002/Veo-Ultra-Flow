"""
Image Tab Builder - Builds Image Whisk tab UI components
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea, QFrame,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QGroupBox, QGridLayout,
    QListWidget, QRadioButton, QProgressBar, QAbstractItemView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


def build_image_tab_content(main_app):
    """Build Image Whisk tab content"""
    image_widget = QWidget()
    layout = QVBoxLayout(image_widget)
    layout.setContentsMargins(5, 5, 5, 5)
    layout.setSpacing(5)
    
    # Main splitter: Controls | Results
    splitter = QSplitter(Qt.Horizontal)
    
    # LEFT: Controls (Mode, Settings, Inputs)
    left_panel = build_image_left_panel(main_app)
    splitter.addWidget(left_panel)
    
    # RIGHT: Results table (full width)
    right_panel = build_image_center_panel(main_app)
    splitter.addWidget(right_panel)
    
    splitter.setSizes([500, 900])
    splitter.setChildrenCollapsible(False)
    
    layout.addWidget(splitter)
    return image_widget


def build_image_left_panel(main_app):
    """Build left panel for Image tab"""
    widget = QWidget()
    widget.setMinimumWidth(480)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(10)
    
    flat_input_style = """
        QLineEdit {
            border: 1px solid #cbd5e1;
            border-radius: 0px;
            padding: 10px 12px;
            font-size: 13px;
            background: #ffffff;
        }
        QLineEdit:focus {
            border: 1px solid #4c8bf5;
        }
    """
    
    # ===== MODE SELECTION =====
    mode_group = QGroupBox("Chế độ tạo ảnh")
    mode_layout = QVBoxLayout()
    
    # Hàng 1: Text-to-Image và Image-to-Image
    row1_layout = QHBoxLayout()
    main_app.rb_text_to_image = QRadioButton("Text-to-Image (chuyển Văn Bản => Ảnh)")
    main_app.rb_text_to_image.setChecked(True)
    main_app.rb_text_to_image.clicked.connect(main_app.on_image_mode_change)
    row1_layout.addWidget(main_app.rb_text_to_image)
    
    main_app.rb_image_to_image = QRadioButton("Image-to-Image (chuyển Văn Bản+Ảnh => Ảnh)")
    main_app.rb_image_to_image.clicked.connect(main_app.on_image_mode_change)
    row1_layout.addWidget(main_app.rb_image_to_image)
    row1_layout.addStretch()
    mode_layout.addLayout(row1_layout)
    
    # Hàng 2: Multiple-to-Image
    row2_layout = QHBoxLayout()
    main_app.rb_multiple_to_image = QRadioButton("Multiple-to-Image (Nhiều Ảnh + Văn Bản => Ảnh)")
    main_app.rb_multiple_to_image.clicked.connect(main_app.on_image_mode_change)
    row2_layout.addWidget(main_app.rb_multiple_to_image)
    row2_layout.addStretch()
    mode_layout.addLayout(row2_layout)
    
    mode_group.setLayout(mode_layout)
    layout.addWidget(mode_group)
    
    # ===== TEXT-TO-IMAGE INPUTS =====
    main_app.text_to_image_group = QGroupBox("Text-to-Image (chuyển Văn Bản => Ảnh)")
    t2i_layout = QVBoxLayout()
    t2i_layout.setSpacing(8)
    
    # Cookie info
    cookie_info = QLabel("Cookie (sử dụng chung với Video)")
    cookie_info.setStyleSheet("font-weight: bold;")
    t2i_layout.addWidget(cookie_info)
    
    cookie_note = QLabel("→ Dùng cookie đã nhập ở tab Video")
    cookie_note.setStyleSheet("color: #666666; font-size: 10px; font-style: italic;")
    t2i_layout.addWidget(cookie_note)
    
    # File prompt
    file_label = QLabel("File prompt (chỉ chấp nhận file .txt):")
    file_label.setStyleSheet("font-weight: bold;")
    t2i_layout.addWidget(file_label)
    
    batch_row = QHBoxLayout()
    main_app.txt_whisk_prompt_file = QLineEdit()
    main_app.txt_whisk_prompt_file.setPlaceholderText("Chọn file .txt chứa prompts (1 prompt/dòng)...")
    main_app.txt_whisk_prompt_file.setReadOnly(True)
    main_app.txt_whisk_prompt_file.setMinimumHeight(36)
    main_app.txt_whisk_prompt_file.setStyleSheet(flat_input_style)
    batch_row.addWidget(main_app.txt_whisk_prompt_file)
    btn_batch = QPushButton("Chọn file")
    btn_batch.setFixedSize(80, 25)
    btn_batch.clicked.connect(main_app.browse_whisk_prompt_file)
    batch_row.addWidget(btn_batch)
    t2i_layout.addLayout(batch_row)
    
    # Folder prompt
    folder_label = QLabel("Hoặc chọn thư mục chứa file .txt:")
    folder_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
    t2i_layout.addWidget(folder_label)
    
    folder_row = QHBoxLayout()
    main_app.txt_t2i_prompt_folder = QLineEdit()
    main_app.txt_t2i_prompt_folder.setPlaceholderText("Chọn thư mục chứa nhiều file .txt...")
    main_app.txt_t2i_prompt_folder.setReadOnly(True)
    main_app.txt_t2i_prompt_folder.setMinimumHeight(36)
    main_app.txt_t2i_prompt_folder.setStyleSheet(flat_input_style)
    folder_row.addWidget(main_app.txt_t2i_prompt_folder)
    btn_folder = QPushButton("Chọn thư mục")
    btn_folder.setFixedSize(100, 25)
    btn_folder.clicked.connect(main_app.browse_t2i_prompt_folder)
    folder_row.addWidget(btn_folder)
    t2i_layout.addLayout(folder_row)
    
    # Batch table
    batch_table_label = QLabel("📋 Danh sách file batch:")
    batch_table_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #1976D2; margin-top: 8px;")
    t2i_layout.addWidget(batch_table_label)
    
    main_app.t2i_batch_table = QTableWidget()
    main_app.t2i_batch_table.setColumnCount(4)
    main_app.t2i_batch_table.setHorizontalHeaderLabels(["STT", "Tên File", "Số Prompts", "Status"])
    main_app.t2i_batch_table.setMinimumHeight(120)
    main_app.t2i_batch_table.setMaximumHeight(200)
    main_app.t2i_batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    main_app.t2i_batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    main_app.t2i_batch_table.verticalHeader().setVisible(False)
    main_app.t2i_batch_table.setColumnWidth(0, 50)
    main_app.t2i_batch_table.setColumnWidth(1, 150)
    main_app.t2i_batch_table.setColumnWidth(2, 80)
    main_app.t2i_batch_table.horizontalHeader().setStretchLastSection(True)
    t2i_layout.addWidget(main_app.t2i_batch_table)
    
    main_app.text_to_image_group.setLayout(t2i_layout)
    layout.addWidget(main_app.text_to_image_group)
    
    # ===== IMAGE-TO-IMAGE INPUTS =====
    main_app.image_to_image_group = QGroupBox("Image-to-Image (chuyển Văn Bản+Ảnh => Ảnh)")
    i2i_group_layout = QVBoxLayout(main_app.image_to_image_group)
    i2i_group_layout.setContentsMargins(0, 0, 0, 0)
    i2i_group_layout.setSpacing(0)

    i2i_scroll = QScrollArea()
    i2i_scroll.setWidgetResizable(True)
    i2i_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    i2i_scroll.setFrameShape(QFrame.NoFrame)

    i2i_container = QWidget()
    i2i_layout = QVBoxLayout(i2i_container)
    i2i_layout.setSpacing(8)
    i2i_layout.setContentsMargins(10, 10, 10, 10)

    # Reference images - SINGLE FILES
    single_ref_group = QGroupBox("Ảnh tham chiếu (Subject / Scene / Style)")
    single_ref_layout = QGridLayout()
    single_ref_layout.setSpacing(6)

    # Subject single
    single_ref_layout.addWidget(QLabel("Subject(Ảnh Chính):"), 0, 0)
    main_app.txt_subject_image = QLineEdit()
    main_app.txt_subject_image.setPlaceholderText("Chọn ảnh Subject...")
    main_app.txt_subject_image.setMinimumHeight(36)
    main_app.txt_subject_image.setStyleSheet(flat_input_style)
    single_ref_layout.addWidget(main_app.txt_subject_image, 0, 1)
    btn_subject = QPushButton("Chọn")
    btn_subject.setFixedSize(80, 25)
    btn_subject.clicked.connect(main_app.browse_subject_image)
    single_ref_layout.addWidget(btn_subject, 0, 2)

    # Scene
    single_ref_layout.addWidget(QLabel("Scene(Cảnh):"), 1, 0)
    main_app.txt_scene_image = QLineEdit()
    main_app.txt_scene_image.setPlaceholderText("Chọn ảnh Scene...")
    main_app.txt_scene_image.setMinimumHeight(36)
    main_app.txt_scene_image.setStyleSheet(flat_input_style)
    single_ref_layout.addWidget(main_app.txt_scene_image, 1, 1)
    btn_scene = QPushButton("Chọn")
    btn_scene.setFixedSize(80, 25)
    btn_scene.clicked.connect(main_app.browse_scene_image)
    single_ref_layout.addWidget(btn_scene, 1, 2)

    # Style
    single_ref_layout.addWidget(QLabel("Style(Kiểu):"), 2, 0)
    main_app.txt_style_image = QLineEdit()
    main_app.txt_style_image.setPlaceholderText("Chọn ảnh Style...")
    main_app.txt_style_image.setMinimumHeight(36)
    main_app.txt_style_image.setStyleSheet(flat_input_style)
    single_ref_layout.addWidget(main_app.txt_style_image, 2, 1)
    btn_style = QPushButton("Chọn")
    btn_style.setFixedSize(80, 25)
    btn_style.clicked.connect(main_app.browse_style_image)
    single_ref_layout.addWidget(btn_style, 2, 2)

    single_ref_group.setLayout(single_ref_layout)
    i2i_layout.addWidget(single_ref_group)

    # Batch prompt file for Image-to-Image
    file_prompt_label = QLabel("File prompt (chỉ chấp nhận file .txt):")
    file_prompt_label.setStyleSheet("font-weight: bold;")
    i2i_layout.addWidget(file_prompt_label)
    
    i2i_batch_row = QHBoxLayout()
    main_app.txt_i2i_prompt_file = QLineEdit()
    main_app.txt_i2i_prompt_file.setPlaceholderText("Chọn file .txt chứa prompts...")
    main_app.txt_i2i_prompt_file.setReadOnly(True)
    main_app.txt_i2i_prompt_file.setMinimumHeight(36)
    main_app.txt_i2i_prompt_file.setStyleSheet(flat_input_style)
    i2i_batch_row.addWidget(main_app.txt_i2i_prompt_file)
    btn_i2i_batch = QPushButton("Chọn file")
    btn_i2i_batch.setFixedSize(80, 25)
    btn_i2i_batch.clicked.connect(main_app.browse_i2i_prompt_file)
    i2i_batch_row.addWidget(btn_i2i_batch)
    i2i_layout.addLayout(i2i_batch_row)
    
    # Folder for I2I
    i2i_folder_label = QLabel("Hoặc chọn thư mục chứa file .txt:")
    i2i_folder_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
    i2i_layout.addWidget(i2i_folder_label)
    
    i2i_folder_row = QHBoxLayout()
    main_app.txt_i2i_prompt_folder = QLineEdit()
    main_app.txt_i2i_prompt_folder.setPlaceholderText("Chọn thư mục chứa nhiều file .txt...")
    main_app.txt_i2i_prompt_folder.setReadOnly(True)
    main_app.txt_i2i_prompt_folder.setMinimumHeight(36)
    main_app.txt_i2i_prompt_folder.setStyleSheet(flat_input_style)
    i2i_folder_row.addWidget(main_app.txt_i2i_prompt_folder)
    btn_i2i_folder = QPushButton("Chọn thư mục")
    btn_i2i_folder.setFixedSize(100, 25)
    btn_i2i_folder.clicked.connect(main_app.browse_i2i_prompt_folder)
    i2i_folder_row.addWidget(btn_i2i_folder)
    i2i_layout.addLayout(i2i_folder_row)
    
    # Batch table for I2I
    i2i_batch_table_label = QLabel("📋 Danh sách file batch:")
    i2i_batch_table_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #1976D2; margin-top: 8px;")
    i2i_layout.addWidget(i2i_batch_table_label)
    
    main_app.i2i_batch_table = QTableWidget()
    main_app.i2i_batch_table.setColumnCount(4)
    main_app.i2i_batch_table.setHorizontalHeaderLabels(["STT", "Tên File", "Số Prompts", "Status"])
    main_app.i2i_batch_table.setMinimumHeight(120)
    main_app.i2i_batch_table.setMaximumHeight(200)
    main_app.i2i_batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    main_app.i2i_batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    main_app.i2i_batch_table.verticalHeader().setVisible(False)
    main_app.i2i_batch_table.setColumnWidth(0, 50)
    main_app.i2i_batch_table.setColumnWidth(1, 150)
    main_app.i2i_batch_table.setColumnWidth(2, 80)
    main_app.i2i_batch_table.horizontalHeader().setStretchLastSection(True)
    i2i_layout.addWidget(main_app.i2i_batch_table)
    
    i2i_scroll.setWidget(i2i_container)
    i2i_group_layout.addWidget(i2i_scroll)
    
    # Hidden initially
    main_app.image_to_image_group.setVisible(False)
    layout.addWidget(main_app.image_to_image_group)
    
    # ===== MULTIPLE-TO-IMAGE INPUTS =====
    main_app.multiple_to_image_group = QGroupBox("Multiple-to-Image (Nhiều Ảnh + Văn Bản => Ảnh)")
    m2i_group_layout = QVBoxLayout(main_app.multiple_to_image_group)
    m2i_group_layout.setContentsMargins(0, 0, 0, 0)
    m2i_group_layout.setSpacing(0)
    
    m2i_scroll = QScrollArea()
    m2i_scroll.setWidgetResizable(True)
    m2i_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    m2i_scroll.setFrameShape(QFrame.NoFrame)
    
    m2i_container = QWidget()
    m2i_layout = QVBoxLayout(m2i_container)
    m2i_layout.setSpacing(8)
    m2i_layout.setContentsMargins(10, 10, 10, 10)
    
    # Folder selection
    m2i_layout.addWidget(QLabel("Thư mục chứa ảnh (từng cặp subject+scene):"))
    m2i_folder_row = QHBoxLayout()
    main_app.txt_m2i_folder = QLineEdit()
    main_app.txt_m2i_folder.setPlaceholderText("Chọn thư mục chứa các cặp ảnh...")
    main_app.txt_m2i_folder.setReadOnly(True)
    main_app.txt_m2i_folder.setMinimumHeight(36)
    main_app.txt_m2i_folder.setStyleSheet(flat_input_style)
    m2i_folder_row.addWidget(main_app.txt_m2i_folder)
    btn_m2i_folder = QPushButton("Chọn thư mục")
    btn_m2i_folder.setFixedSize(100, 25)
    btn_m2i_folder.clicked.connect(main_app.browse_m2i_folder)
    m2i_folder_row.addWidget(btn_m2i_folder)
    m2i_layout.addLayout(m2i_folder_row)
    
    # Info
    m2i_info = QLabel("💡 Cấu trúc folder: [subject_1.jpg, scene_1.jpg], [subject_2.jpg, scene_2.jpg], ...")
    m2i_info.setStyleSheet("color: #666666; font-size: 11px; font-style: italic;")
    m2i_layout.addWidget(m2i_info)
    
    # Prompt file
    m2i_prompt_label = QLabel("File prompt (1 dòng = 1 cặp ảnh):")
    m2i_prompt_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
    m2i_layout.addWidget(m2i_prompt_label)
    
    m2i_prompt_row = QHBoxLayout()
    main_app.txt_m2i_prompt_file = QLineEdit()
    main_app.txt_m2i_prompt_file.setPlaceholderText("Chọn file .txt...")
    main_app.txt_m2i_prompt_file.setReadOnly(True)
    main_app.txt_m2i_prompt_file.setMinimumHeight(36)
    main_app.txt_m2i_prompt_file.setStyleSheet(flat_input_style)
    m2i_prompt_row.addWidget(main_app.txt_m2i_prompt_file)
    btn_m2i_prompt = QPushButton("Chọn file")
    btn_m2i_prompt.setFixedSize(80, 25)
    btn_m2i_prompt.clicked.connect(main_app.browse_m2i_prompt_file)
    m2i_prompt_row.addWidget(btn_m2i_prompt)
    m2i_layout.addLayout(m2i_prompt_row)
    
    m2i_scroll.setWidget(m2i_container)
    m2i_group_layout.addWidget(m2i_scroll)
    
    main_app.multiple_to_image_group.setVisible(False)
    layout.addWidget(main_app.multiple_to_image_group)
    
    # ===== SETTINGS =====
    settings_group = QGroupBox("Thiết lập")
    settings_layout = QGridLayout()
    settings_layout.setSpacing(10)
    settings_layout.setColumnStretch(1, 1)
    
    # Model
    settings_layout.addWidget(QLabel("Model:"), 0, 0)
    main_app.combo_image_model = QComboBox()
    main_app.combo_image_model.addItems([
        "Pixel (nhanh, ảnh nhỏ)",
        "Pixel 2 (chất lượng tốt)",
        "Pixel 3 (chất lượng cao nhất)"
    ])
    main_app.combo_image_model.setCurrentIndex(1)
    settings_layout.addWidget(main_app.combo_image_model, 0, 1)
    
    # Aspect ratio
    settings_layout.addWidget(QLabel("Tỷ lệ:"), 1, 0)
    main_app.combo_image_aspect = QComboBox()
    main_app.combo_image_aspect.addItems([
        "1:1 (Vuông)",
        "16:9 (Ngang)",
        "9:16 (Dọc)",
        "4:3",
        "3:4"
    ])
    main_app.combo_image_aspect.setCurrentIndex(1)
    settings_layout.addWidget(main_app.combo_image_aspect, 1, 1)
    
    # Output folder
    settings_layout.addWidget(QLabel("Thư mục lưu:"), 2, 0)
    img_output_row = QHBoxLayout()
    main_app.txt_image_output_folder = QLineEdit()
    main_app.txt_image_output_folder.setText(str(Path.home() / "Downloads" / "Generated_Images"))
    img_output_row.addWidget(main_app.txt_image_output_folder)
    btn_img_output = QPushButton("Chọn")
    btn_img_output.setFixedSize(70, 25)
    btn_img_output.clicked.connect(main_app.browse_image_output_folder)
    img_output_row.addWidget(btn_img_output)
    settings_layout.addLayout(img_output_row, 2, 1)
    
    settings_group.setLayout(settings_layout)
    layout.addWidget(settings_group)
    
    # ===== CONTROL BUTTONS =====
    btn_layout = QHBoxLayout()
    btn_layout.setSpacing(10)
    
    main_app.btn_image_start = QPushButton("🚀 Bắt đầu")
    main_app.btn_image_start.setFixedSize(120, 40)
    main_app.btn_image_start.setObjectName("startButton")
    main_app.btn_image_start.clicked.connect(main_app.on_image_start)
    btn_layout.addWidget(main_app.btn_image_start)
    
    main_app.btn_image_pause = QPushButton("⏸ Tạm dừng")
    main_app.btn_image_pause.setFixedSize(100, 40)
    main_app.btn_image_pause.setEnabled(False)
    main_app.btn_image_pause.clicked.connect(main_app.on_image_pause)
    btn_layout.addWidget(main_app.btn_image_pause)
    
    main_app.btn_image_stop = QPushButton("⏹ Dừng")
    main_app.btn_image_stop.setFixedSize(80, 40)
    main_app.btn_image_stop.setEnabled(False)
    main_app.btn_image_stop.clicked.connect(main_app.on_image_stop)
    btn_layout.addWidget(main_app.btn_image_stop)
    
    layout.addLayout(btn_layout)
    layout.addStretch()
    
    return widget


def build_image_center_panel(main_app):
    """Build center panel for Image tab"""
    from PySide6.QtWidgets import QAbstractItemView
    
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(5, 5, 5, 5)
    layout.setSpacing(10)
    
    # Header
    header = QHBoxLayout()
    header_label = QLabel("Kết quả tạo ảnh")
    header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
    header.addWidget(header_label)
    header.addStretch()
    
    main_app.btn_clear_images = QPushButton("🗑️ Xóa tất cả")
    main_app.btn_clear_images.setFixedSize(100, 30)
    main_app.btn_clear_images.clicked.connect(main_app.clear_image_results)
    header.addWidget(main_app.btn_clear_images)
    
    layout.addLayout(header)
    
    # Results table
    main_app.image_results_table = QTableWidget()
    main_app.image_results_table.setColumnCount(4)
    main_app.image_results_table.setHorizontalHeaderLabels(["#", "Prompt", "Trạng thái", "Ảnh"])
    main_app.image_results_table.setMinimumHeight(400)
    main_app.image_results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    main_app.image_results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    main_app.image_results_table.verticalHeader().setVisible(True)
    main_app.image_results_table.setColumnWidth(0, 40)
    main_app.image_results_table.setColumnWidth(1, 200)
    main_app.image_results_table.setColumnWidth(2, 100)
    main_app.image_results_table.horizontalHeader().setStretchLastSection(True)
    main_app.image_results_table.setStyleSheet("""
        QTableWidget {
            background: #ffffff;
            border: 1px solid #e0e0e0;
        }
    """)
    
    layout.addWidget(main_app.image_results_table)
    
    # Progress
    main_app.image_progress_bar = QProgressBar()
    main_app.image_progress_bar.setFixedHeight(20)
    main_app.image_progress_bar.setTextVisible(True)
    main_app.image_progress_bar.setStyleSheet("""
        QProgressBar {
            border: 1px solid #ccc;
            border-radius: 5px;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: #4CAF50;
        }
    """)
    layout.addWidget(main_app.image_progress_bar)
    
    return widget


# Import needed for QAbstractItemView
from PySide6.QtWidgets import QAbstractItemView

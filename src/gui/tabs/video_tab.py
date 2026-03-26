"""
Video Tab Builder - Builds Video tab UI components
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea, QFrame,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QGroupBox, QGridLayout, QTextEdit,
    QListWidget, QListWidgetItem, QProgressBar, QButtonGroup, QRadioButton,
    QFormLayout, QPlainTextEdit, QAbstractItemView, QHeaderView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


def build_video_tab_content(main_app):
    """Build Video tab content widget"""
    video_widget = QWidget()
    layout = QVBoxLayout(video_widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    
    # TOP: 2 cột (Settings | Prompts)
    top_splitter = QSplitter(Qt.Horizontal)
    
    # LEFT: Settings
    left = build_left_panel(main_app)
    top_splitter.addWidget(left)
    
    # RIGHT: Prompts table
    center = build_center_panel(main_app)
    top_splitter.addWidget(center)
    
    top_splitter.setSizes([500, 900])
    top_splitter.setChildrenCollapsible(False)
    
    layout.addWidget(top_splitter)
    
    # BOTTOM: Logs
    logs_panel = build_logs_panel(main_app)
    layout.addWidget(logs_panel)
    
    return video_widget


def build_left_panel(main_app):
    """Build left panel (Settings) for Video tab"""
    from PySide6.QtWidgets import QScrollArea
    
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setMinimumWidth(480)
    scroll_area.setStyleSheet("""
        QScrollArea {
            border: none;
            background-color: transparent;
        }
    """)
    
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(10)
    
    # ===== BATCH JOB INPUT =====
    input_group = QGroupBox("Batch Job")
    input_layout = QVBoxLayout()
    input_layout.setSpacing(8)
    
    # Text to Video inputs (hidden - using Batch Job only)
    txt_t2v_frame = QWidget()
    t2v_layout = QVBoxLayout(txt_t2v_frame)
    t2v_layout.setContentsMargins(0, 0, 0, 0)
    txt_t2v_frame.setVisible(False)
    input_layout.addWidget(txt_t2v_frame)
    
    # Image to Video inputs
    txt_i2v_frame = QWidget()
    i2v_layout = QVBoxLayout(txt_i2v_frame)
    i2v_layout.setContentsMargins(0, 0, 0, 0)
    i2v_layout.setSpacing(6)
    
    i2v_mode_col = QVBoxLayout()
    main_app.rb_i2v_mode_folder_file = QRadioButton("Thư mục ảnh + 1 file .txt")
    main_app.rb_i2v_mode_folder_file.setChecked(True)
    main_app.rb_i2v_mode_folder_txt = QRadioButton("Thư mục ảnh + thư mục .txt")
    main_app.rb_i2v_mode_root_match = QRadioButton("Folder gốc: file .txt + folder ảnh trùng tên")
    i2v_mode_col.addWidget(main_app.rb_i2v_mode_folder_file)
    i2v_mode_col.addWidget(main_app.rb_i2v_mode_folder_txt)
    i2v_mode_col.addWidget(main_app.rb_i2v_mode_root_match)
    i2v_layout.addLayout(i2v_mode_col)
    
    # Thư mục ảnh
    main_app.lbl_i2v_img_folder = QLabel("Thư mục ảnh (nhiều files):")
    i2v_layout.addWidget(main_app.lbl_i2v_img_folder)
    img_folder_row = QHBoxLayout()
    main_app.txt_image_folder = QLineEdit()
    main_app.txt_image_folder.setPlaceholderText("Chọn thư mục chứa ảnh...")
    img_folder_row.addWidget(main_app.txt_image_folder)
    main_app.btn_img_folder = QPushButton("Chọn thư mục")
    main_app.btn_img_folder.setFixedSize(100, 25)
    main_app.btn_img_folder.clicked.connect(main_app.browse_image_folder)
    img_folder_row.addWidget(main_app.btn_img_folder)
    i2v_layout.addLayout(img_folder_row)
    
    # File prompt
    main_app.lbl_i2v_prompt_file = QLabel("File prompt (1 dòng = 1 ảnh):")
    i2v_layout.addWidget(main_app.lbl_i2v_prompt_file)
    img_prompt_row = QHBoxLayout()
    main_app.txt_image_prompt_file = QLineEdit()
    main_app.txt_image_prompt_file.setPlaceholderText("Chọn file .txt...")
    img_prompt_row.addWidget(main_app.txt_image_prompt_file)
    main_app.btn_img_prompt = QPushButton("Chọn file")
    main_app.btn_img_prompt.setFixedSize(80, 25)
    main_app.btn_img_prompt.clicked.connect(main_app.browse_image_prompt_file)
    img_prompt_row.addWidget(main_app.btn_img_prompt)
    i2v_layout.addLayout(img_prompt_row)
    
    # Thư mục .txt
    main_app.lbl_i2v_prompt_folder = QLabel("Thư mục .txt (nhiều files):")
    i2v_layout.addWidget(main_app.lbl_i2v_prompt_folder)
    img_prompt_folder_row = QHBoxLayout()
    main_app.txt_image_prompt_folder = QLineEdit()
    main_app.txt_image_prompt_folder.setPlaceholderText("Chọn thư mục chứa nhiều file .txt...")
    img_prompt_folder_row.addWidget(main_app.txt_image_prompt_folder)
    main_app.btn_img_prompt_folder = QPushButton("Chưng thư mục")
    main_app.btn_img_prompt_folder.setFixedSize(100, 25)
    main_app.btn_img_prompt_folder.clicked.connect(main_app.browse_image_prompt_folder)
    img_prompt_folder_row.addWidget(main_app.btn_img_prompt_folder)
    i2v_layout.addLayout(img_prompt_folder_row)
    
    # Folder gốc
    main_app.lbl_i2v_root_folder = QLabel("Folder gốc (file .txt + folder ảnh trùng tên):")
    i2v_layout.addWidget(main_app.lbl_i2v_root_folder)
    img_root_folder_row = QHBoxLayout()
    main_app.txt_image_root_folder = QLineEdit()
    main_app.txt_image_root_folder.setPlaceholderText("Chọn folder gốc...")
    img_root_folder_row.addWidget(main_app.txt_image_root_folder)
    main_app.btn_img_root_folder = QPushButton("Chọn folder")
    main_app.btn_img_root_folder.setFixedSize(100, 25)
    main_app.btn_img_root_folder.clicked.connect(main_app.browse_image_root_folder)
    img_root_folder_row.addWidget(main_app.btn_img_root_folder)
    i2v_layout.addLayout(img_root_folder_row)
    
    # Tip
    main_app.lbl_i2v_tip = QLabel(
        "💡 Logic:\n"
        "- Mode 1: Thư mục ảnh + 1 file .txt\n"
        "- Mode 2: Thư mục ảnh + thư mục .txt\n"
        "- Mode 3: Folder gốc: 1.txt + folder '1', ..."
    )
    main_app.lbl_i2v_tip.setStyleSheet("color: #666666; font-size: 10px; font-style: italic;")
    i2v_layout.addWidget(main_app.lbl_i2v_tip)
    
    # Connect events
    main_app.rb_i2v_mode_folder_file.toggled.connect(main_app.update_i2v_mode_ui)
    main_app.rb_i2v_mode_folder_txt.toggled.connect(main_app.update_i2v_mode_ui)
    main_app.rb_i2v_mode_root_match.toggled.connect(main_app.update_i2v_mode_ui)
    main_app.update_i2v_mode_ui()
    
    txt_i2v_frame.setVisible(False)
    input_layout.addWidget(txt_i2v_frame)
    
    # Start+End to Video inputs
    txt_start_end_frame = QWidget()
    se_layout = QVBoxLayout(txt_start_end_frame)
    se_layout.setContentsMargins(0, 0, 0, 0)
    se_layout.setSpacing(6)
    
    se_layout.addWidget(QLabel("Thư mục ảnh (Start + End):"))
    se_folder_row = QHBoxLayout()
    main_app.txt_start_end_folder = QLineEdit()
    main_app.txt_start_end_folder.setPlaceholderText("Chọn thư mục...")
    se_folder_row.addWidget(main_app.txt_start_end_folder)
    btn_se_folder = QPushButton("Chọn thư mục")
    btn_se_folder.setFixedSize(100, 25)
    btn_se_folder.clicked.connect(main_app.browse_start_end_folder)
    se_folder_row.addWidget(btn_se_folder)
    se_layout.addLayout(se_folder_row)
    
    se_layout.addWidget(QLabel("File prompt"))
    se_prompt_row = QHBoxLayout()
    main_app.txt_start_end_prompt = QLineEdit()
    main_app.txt_start_end_prompt.setPlaceholderText("File prompt...")
    se_prompt_row.addWidget(main_app.txt_start_end_prompt)
    btn_se_prompt = QPushButton("Chọn file")
    btn_se_prompt.setFixedSize(80, 25)
    btn_se_prompt.clicked.connect(main_app.browse_start_end_prompt)
    se_prompt_row.addWidget(btn_se_prompt)
    se_layout.addLayout(se_prompt_row)
    
    # Mode selection
    mode_row = QHBoxLayout()
    mode_label = QLabel("Chế độ Start+End:")
    mode_row.addWidget(mode_label)
    main_app.rb_start_end_pair = QRadioButton("2 ảnh / 1 prompt")
    main_app.rb_start_end_pair.setChecked(True)
    main_app.rb_start_end_chain = QRadioButton("Nối frame 1-2, 2-3, 3-4...")
    mode_row.addWidget(main_app.rb_start_end_pair)
    mode_row.addWidget(main_app.rb_start_end_chain)
    mode_row.addStretch()
    se_layout.addLayout(mode_row)
    
    txt_start_end_frame.setVisible(False)
    input_layout.addWidget(txt_start_end_frame)
    
    # Extend Video inputs
    txt_extend_frame = QWidget()
    ext_layout = QVBoxLayout(txt_extend_frame)
    ext_layout.setContentsMargins(0, 0, 0, 0)
    ext_layout.setSpacing(6)
    
    ext_layout.addWidget(QLabel("File TXT (mỗi dòng = 1 đoạn video 8s):"))
    file_row = QHBoxLayout()
    main_app.txt_extend_txt_file = QLineEdit()
    main_app.txt_extend_txt_file.setPlaceholderText("Chọn file .txt...")
    file_row.addWidget(main_app.txt_extend_txt_file)
    btn_ext_file = QPushButton("Chọn file")
    btn_ext_file.setFixedSize(100, 25)
    btn_ext_file.clicked.connect(main_app.browse_extend_txt_file)
    file_row.addWidget(btn_ext_file)
    ext_layout.addLayout(file_row)
    
    ext_layout.addWidget(QLabel("Folder TXT (mỗi file = 1 project, ≤ 5 dòng/file):"))
    folder_row = QHBoxLayout()
    main_app.txt_extend_txt_folder = QLineEdit()
    main_app.txt_extend_txt_folder.setPlaceholderText("Chọn thư mục...")
    folder_row.addWidget(main_app.txt_extend_txt_folder)
    btn_ext_folder = QPushButton("Chọn thư mục")
    btn_ext_folder.setFixedSize(120, 25)
    btn_ext_folder.clicked.connect(main_app.browse_extend_txt_folder)
    folder_row.addWidget(btn_ext_folder)
    ext_layout.addLayout(folder_row)
    
    # Group size
    group_row = QHBoxLayout()
    group_row.addWidget(QLabel("Mỗi project chứa:"))
    main_app.combo_extend_group_size = QComboBox()
    main_app.combo_extend_group_size.addItems([str(i) for i in range(1, 6)])
    main_app.combo_extend_group_size.setCurrentText("5")
    main_app.combo_extend_group_size.setFixedWidth(60)
    group_row.addWidget(main_app.combo_extend_group_size)
    main_app.lbl_extend_max_prompts = QLabel("đoạn (max 5)")
    group_row.addWidget(main_app.lbl_extend_max_prompts)
    group_row.addStretch()
    ext_layout.addLayout(group_row)
    
    # Output folder
    ext_layout.addWidget(QLabel("Thư mục xuất video:"))
    output_row = QHBoxLayout()
    main_app.txt_extend_output = QLineEdit()
    main_app.txt_extend_output.setText(str(Path.home() / "Downloads" / "Extended_Videos"))
    output_row.addWidget(main_app.txt_extend_output)
    btn_ext_output = QPushButton("Chọn")
    btn_ext_output.setFixedSize(80, 25)
    btn_ext_output.clicked.connect(main_app.browse_extend_output)
    output_row.addWidget(btn_ext_output)
    ext_layout.addLayout(output_row)
    
    txt_extend_frame.setVisible(False)
    input_layout.addWidget(txt_extend_frame)
    
    # Integrate to Video inputs
    txt_integrate_frame = QWidget()
    int_layout = QVBoxLayout(txt_integrate_frame)
    int_layout.setContentsMargins(0, 0, 0, 0)
    int_layout.setSpacing(6)
    
    # Mode radio buttons
    main_app.integrate_mode_group = QButtonGroup()
    mode_radio_layout = QHBoxLayout()
    mode_radio_layout.setSpacing(15)
    
    main_app.rb_integrate_default = QRadioButton("Mặc Định")
    main_app.rb_integrate_default.setChecked(True)
    main_app.rb_integrate_default.toggled.connect(main_app.on_integrate_mode_changed)
    main_app.integrate_mode_group.addButton(main_app.rb_integrate_default, 0)
    mode_radio_layout.addWidget(main_app.rb_integrate_default)
    
    main_app.rb_integrate_custom = QRadioButton("Tùy Chỉnh (Trả Phí)")
    main_app.rb_integrate_custom.toggled.connect(main_app.on_integrate_mode_changed)
    main_app.integrate_mode_group.addButton(main_app.rb_integrate_custom, 1)
    mode_radio_layout.addWidget(main_app.rb_integrate_custom)
    
    mode_radio_layout.addStretch()
    int_layout.addLayout(mode_radio_layout)
    
    # Default frame
    main_app.integrate_default_frame = QWidget()
    default_layout = QVBoxLayout(main_app.integrate_default_frame)
    default_layout.setContentsMargins(0, 0, 0, 0)
    default_layout.setSpacing(6)
    
    # Folder ảnh
    default_layout.addWidget(QLabel("Thư mục chứa các ảnh:"))
    img_folder_row = QHBoxLayout()
    main_app.txt_integrate_images_folder = QLineEdit()
    main_app.txt_integrate_images_folder.setPlaceholderText("Chọn thư mục ảnh...")
    img_folder_row.addWidget(main_app.txt_integrate_images_folder)
    btn_int_folder = QPushButton("Chọn thư mục")
    btn_int_folder.setFixedSize(100, 25)
    btn_int_folder.clicked.connect(main_app.browse_integrate_images_folder)
    img_folder_row.addWidget(btn_int_folder)
    default_layout.addLayout(img_folder_row)
    
    # File prompt
    default_layout.addWidget(QLabel("File txt chứa prompt:"))
    prompt_row = QHBoxLayout()
    main_app.txt_integrate_prompt_file = QLineEdit()
    main_app.txt_integrate_prompt_file.setPlaceholderText("Chọn file prompt...")
    prompt_row.addWidget(main_app.txt_integrate_prompt_file)
    btn_int_prompt = QPushButton("Chọn file")
    btn_int_prompt.setFixedSize(80, 25)
    btn_int_prompt.clicked.connect(main_app.browse_integrate_prompt_file)
    prompt_row.addWidget(btn_int_prompt)
    default_layout.addLayout(prompt_row)
    
    # Số ảnh mỗi nhóm
    group_size_row = QHBoxLayout()
    group_size_row.addWidget(QLabel("Số ảnh mỗi nhóm:"))
    main_app.combo_integrate_images_per_group = QComboBox()
    main_app.combo_integrate_images_per_group.addItems(["1", "2", "3"])
    main_app.combo_integrate_images_per_group.setCurrentText("3")
    main_app.combo_integrate_images_per_group.setFixedWidth(60)
    group_size_row.addWidget(main_app.combo_integrate_images_per_group)
    group_size_row.addStretch()
    default_layout.addLayout(group_size_row)
    
    # Separator
    separator_line = QFrame()
    separator_line.setFrameShape(QFrame.HLine)
    separator_line.setFrameShadow(QFrame.Sunken)
    separator_line.setStyleSheet("background-color: #e0e0e0; margin: 10px 0;")
    default_layout.addWidget(separator_line)
    
    # Folder prompts + nhân vật cố định
    folder_fixed_label = QLabel("📁 Folder Prompts + Nhân vật cố định:")
    folder_fixed_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #1976D2; margin-top: 5px;")
    default_layout.addWidget(folder_fixed_label)
    
    folder_fixed_tip = QLabel("Chọn 1 folder chứa nhiều file .txt, áp dụng 2-3 ảnh nhân vật cố định")
    folder_fixed_tip.setStyleSheet("font-size: 11px; color: #666; margin-bottom: 5px;")
    folder_fixed_tip.setWordWrap(True)
    default_layout.addWidget(folder_fixed_tip)
    
    # Folder prompts
    default_layout.addWidget(QLabel("Thư mục chứa các file prompts (.txt):"))
    folder_prompts_row = QHBoxLayout()
    main_app.txt_expand_ref_folder_prompts = QLineEdit()
    main_app.txt_expand_ref_folder_prompts.setPlaceholderText("Chọn thư mục...")
    folder_prompts_row.addWidget(main_app.txt_expand_ref_folder_prompts)
    btn_folder_prompts = QPushButton("Chọn thư mục")
    btn_folder_prompts.setFixedSize(100, 25)
    btn_folder_prompts.clicked.connect(main_app.browse_expand_ref_folder_prompts)
    folder_prompts_row.addWidget(btn_folder_prompts)
    default_layout.addLayout(folder_prompts_row)
    
    # Nhân vật cố định
    default_layout.addWidget(QLabel("Ảnh nhân vật cố định (tối đa 3 ảnh):"))
    main_app.expand_ref_fixed_images_list = QListWidget()
    main_app.expand_ref_fixed_images_list.setFixedHeight(100)
    main_app.expand_ref_fixed_images_list.setStyleSheet("""
        QListWidget {
            background: #fafafa;
            border: 1px solid #ddd;
            border-radius: 6px;
        }
    """)
    default_layout.addWidget(main_app.expand_ref_fixed_images_list)
    
    # Buttons
    fixed_images_btn_row = QHBoxLayout()
    btn_add_fixed_images = QPushButton("➕ Thêm ảnh")
    btn_add_fixed_images.setFixedSize(100, 28)
    btn_add_fixed_images.clicked.connect(main_app.add_expand_ref_fixed_images)
    fixed_images_btn_row.addWidget(btn_add_fixed_images)
    
    btn_clear_fixed_images = QPushButton("🗑️ Xóa tất cả")
    btn_clear_fixed_images.setFixedSize(100, 28)
    btn_clear_fixed_images.clicked.connect(main_app.clear_expand_ref_fixed_images)
    fixed_images_btn_row.addWidget(btn_clear_fixed_images)
    fixed_images_btn_row.addStretch()
    default_layout.addLayout(fixed_images_btn_row)
    
    main_app.expand_ref_fixed_images_paths = []
    
    int_layout.addWidget(main_app.integrate_default_frame)
    
    # Custom frame
    custom_btn_layout = QHBoxLayout()
    custom_btn_layout.addStretch()
    main_app.btn_open_custom = QPushButton("⚙️ Mở Cấu Hình Tùy Chỉnh")
    main_app.btn_open_custom.setFixedSize(200, 35)
    main_app.btn_open_custom.setObjectName("btn_open_custom")
    main_app.btn_open_custom.clicked.connect(main_app.open_custom_integrate_dialog)
    custom_btn_layout.addWidget(main_app.btn_open_custom)
    custom_btn_layout.addStretch()
    
    main_app.integrate_custom_frame = QWidget()
    custom_frame_layout = QVBoxLayout(main_app.integrate_custom_frame)
    custom_frame_layout.setContentsMargins(0, 0, 0, 0)
    custom_frame_layout.addLayout(custom_btn_layout)
    
    int_layout.addWidget(main_app.integrate_custom_frame)
    main_app.integrate_custom_frame.setVisible(False)
    
    # Character storage
    main_app.custom_characters = {}
    main_app.character_matching_results = {}
    
    # Hidden prompt file path
    main_app.txt_integrate_custom_prompt_file = QLineEdit()
    main_app.txt_integrate_custom_prompt_file.setVisible(False)
    
    # Show/hide frames
    device_info = main_app.get_device_info()
    main_app.rb_integrate_default.setVisible(True)
    main_app.rb_integrate_custom.setVisible(True)
    main_app.integrate_default_frame.setVisible(True)
    main_app.integrate_custom_frame.setVisible(False)
    
    txt_integrate_frame.setVisible(False)
    input_layout.addWidget(txt_integrate_frame)
    
    input_group.setLayout(input_layout)
    input_group.setVisible(False)
    layout.addWidget(input_group)
    
    # ===== SETTINGS BOX =====
    main_app.settings_box = QGroupBox("Thiết lập tạo Video")
    settings_layout = QGridLayout()
    settings_layout.setSpacing(10)
    settings_layout.setColumnStretch(1, 1)
    settings_layout.setColumnStretch(2, 0)
    
    row = 0
    
    # Model
    settings_layout.addWidget(QLabel("Model:"), row, 0)
    main_app.combo_model = QComboBox()
    main_app.combo_model.addItems([
        "Low Fast (16:9) - 0 credits",
        "Fast (16:9) - 10 credits",
        "Quality (16:9) - 100 credits",
        "Low Fast (9:16) - 0 credits",
        "Fast (9:16) - 10 credits",
        "Quality (9:16) - 100 credits",
    ])
    main_app.combo_model.setCurrentIndex(1)
    settings_layout.addWidget(main_app.combo_model, row, 1)
    main_app.combo_model.currentIndexChanged.connect(main_app.update_model_credit_hint)
    
    main_app.model_credit_label = QLabel("")
    main_app.model_credit_label.setStyleSheet("font-size: 11px; color: #616161;")
    main_app.model_credit_label.setVisible(False)
    settings_layout.addWidget(main_app.model_credit_label, row + 1, 0, 1, 2)
    main_app.update_model_credit_hint()
    
    row += 1
    
    # Hidden spin box
    main_app.spin_num_videos = QSpinBox()
    main_app.spin_num_videos.setRange(1, 1)
    main_app.spin_num_videos.setValue(1)
    main_app.spin_num_videos.setVisible(False)
    
    # Resolution - removed, using model name instead
    
    row += 1
    
    # Duration (video length)
    settings_layout.addWidget(QLabel("Độ dài:"), row, 0)
    main_app.combo_duration = QComboBox()
    main_app.combo_duration.addItems(["5 giây", "8 giây"])
    main_app.combo_duration.setCurrentIndex(1)
    settings_layout.addWidget(main_app.combo_duration, row, 1)
    
    row += 1
    
    # Aspect ratio display
    main_app.lbl_aspect_ratio = QLabel("Tỷ lệ: 16:9")
    main_app.lbl_aspect_ratio.setStyleSheet("font-size: 12px; color: #1976D2; font-weight: bold;")
    settings_layout.addWidget(main_app.lbl_aspect_ratio, row, 0, 1, 2)
    
    # Connect model change to update aspect ratio label
    main_app.combo_model.currentIndexChanged.connect(main_app.update_aspect_ratio_label)
    main_app.update_aspect_ratio_label()
    
    row += 1
    
    # Output folder
    settings_layout.addWidget(QLabel("Thư mục lưu:"), row, 0)
    output_folder_row = QHBoxLayout()
    main_app.txt_output_folder = QLineEdit()
    main_app.txt_output_folder.setText(str(Path.home() / "Downloads" / "Generated_Videos"))
    output_folder_row.addWidget(main_app.txt_output_folder)
    btn_output = QPushButton("Chọn")
    btn_output.setFixedSize(70, 25)
    btn_output.clicked.connect(main_app.browse_output_folder)
    output_folder_row.addWidget(btn_output)
    settings_layout.addLayout(output_folder_row, row, 1)
    
    row += 1
    
    # Cookie selection
    settings_layout.addWidget(QLabel("Cookie:"), row, 0)
    cookie_row = QHBoxLayout()
    main_app.combo_cookie = QComboBox()
    main_app.combo_cookie.setMinimumWidth(200)
    cookie_row.addWidget(main_app.combo_cookie)
    main_app.btn_refresh_cookies = QPushButton("🔄")
    main_app.btn_refresh_cookies.setFixedSize(30, 30)
    main_app.btn_refresh_cookies.setToolTip("Refresh cookies")
    main_app.btn_refresh_cookies.clicked.connect(main_app.load_cookies_from_file)
    cookie_row.addWidget(main_app.btn_refresh_cookies)
    settings_layout.addLayout(cookie_row, row, 1)
    
    # Store frames for visibility control
    main_app.txt_t2v_frame = txt_t2v_frame
    main_app.txt_i2v_frame = txt_i2v_frame
    main_app.txt_start_end_frame = txt_start_end_frame
    main_app.txt_extend_frame = txt_extend_frame
    main_app.txt_integrate_frame = txt_integrate_frame
    main_app.input_group = input_group
    
    main_app.settings_box.setLayout(settings_layout)
    layout.addWidget(main_app.settings_box)
    
    # ===== VIDEO MODE SELECTION =====
    mode_group = QGroupBox("Chế độ Video")
    mode_layout = QVBoxLayout()
    
    main_app.video_mode_group = QButtonGroup()
    
    row_mode = 0
    for mode_name in ["Text to Video", "Image to Video", "Start+End to Video", 
                      "Extend Video", "Integrate to Video"]:
        radio = QRadioButton(mode_name)
        main_app.video_mode_group.addButton(radio)
        radio.toggled.connect(lambda checked, m=mode_name: main_app.on_video_mode_changed(m) if checked else None)
        mode_layout.addWidget(radio)
        if row_mode == 0:
            radio.setChecked(True)
        row_mode += 1
    
    mode_group.setLayout(mode_layout)
    layout.addWidget(mode_group)
    
    # ===== REFRESH COOKIE BUTTON =====
    refresh_layout = QHBoxLayout()
    refresh_layout.addStretch()
    layout.addLayout(refresh_layout)
    
    # Scroll area setup
    scroll_area.setWidget(widget)
    
    return scroll_area


def build_center_panel(main_app):
    """Build center panel (Prompts table) for Video tab"""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(5, 5, 5, 5)
    layout.setSpacing(10)
    
    # Pagination controls
    pagination_row = QHBoxLayout()
    
    main_app.lbl_prompts_page_info = QLabel("Trang 1/1 (0 prompts)")
    main_app.lbl_prompts_page_info.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 12px;")
    pagination_row.addWidget(main_app.lbl_prompts_page_info)
    
    pagination_row.addStretch()
    
    main_app.btn_prompts_prev_page = QPushButton("◀ Trang trước")
    main_app.btn_prompts_prev_page.setFixedSize(120, 30)
    main_app.btn_prompts_prev_page.clicked.connect(main_app.go_to_prev_prompts_page)
    main_app.btn_prompts_prev_page.setEnabled(False)
    pagination_row.addWidget(main_app.btn_prompts_prev_page)
    
    main_app.lbl_prompts_current_page = QLabel("1/1")
    main_app.lbl_prompts_current_page.setStyleSheet("font-weight: bold; font-size: 13px; margin: 0 10px;")
    pagination_row.addWidget(main_app.lbl_prompts_current_page)
    
    main_app.btn_prompts_next_page = QPushButton("Trang sau ▶")
    main_app.btn_prompts_next_page.setFixedSize(120, 30)
    main_app.btn_prompts_next_page.clicked.connect(main_app.go_to_next_prompts_page)
    main_app.btn_prompts_next_page.setEnabled(False)
    pagination_row.addWidget(main_app.btn_prompts_next_page)
    
    layout.addLayout(pagination_row)
    
    # Pagination variables
    main_app.prompts_per_page = 200
    main_app.current_prompts_page = 1
    main_app.total_prompts_pages = 1
    main_app.all_prompts_data = []
    main_app.global_task_progress = {}
    
    # Prompts table
    main_app.prompts_table = QTableWidget()
    main_app.prompts_table.setColumnCount(6)
    main_app.prompts_table.setHorizontalHeaderLabels([
        "☑", "Prompt (Lời nhắc)", "Tiến độ", "Trạng thái", "Review", "Chạy lại"
    ])
    
    main_app.prompts_table.setColumnWidth(0, 35)
    main_app.prompts_table.setColumnWidth(2, 200)
    main_app.prompts_table.setColumnWidth(3, 80)
    main_app.prompts_table.setColumnWidth(4, 80)
    main_app.prompts_table.setColumnWidth(5, 100)
    
    main_app.prompts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    main_app.prompts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    main_app.prompts_table.verticalHeader().setVisible(True)
    main_app.prompts_table.verticalHeader().setDefaultSectionSize(24)
    main_app.prompts_table.verticalHeader().setStyleSheet("QHeaderView::section { background: #F5F7FA; color: #333; }")
    
    main_app.prompts_table.horizontalHeader().sectionClicked.connect(main_app.on_header_clicked)
    main_app.prompts_table.setWordWrap(False)
    main_app.prompts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    
    layout.addWidget(main_app.prompts_table)
    
    # Control buttons
    main_app.normal_control_frame = QWidget()
    btn_layout = QHBoxLayout(main_app.normal_control_frame)
    btn_layout.setAlignment(Qt.AlignCenter)
    btn_layout.setSpacing(10)
    
    main_app.btn_start = QPushButton("Bắt đầu")
    main_app.btn_start.setFixedSize(120, 36)
    main_app.btn_start.setObjectName("startButton")
    main_app.btn_start.clicked.connect(main_app.on_start)
    btn_layout.addWidget(main_app.btn_start)
    
    main_app.btn_pause = QPushButton("Tạm dừng")
    main_app.btn_pause.setFixedSize(100, 36)
    main_app.btn_pause.setEnabled(False)
    main_app.btn_pause.clicked.connect(main_app.on_pause)
    btn_layout.addWidget(main_app.btn_pause)
    
    main_app.btn_stop = QPushButton("Dừng")
    main_app.btn_stop.setFixedSize(80, 36)
    main_app.btn_stop.setEnabled(False)
    main_app.btn_stop.clicked.connect(main_app.on_stop)
    btn_layout.addWidget(main_app.btn_stop)
    
    layout.addWidget(main_app.normal_control_frame)
    
    return widget


def build_logs_panel(main_app):
    """Build logs panel for Video tab"""
    from PySide6.QtWidgets import QTextEdit
    
    logs_widget = QWidget()
    logs_layout = QVBoxLayout(logs_widget)
    logs_layout.setContentsMargins(5, 5, 5, 5)
    logs_layout.setSpacing(5)
    
    # Logs header
    logs_header = QHBoxLayout()
    
    logs_label = QLabel("📝 Logs")
    logs_label.setStyleSheet("font-weight: bold; font-size: 14px;")
    logs_header.addWidget(logs_label)
    
    logs_header.addStretch()
    
    main_app.btn_clear_log = QPushButton("🗑️ Xóa log")
    main_app.btn_clear_log.setFixedSize(90, 28)
    main_app.btn_clear_log.clicked.connect(main_app.clear_log)
    logs_header.addWidget(main_app.btn_clear_log)
    
    main_app.btn_export_log = QPushButton("💾 Lưu log")
    main_app.btn_export_log.setFixedSize(90, 28)
    main_app.btn_export_log.clicked.connect(main_app.export_log)
    logs_header.addWidget(main_app.btn_export_log)
    
    logs_layout.addLayout(logs_header)
    
    # Log text area
    main_app.logs_display = QTextEdit()
    main_app.logs_display.setReadOnly(True)
    main_app.logs_display.setStyleSheet("""
        QTextEdit {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 12px;
        }
    """)
    logs_layout.addWidget(main_app.logs_display)
    
    return logs_widget

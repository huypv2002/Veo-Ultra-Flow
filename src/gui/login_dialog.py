"""
Login dialog và credential management.
Tách từ gui_app_mac.py - chứa show_standalone_login() và các hàm credentials.
"""

import json
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt, QTimer

from iting_api import authenticate_iting_user, ItingAPI


def load_saved_credentials():
    """Load saved credentials từ file temp"""
    try:
        cred_file = Path.cwd() / ".login_temp"
        if cred_file.exists():
            with open(cred_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("username", ""), data.get("password", ""), data.get("remember", False)
    except Exception:
        pass
    return "", "", False


def save_credentials(username, password, remember):
    """Save credentials vào file temp (chỉ khi remember=True)"""
    try:
        cred_file = Path.cwd() / ".login_temp"
        if remember:
            with open(cred_file, 'w', encoding='utf-8') as f:
                json.dump({"username": username, "password": password, "remember": True}, f)
        else:
            if cred_file.exists():
                cred_file.unlink()
    except Exception:
        pass


def save_key_credentials(activation_key: str):
    """Save activation key vào file temp để tự động login lần sau"""
    try:
        key_file = Path.cwd() / ".key_temp"
        with open(key_file, 'w', encoding='utf-8') as f:
            json.dump({"activation_key": activation_key, "saved_at": datetime.now().isoformat()}, f)
    except Exception as e:
        print(f"Error saving key credentials: {e}")


def load_saved_key() -> str:
    """Load saved activation key từ file temp"""
    try:
        key_file = Path.cwd() / ".key_temp"
        if key_file.exists():
            with open(key_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("activation_key", "")
    except Exception as e:
        print(f"Error loading saved key: {e}")
    return ""


def clear_saved_key():
    """Xóa saved key khi logout hoặc key hết hạn"""
    try:
        key_file = Path.cwd() / ".key_temp"
        if key_file.exists():
            key_file.unlink()
    except Exception:
        pass

def show_standalone_login():
    """Hiển thị login form TRƯỚC khi tạo main window - UI ĐẸP & ĐÁNG TIN CẬY"""
    dialog = QDialog()
    dialog.setWindowTitle("Google Labs Flow - Đăng nhập")
    dialog.setFixedSize(500, 720)  # Tăng chiều cao để chứa error message mà không làm UI bị đẩy
    dialog.setWindowModality(Qt.ApplicationModal)
    
    # Ensure dialog hiển thị chính xác
    dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
    dialog.raise_()
    dialog.activateWindow()
    
    # Modern gradient background
    dialog.setStyleSheet("""
        QDialog { 
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #f8f9fa, stop:1 #e9ecef);
            border: 2px solid #dee2e6;
            border-radius: 12px;
        }
        QLabel { 
            color: #212529; 
            font-family: 'Segoe UI', Arial;
        }
        QLineEdit { 
            padding: 12px 16px; 
            border: 2px solid #dee2e6; 
            border-radius: 8px; 
            font-size: 14px; 
            background: #ffffff;
            selection-background-color: #007bff;
        }
        QLineEdit:focus { 
            border: 2px solid #007bff; 
            background: #ffffff;
            outline: none;
        }
        QLineEdit:hover {
            border: 2px solid #6c757d;
        }
        QCheckBox {
            color: #6c757d;
            font-size: 12px;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 2px solid #dee2e6;
            border-radius: 3px;
            background: #ffffff;
        }
        QCheckBox::indicator:checked {
            background: #007bff;
            border: 2px solid #007bff;
        }
        QPushButton { 
            padding: 12px 24px; 
            border: none; 
            border-radius: 6px; 
            font-weight: 600; 
            font-size: 14px;
            min-width: 100px;
        }
        QPushButton:hover {
            transform: translateY(-1px);
        }
        QPushButton:pressed {
            transform: translateY(1px);
        }
    """)
    
    # ✅ LOAD SAVED CREDENTIALS TRƯỚC KHI TẠO UI
    saved_username, saved_password, saved_remember = load_saved_credentials()
    
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(50, 40, 50, 40)
    layout.setSpacing(18)
    
    # Header với icon
    header_layout = QVBoxLayout()
    
    # Icon/Logo placeholder (nhỏ lại cho gọn)
    logo_label = QLabel("🚀")
    logo_label.setStyleSheet("font-size: 32px; margin-bottom: 4px;")
    logo_label.setAlignment(Qt.AlignCenter)
    header_layout.addWidget(logo_label)
    
    # Title
    title = QLabel("Google Labs Flow")
    title.setStyleSheet("""
        font-size: 24px; 
        font-weight: 700; 
        color: #212529;
        margin-bottom: 4px;
        letter-spacing: 0.5px;
    """)
    title.setAlignment(Qt.AlignCenter)
    header_layout.addWidget(title)
    
    # Subtitle
    subtitle = QLabel("Đăng nhập để tiếp tục sử dụng")
    subtitle.setStyleSheet("""
        font-size: 13px; 
        color: #6c757d;
        margin-bottom: 20px;
        font-weight: 400;
    """)
    subtitle.setAlignment(Qt.AlignCenter)
    header_layout.addWidget(subtitle)
    

    
    # Function hiển thị popup nhập key
    def show_key_login_popup():
        key_dialog = QDialog(dialog)
        key_dialog.setWindowTitle("🔑 Đăng nhập bằng Key")
        key_dialog.setFixedSize(450, 280)
        key_dialog.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                border-radius: 12px;
            }
            QLabel {
                color: #212529;
            }
            QLineEdit {
                padding: 12px 16px;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                font-size: 14px;
                background: #ffffff;
            }
            QLineEdit:focus {
                border: 2px solid #007bff;
            }
            QPushButton {
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                font-weight: 600;
                font-size: 14px;
            }
        """)
        
        key_layout = QVBoxLayout(key_dialog)
        key_layout.setContentsMargins(30, 25, 30, 25)
        key_layout.setSpacing(16)
        
        # Header
        key_header = QLabel("🔑 Nhập Key Đăng Nhập")
        key_header.setStyleSheet("font-size: 18px; font-weight: 700; color: #212529;")
        key_header.setAlignment(Qt.AlignCenter)
        key_layout.addWidget(key_header)
        
        # Description
        key_desc = QLabel("Nhập key được cấp bởi admin để đăng nhập nhanh")
        key_desc.setStyleSheet("font-size: 12px; color: #6c757d;")
        key_desc.setAlignment(Qt.AlignCenter)
        key_layout.addWidget(key_desc)
        
        # Key input field
        key_input = QLineEdit()
        key_input.setPlaceholderText("Nhập key của bạn tại đây...")
        key_input.setFixedHeight(45)
        
        # ✅ AUTO-FILL từ saved key (nếu có)
        saved_key = load_saved_key()
        if saved_key:
            key_input.setText(saved_key)
        
        key_layout.addWidget(key_input)
        
        # Error message label
        key_error_label = QLabel("")
        key_error_label.setStyleSheet("color: #dc3545; font-size: 12px;")
        key_error_label.setAlignment(Qt.AlignCenter)
        key_error_label.setWordWrap(True)
        key_layout.addWidget(key_error_label)
        
        # Buttons
        key_btn_layout = QHBoxLayout()
        key_btn_layout.setSpacing(12)
        
        key_cancel_btn = QPushButton("Hủy")
        key_cancel_btn.setFixedHeight(40)
        key_cancel_btn.setStyleSheet("""
            QPushButton {
                background: #6c757d;
                color: white;
            }
            QPushButton:hover {
                background: #5a6268;
            }
        """)
        key_cancel_btn.clicked.connect(key_dialog.reject)
        key_btn_layout.addWidget(key_cancel_btn)
        
        key_submit_btn = QPushButton("🚀 Đăng nhập")
        key_submit_btn.setFixedHeight(40)
        key_submit_btn.setStyleSheet("""
            QPushButton {
                background: #28a745;
                color: white;
            }
            QPushButton:hover {
                background: #218838;
            }
        """)
        key_btn_layout.addWidget(key_submit_btn)
        
        key_layout.addLayout(key_btn_layout)
        
        # Function xử lý đăng nhập bằng key
        def do_key_login():
            entered_key = key_input.text().strip()
            if not entered_key:
                key_error_label.setText("⚠️ Vui lòng nhập key")
                return
            
            # Loading state
            key_submit_btn.setText("⏳ Đang xác thực...")
            key_submit_btn.setEnabled(False)
            key_cancel_btn.setEnabled(False)
            key_error_label.setText("")
            
            # Lấy machine_code
            try:
                machine_code = ItingAPI()._get_machine_secret()
            except Exception:
                machine_code = current_machine_code  # Fallback to already computed value
            
            # Gọi API authenticate với key
            from supabase_manager import supabase_manager
            success, message, data = supabase_manager.authenticate_with_key(entered_key, machine_code)
            
            if success:
                # ✅ ĐĂNG NHẬP BẰNG KEY THÀNH CÔNG
                
                # Kiểm tra thông tin subscription sau khi login
                subscription = data.get("subscription", {})
                days_remaining = subscription.get("days_remaining")
                
                # Hiển thị thông báo nếu gói sắp hết hạn
                if days_remaining is not None and days_remaining <= 7 and days_remaining < 999999:
                    warning_title = "⚠️ Cảnh Báo Gói Dịch Vụ"
                    if days_remaining <= 1:
                        warning_title = "🚨 Gói Dịch Vụ Sắp Hết Hạn"
                        icon = QMessageBox.Critical
                    elif days_remaining <= 3:
                        icon = QMessageBox.Warning
                    else:
                        icon = QMessageBox.Information
                    
                    warning_box = QMessageBox(icon, warning_title,
                        f"Gói dịch vụ của bạn sẽ hết hạn trong {days_remaining} ngày.\n\n"
                        "Vui lòng liên hệ admin để gia hạn để tránh gián đoạn sử dụng.\n\n"
                        "Ứng dụng sẽ tự động thoát khi gói hết hạn.",
                        QMessageBox.Ok, key_dialog)
                    warning_box.exec()
                
                # ✅ LƯU KEY VÀO FILE ĐỂ TỰ ĐỘNG LOGIN LẦN SAU
                save_key_credentials(entered_key)
                
                # Set login_data và đóng cả 2 dialog
                login_data["success"] = True
                login_data["username"] = data.get("user", {}).get("username", f"Key-{entered_key[:8]}")
                login_data["data"] = data
                login_data["remember"] = True  # Key login luôn remember
                login_data["saved_username"] = ""
                login_data["saved_password"] = ""
                login_data["is_key_login"] = True
                login_data["activation_key"] = entered_key
                
                key_dialog.accept()  # Đóng key popup
                dialog.accept()      # Đóng login dialog chính
                
            else:
                # ❌ ĐĂNG NHẬP THẤT BẠI
                error_code = data.get("error_code", "")
                
                if error_code == "KEY_EXPIRED":
                    key_error_label.setStyleSheet("color: #dc3545; font-size: 12px; font-weight: bold;")
                    key_error_label.setText(f"🚨 {message}")
                elif error_code == "MACHINE_MISMATCH":
                    key_error_label.setStyleSheet("color: #dc3545; font-size: 12px; font-weight: bold;")
                    key_error_label.setText(f"⚠️ {message}")
                else:
                    key_error_label.setStyleSheet("color: #dc3545; font-size: 12px;")
                    key_error_label.setText(f"❌ {message}")
                
                # Restore button states
                key_submit_btn.setText("🚀 Đăng nhập")
                key_submit_btn.setEnabled(True)
                key_cancel_btn.setEnabled(True)
                key_input.setFocus()
                key_input.selectAll()
        
        key_submit_btn.clicked.connect(do_key_login)
        key_input.returnPressed.connect(do_key_login)
        
        key_input.setFocus()
        key_dialog.exec()
    

    
    layout.addLayout(header_layout)
    
    # Form fields với labels đẹp hơn
    # Username field
    username_container = QVBoxLayout()
    username_container.setSpacing(6)
    
    username_label = QLabel("Tên đăng nhập")
    username_label.setStyleSheet("""
        font-size: 13px; 
        color: #495057; 
        font-weight: 600;
        margin-bottom: 4px;
    """)
    username_container.addWidget(username_label)
    
    username_input = QLineEdit()
    username_input.setPlaceholderText("Nhập tên đăng nhập của bạn")
    username_input.setFixedHeight(45)
    
    # ✅ AUTO-FILL từ saved credentials
    if saved_username:
        username_input.setText(saved_username)
    
    username_container.addWidget(username_input)
    layout.addLayout(username_container)
    
    # Password field
    password_container = QVBoxLayout()
    password_container.setSpacing(6)
    
    password_label = QLabel("Mật khẩu")
    password_label.setStyleSheet("""
        font-size: 13px; 
        color: #495057; 
        font-weight: 600;
        margin-bottom: 4px;
    """)
    password_container.addWidget(password_label)
    
    password_input = QLineEdit()
    password_input.setEchoMode(QLineEdit.Password)
    password_input.setPlaceholderText("Nhập mật khẩu")
    password_input.setFixedHeight(45)
    
    # ✅ AUTO-FILL từ saved credentials
    if saved_password:
        password_input.setText(saved_password)
    
    password_container.addWidget(password_input)
    layout.addLayout(password_container)
    
    # Machine code field (mã máy)
    machine_container = QVBoxLayout()
    machine_container.setSpacing(6)
    
    machine_label_title = QLabel("Mã máy (cố định cho 1 máy)")
    machine_label_title.setStyleSheet("""
        font-size: 13px; 
        color: #495057; 
        font-weight: 600;
        margin-bottom: 4px;
    """)
    machine_container.addWidget(machine_label_title)
    
    from iting_api import ItingAPI
    try:
        api = ItingAPI()
        current_machine_code = api._get_machine_secret()
    except Exception:
        current_machine_code = "UNKNOWN"
    
    # Container cho machine code với nút copy
    machine_code_row = QHBoxLayout()
    machine_code_row.setSpacing(8)
    
    machine_code_input = QLineEdit()
    # Đặt sẵn mã máy vào ô nhập để user chỉ cần copy (không thể sửa)
    machine_code_input.setText(current_machine_code)
    machine_code_input.setPlaceholderText("Mã máy do admin gắn. Có thể copy và gửi cho admin.")
    machine_code_input.setFixedHeight(45)
    machine_code_input.setReadOnly(True)
    
    # Nút copy clipboard
    copy_btn = QPushButton("📋")
    copy_btn.setToolTip("Copy mã máy vào clipboard")
    copy_btn.setFixedWidth(50)
    copy_btn.setFixedHeight(45)
    copy_btn.setStyleSheet("""
        QPushButton {
            background: #007bff; 
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 16px;
        }
        QPushButton:hover {
            background: #0056b3;
        }
        QPushButton:pressed {
            background: #004085;
        }
    """)
    
    # Function copy clipboard
    def copy_machine_code():
        from PySide6.QtGui import QClipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(current_machine_code)
        copy_btn.setText("✓")
        copy_btn.setStyleSheet("""
            QPushButton {
                background: #28a745; 
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: 600;
                font-size: 16px;
            }
        """)
        QTimer.singleShot(2000, lambda: (
            copy_btn.setText("📋"),
            copy_btn.setStyleSheet("""
                QPushButton {
                    background: #007bff; 
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background: #0056b3;
                }
                QPushButton:pressed {
                    background: #004085;
                }
            """)
        ))
    
    copy_btn.clicked.connect(copy_machine_code)
    
    # Double-click để copy
    def on_double_click(event):
        QLineEdit.mouseDoubleClickEvent(machine_code_input, event)
        copy_machine_code()
    
    machine_code_input.mouseDoubleClickEvent = on_double_click
    
    machine_code_row.addWidget(machine_code_input)
    machine_code_row.addWidget(copy_btn)
    machine_container.addLayout(machine_code_row)
    
    # Gợi ý ngắn gọn
    machine_hint = QLabel("👉 Mã máy đã được tự động điền. Nhấp đúp hoặc click nút 📋 để copy.")
    machine_hint.setStyleSheet("font-size: 11px; color: #6c757d;")
    machine_hint.setWordWrap(True)
    machine_container.addWidget(machine_hint)
    
    layout.addLayout(machine_container)
    
    # Remember checkbox với style đẹp hơn
    remember_checkbox = QCheckBox("🔐 Ghi nhớ thông tin đăng nhập")
    remember_checkbox.setChecked(saved_remember)
    remember_checkbox.setStyleSheet("""
        QCheckBox {
            color: #495057;
            font-size: 12px;
            font-weight: 500;
            padding: 8px 0px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
        }
    """)
    layout.addWidget(remember_checkbox)
    
    # ✅ Link "Đăng nhập bằng key có sẵn" - Đặt dưới checkbox remember
    key_login_link = QLabel("Đăng nhập phần mềm bằng key có sẵn")
    key_login_link.setStyleSheet("""
        QLabel {
            color: #007bff;
            font-size: 12px;
            font-weight: 500;
            text-decoration: underline;
            padding: 4px 0px;
        }
        QLabel:hover {
            color: #0056b3;
        }
    """)
    key_login_link.setAlignment(Qt.AlignCenter)
    key_login_link.setCursor(Qt.PointingHandCursor)
    key_login_link.mousePressEvent = lambda e: show_key_login_popup()
    layout.addWidget(key_login_link)
    
    # Error message với chiều cao cố định (gấp đôi) để không làm dịch chuyển UI
    # Luôn chiếm không gian để không làm UI bị dịch chuyển
    msg_label = QLabel("")
    msg_label.setWordWrap(True)
    msg_label.setFixedHeight(20)  # Chiều cao cố định gấp đôi (30px -> 60px)
    msg_label.setStyleSheet("""
        color: #dc3545; 
        font-size: 12px;
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 8px 12px;
        margin: 8px 0px;
    """)
    layout.addWidget(msg_label)
    
    # Function để hiển thị/ẩn error message
    def show_error(text):
        if text:
            msg_label.setText(text)
            msg_label.setStyleSheet("""
                color: #dc3545; 
                font-size: 12px;
                background: #f8d7da;
                border: 1px solid #f5c6cb;
                border-radius: 6px;
                padding: 8px 12px;
                margin: 8px 0px;
            """)
        else:
            msg_label.setText("")
            msg_label.setStyleSheet("""
                color: transparent; 
                font-size: 12px;
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                margin: 8px 0px;
            """)
    
    # Spacer
    layout.addStretch()
    
    # Buttons với style modern hơn
    btn_layout = QHBoxLayout()
    btn_layout.setSpacing(12)
    
    # Cancel button
    cancel_btn = QPushButton("❌ Thoát")
    cancel_btn.setFixedHeight(45)
    cancel_btn.setStyleSheet("""
        QPushButton {
            background: #6c757d; 
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 13px;
        }
        QPushButton:hover {
            background: #5a6268;
        }
        QPushButton:pressed {
            background: #545b62;
        }
    """)
    btn_layout.addWidget(cancel_btn)
    
    # Login button
    login_btn = QPushButton("🚀 Đăng nhập")
    login_btn.setFixedHeight(45)
    login_btn.setStyleSheet("""
        QPushButton {
            background: #007bff; 
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
        }
        QPushButton:hover {
            background: #0056b3;
        }
        QPushButton:pressed {
            background: #004085;
        }
        QPushButton:disabled {
            background: #adb5bd;
        }
    """)
    btn_layout.addWidget(login_btn)
    
    layout.addLayout(btn_layout)
    
    # Login data to return
    login_data = {"success": False, "username": "", "data": None}
    
    def do_login():
        username = username_input.text().strip()
        password = password_input.text().strip()
        # Luôn lấy mã máy thật của máy hiện tại (không dùng giá trị user nhập)
        try:
            machine_code = ItingAPI()._get_machine_secret()
        except Exception:
            machine_code = machine_code_input.text().strip()
        
        if not username or not password or not machine_code:
            show_error("⚠️ Vui lòng nhập đầy đủ tên đăng nhập, mật khẩu và mã máy")
            return
        
        # Hide error message
        show_error("")
        
        # Loading state
        login_btn.setText("⏳ Đang đăng nhập...")
        login_btn.setEnabled(False)
        cancel_btn.setEnabled(False)
        
        success, message, data = authenticate_iting_user(username, password, machine_code)
        
        if success:
            # ✅ ĐĂNG NHẬP THÀNH CÔNG
            
            # Kiểm tra thông tin subscription sau khi login
            subscription = data.get("subscription", {})
            days_remaining = subscription.get("days_remaining")
            
            # Hiển thị thông báo nếu gói sắp hết hạn
            if days_remaining is not None and days_remaining <= 7:
                warning_title = "⚠️ Cảnh Báo Gói Dịch Vụ"
                if days_remaining <= 1:
                    warning_title = "🚨 Gói Dịch Vụ Sắp Hết Hạn"
                    icon = QMessageBox.Critical
                elif days_remaining <= 3:
                    icon = QMessageBox.Warning
                else:
                    icon = QMessageBox.Information
                
                warning_box = QMessageBox(icon, warning_title,
                    f"Gói dịch vụ của bạn sẽ hết hạn trong {days_remaining} ngày.\n\n"
                    "Vui lòng liên hệ admin để gia hạn để tránh gián đoạn sử dụng.\n\n"
                    "Ứng dụng sẽ tự động thoát khi gói hết hạn.",
                    QMessageBox.Ok, dialog)
                warning_box.exec()
            
            # ✅ SAVE CREDENTIALS VÀO FILE nếu user chọn ghi nhớ
            remember = remember_checkbox.isChecked()
            save_credentials(username, password, remember)
            
            login_data["success"] = True
            login_data["username"] = username
            login_data["data"] = data
            login_data["remember"] = remember
            login_data["saved_username"] = username if remember else ""
            login_data["saved_password"] = password if remember else ""
            
            dialog.accept()
            
        else:
            # ❌ ĐĂNG NHẬP THẤT BẠI
            error_code = data.get("error_code", "")
            
            if error_code == "SUBSCRIPTION_EXPIRED":
                # Hiển thị thông báo đặc biệt cho subscription hết hạn
                error_text = f"🚨 {message}"
                msg_label.setText(error_text)
                msg_label.setStyleSheet("""
                        color: #dc3545; 
                        font-size: 12px;
                        background: #f8d7da;
                        border: 2px solid #dc3545;
                        border-radius: 6px;
                        padding: 12px;
                        margin: 8px 0px;
                        font-weight: bold;
                """)
            else:
                show_error(f"❌ {message}")
            
            # Restore button states
            login_btn.setText("🚀 Đăng nhập")
            login_btn.setEnabled(True)
            cancel_btn.setEnabled(True)
            password_input.setFocus()
            password_input.selectAll()
    
    # Connect events
    login_btn.clicked.connect(do_login)
    cancel_btn.clicked.connect(dialog.reject)
    password_input.returnPressed.connect(do_login)
    username_input.returnPressed.connect(lambda: password_input.setFocus())
    
    # ✅ SMART FOCUS dựa trên saved credentials
    if saved_username:
        password_input.setFocus()  # Username đã có, focus vào password
        password_input.selectAll()   # Select all để user có thể gõ đè ngay
    else:
        username_input.setFocus()   # Chưa có username, focus vào đây
    
    # Show dialog
    result = dialog.exec()
    
    if result == QDialog.Accepted and login_data["success"]:
        return login_data
    else:
        return None



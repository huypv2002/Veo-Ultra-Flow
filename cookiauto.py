"""
Get Cookie JS Tool
- Import Excel to load accounts (email in column 1, password in column 2)
- Get cookies from each account using Playwright browser automation
- Export all cookies to a single .txt file (cookies only, separated by 2 newlines)
- Auto-save last Excel config for convenience
- Profiles stored in tool's own profiles folder
"""

import sys
import os
import json
import asyncio
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# ===== DISABLE WINDOWS BEEP SOUND =====
# Disabled on macOS - no Windows sound APIs available
def _disable_beep():
    """Disable beep sounds (no-op on macOS)"""
    pass

# Ưu tiên import module cùng thư mục gui_app_clone trước, rồi mới tới parent.
# Điều này tránh ăn nhầm các file trùng tên ở thư mục root (vd: proxy_manager.py cũ).
try:
    current_dir = str(Path(__file__).parent)
    parent_dir = str(Path(__file__).parent.parent)
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(1, parent_dir)
except NameError:
    # __file__ doesn't exist in Nuitka compiled mode
    pass

from chrome_profile_utils import (
    resolve_chrome_profile,
    get_cookie_db_candidates,
    is_managed_profile_path,
    get_default_system_chrome_profile_path,
    get_tool_system_chrome_profile_path,
    get_tool_account_profile_path,
    is_shared_system_chrome_profile_path,
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QFileDialog,
    QTextEdit, QProgressBar, QMessageBox, QHeaderView, QCheckBox,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMenu, QSpinBox,
    QPlainTextEdit
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont


# ===== SILENT MESSAGE BOX (No Beep) =====
class SilentMessageBox(QMessageBox):
    """QMessageBox without system beep sound"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disable sound on this message box
        self.setWindowFlags(self.windowFlags())
    
    def showEvent(self, event):
        """Override showEvent to mute beep before and after showing"""
        _disable_beep()
        super().showEvent(event)
        # Also kill sound right after show (in case it was queued)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1, _disable_beep)
        QTimer.singleShot(10, _disable_beep)
        QTimer.singleShot(50, _disable_beep)
    
    @staticmethod
    def information(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        _disable_beep()
        msg = SilentMessageBox(parent)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStandardButtons(buttons)
        msg.setDefaultButton(defaultButton)
        return msg.exec()
    
    @staticmethod
    def warning(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        _disable_beep()
        msg = SilentMessageBox(parent)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStandardButtons(buttons)
        msg.setDefaultButton(defaultButton)
        return msg.exec()
    
    @staticmethod
    def question(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, defaultButton=QMessageBox.NoButton):
        _disable_beep()
        msg = SilentMessageBox(parent)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStandardButtons(buttons)
        msg.setDefaultButton(defaultButton)
        return msg.exec()
    
    @staticmethod
    def critical(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        _disable_beep()
        msg = SilentMessageBox(parent)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStandardButtons(buttons)
        msg.setDefaultButton(defaultButton)
        return msg.exec()

# ===== CONFIG =====
def _get_tool_dir():
    """
    Get the tool directory, handling:
    - Normal Python execution (dev mode)
    - PyInstaller frozen executable
    - Nuitka compiled executable
    """
    # Method 1: Check for Nuitka compiled (has __compiled__ or __nuitka_binary_dir)
    if hasattr(sys, '__compiled__') or hasattr(sys, '__nuitka_binary_dir'):
        # Nuitka: sys.executable is the .exe file
        return Path(sys.executable).parent
    
    # Method 2: Check for PyInstaller frozen
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    
    # Method 3: Check if running as .exe (fallback for any compiled exe)
    if sys.executable.lower().endswith('.exe') and 'python' not in sys.executable.lower():
        return Path(sys.executable).parent
    
    # Method 4: Normal Python script execution
    try:
        return Path(__file__).parent
    except NameError:
        # __file__ doesn't exist, use current working directory as last resort
        return Path.cwd()


TOOL_DIR = _get_tool_dir()

# ===== APP DATA DIRECTORY (Fixed location in AppData) =====
# Store all app data (profiles, config, db) in a fixed location
# This ensures:
# - Data won't be deleted when moving the exe
# - Data won't be cleaned by junk cleaners
# - User won't accidentally delete data
APP_NAME = "GetCookieVeo3"
APP_DATA_DIR = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))) / APP_NAME

# === DEBUG: Print directories on startup ===
print(f"[DEBUG] TOOL_DIR (exe location) = {TOOL_DIR}")
print(f"[DEBUG] APP_DATA_DIR (data storage) = {APP_DATA_DIR}")
print(f"[DEBUG] sys.executable = {sys.executable}")
try:
    print(f"[DEBUG] __file__ = {__file__}")
except NameError:
    print("[DEBUG] __file__ = N/A (compiled mode)")

# === DATA PATHS (stored in AppData, not next to exe) ===
PROFILES_DIR = APP_DATA_DIR / "profiles"
CONFIG_FILE = APP_DATA_DIR / "config.json"
DB_FILE = APP_DATA_DIR / "accounts.db"


def _resolved_profile_storage_path(profile_path: str) -> Path:
    info = resolve_chrome_profile(profile_path)
    return Path(info["profile_storage_path"] or profile_path).expanduser()
DEFAULT_EXPORT_NAME = "cookies_export.txt"

# === ENSURE ALL REQUIRED DIRECTORIES AND FILES EXIST ===
def _init_required_files():
    """Create all required directories and files on startup"""
    try:
        # 1. Create main AppData directory
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[INIT] App data dir: {APP_DATA_DIR} (exists: {APP_DATA_DIR.exists()})")
        
        # 2. Create profiles directory
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[INIT] Profiles dir: {PROFILES_DIR} (exists: {PROFILES_DIR.exists()})")
        
        # 3. Create empty config.json if not exists
        if not CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            print(f"[INIT] Created config.json")
        else:
            print(f"[INIT] Config file: {CONFIG_FILE} (exists: True)")
        
        # 4. DB will be initialized separately by init_db()
        print(f"[INIT] DB file path: {DB_FILE}")
        
    except Exception as e:
        print(f"[INIT ERROR] {e}")

# Run initialization
_init_required_files()



def load_config() -> dict:
    """Load saved config"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config: dict):
    """Save config"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save config: {e}")


def init_db():
    """Initialize SQLite database"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS accounts
                     (email TEXT PRIMARY KEY, password TEXT, profile_path TEXT, created_at TEXT, cookies TEXT, api_key TEXT)''')
        # ✅ Thêm cột cookies nếu chưa có (migration)
        try:
            c.execute("ALTER TABLE accounts ADD COLUMN cookies TEXT")
        except sqlite3.OperationalError:
            pass  # Cột đã tồn tại
        # ✅ Thêm cột api_key nếu chưa có (migration)
        try:
            c.execute("ALTER TABLE accounts ADD COLUMN api_key TEXT")
        except sqlite3.OperationalError:
            pass  # Cột đã tồn tại
        # ✅ Thêm cột credits nếu chưa có (migration)
        try:
            c.execute("ALTER TABLE accounts ADD COLUMN credits INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Cột đã tồn tại
        # ✅ Thêm cột proxy_config nếu chưa có (migration)
        try:
            c.execute("ALTER TABLE accounts ADD COLUMN proxy_config TEXT")
        except sqlite3.OperationalError:
            pass  # Cột đã tồn tại
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Init Error: {e}")

def db_add_account(email: str, password: str, profile_path: str):
    """Add or update account in DB while preserving cookies/credits/api_key/proxy_config."""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        email = (email or "").strip()
        password = password or ""
        profile_path = profile_path or ""
        c.execute("""
            INSERT INTO accounts (email, password, profile_path, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                password = excluded.password,
                profile_path = excluded.profile_path,
                created_at = excluded.created_at
        """, (email, password, profile_path, created_at))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Add Error: {e}")

def db_get_all_accounts() -> List[dict]:
    """Get all accounts from DB"""
    accounts = []
    try:
        import sqlite3
        if not DB_FILE.exists():
            return []
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        def _normalize_profile_path(email_value: str, raw_profile_path: str) -> str:
            current = (raw_profile_path or "").strip()
            if not current:
                migrated = get_tool_account_profile_path(email_value)
                try:
                    c.execute(
                        "UPDATE accounts SET profile_path = ? WHERE email = ?",
                        (migrated, email_value),
                    )
                    conn.commit()
                    print(f"[DB MIGRATE EMPTY] {email_value}: -> {migrated}")
                except Exception as migrate_err:
                    print(f"[DB MIGRATE EMPTY ERROR] {email_value}: {migrate_err}")
                return migrated
            if is_shared_system_chrome_profile_path(current):
                migrated = get_tool_account_profile_path(email_value)
                try:
                    c.execute(
                        "UPDATE accounts SET profile_path = ? WHERE email = ?",
                        (migrated, email_value),
                    )
                    conn.commit()
                    print(f"[DB MIGRATE] {email_value}: {current} -> {migrated}")
                except Exception as migrate_err:
                    print(f"[DB MIGRATE ERROR] {email_value}: {migrate_err}")
                return migrated
            return current

        # Try to select credits and proxy_config as well
        try:
            c.execute("SELECT email, password, profile_path, credits, proxy_config FROM accounts ORDER BY created_at DESC")
            for row in c.fetchall():
                normalized_profile_path = _normalize_profile_path(row[0], row[2])
                proxy_config = None
                if row[4]:  # proxy_config column
                    try:
                        proxy_config = json.loads(row[4])
                    except:
                        pass
                accounts.append({
                    'email': row[0],
                    'password': row[1],
                    'profile_path': normalized_profile_path,
                    'credits': row[3] if row[3] is not None else 0,
                    'proxy_config': proxy_config,
                    'selected': True,
                    'profile_edited': False  # ✅ Flag để track đã "Sửa Profile" (login thủ công) chưa
                })
        except sqlite3.OperationalError:
             # Fallback if credits/proxy_config column doesn't exist yet
             try:
                 c.execute("SELECT email, password, profile_path, credits FROM accounts ORDER BY created_at DESC")
                 for row in c.fetchall():
                    normalized_profile_path = _normalize_profile_path(row[0], row[2])
                    accounts.append({
                        'email': row[0],
                        'password': row[1],
                        'profile_path': normalized_profile_path,
                        'credits': row[3] if row[3] is not None else 0,
                        'proxy_config': None,
                        'selected': True,
                        'profile_edited': False  # ✅ Flag để track đã "Sửa Profile" (login thủ công) chưa
                    })
             except sqlite3.OperationalError:
                 c.execute("SELECT email, password, profile_path FROM accounts ORDER BY created_at DESC")
                 for row in c.fetchall():
                    normalized_profile_path = _normalize_profile_path(row[0], row[2])
                    accounts.append({
                        'email': row[0],
                        'password': row[1],
                        'profile_path': normalized_profile_path,
                        'credits': 0,
                        'proxy_config': None,
                        'selected': True,
                        'profile_edited': False  # ✅ Flag để track đã "Sửa Profile" (login thủ công) chưa
                    })
        conn.close()
    except Exception as e:
        print(f"DB Get Error: {e}")
    return accounts

def db_update_account_credits(email: str, credits: int):
    """Update credits for an account"""
    try:
        import sqlite3
        if not DB_FILE.exists():
            return False
            
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE accounts SET credits = ? WHERE email = ?", (credits, email))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Update Credits Error: {e}")
        return False

def db_delete_account(email: str):
    """Delete account from DB"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        email = email.strip()
        c.execute("DELETE FROM accounts WHERE email=?", (email,))
        rows = c.rowcount
        conn.commit()
        conn.close()
        print(f"[DB] Deleted {rows} row(s) for {email}")
    except Exception as e:
        print(f"DB Delete Error: {e}")

def db_update_account_cookies(email: str, cookies_json: str):
    """Update cookies for an account (lưu 3 cookie cần thiết)"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE accounts SET cookies = ? WHERE email = ?", (cookies_json, email))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Update Cookies Error: {e}")
        return False

def db_get_account_cookies(email: str) -> str:
    """Get cookies for an account"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT cookies FROM accounts WHERE email = ?", (email,))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
        return ""
    except Exception as e:
        print(f"DB Get Cookies Error: {e}")
        return ""

def db_get_account_api_key(email: str) -> str:
    """Get API key for an account"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT api_key FROM accounts WHERE email = ?", (email,))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
        return ""
    except Exception as e:
        print(f"DB Get API Key Error: {e}")
        return ""

def db_update_account_api_key(email: str, api_key: str):
    """Update API key for an account"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE accounts SET api_key = ? WHERE email = ?", (api_key, email))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Update API Key Error: {e}")
        return False

def db_update_account_proxy_config(email: str, proxy_config: Optional[Dict[str, str]]):
    """Update proxy config for an account"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        proxy_json = json.dumps(proxy_config) if proxy_config else None
        c.execute("UPDATE accounts SET proxy_config = ? WHERE email = ?", (proxy_json, email))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Update Proxy Config Error: {e}")
        return False

def db_get_account_proxy_config(email: str) -> Optional[Dict[str, str]]:
    """Get proxy config for an account"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT proxy_config FROM accounts WHERE email = ?", (email,))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except:
                return None
        return None
    except Exception as e:
        print(f"DB Get Proxy Config Error: {e}")
        return None


class AddAccountDialog(QDialog):
    """Dialog to add new account with Email/Pass"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thêm Tài Khoản Mới")
        self.setMinimumWidth(560)
        
        layout = QVBoxLayout(self)
        
        # Form
        form = QFormLayout()
        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("example@gmail.com")
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.Password)
        self.txt_password.setPlaceholderText("Password (tùy chọn)")
        self.txt_profile_path = QLineEdit()
        self.txt_profile_path.setPlaceholderText("Để trống = tự tạo profile riêng cố định cho account này (khuyên dùng)")
        self.txt_profile_path.setText("")
        self.btn_browse_profile = QPushButton("Chọn...")
        self.btn_browse_profile.clicked.connect(self._browse_profile_path)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.txt_profile_path)
        profile_row.addWidget(self.btn_browse_profile)
        
        form.addRow("Email:", self.txt_email)
        form.addRow("Password:", self.txt_password)
        form.addRow("Profile Chrome:", profile_row)
        layout.addLayout(form)
        
        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_add_run = QPushButton("⚡ Thêm & Chạy Ngay")
        self.btn_add_run.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 6px 12px;")
        self.btn_add_run.clicked.connect(self.accept)
        
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_add_run)
        layout.addLayout(btn_box)

    def _browse_profile_path(self):
        selected = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục profile Chrome",
            str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome")
        )
        if selected:
            self.txt_profile_path.setText(selected)
        
    def get_data(self):
        return (
            self.txt_email.text().strip(),
            self.txt_password.text().strip(),
            self.txt_profile_path.text().strip(),
        )


class ManualCookieDialog(QDialog):
    """Dialog để nhập cookie thủ công (Paste JSON/Netscape/Header)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nhập Cookie Thủ Công")
        self.setMinimumSize(700, 550)
        self.parsed_cookies = []  # List of cookie dicts
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # 1. Email/Name field
        form = QFormLayout()
        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("example@gmail.com hoặc tên tùy chỉnh (tùy chọn)")
        form.addRow("Email / Tên:", self.txt_email)
        layout.addLayout(form)
        
        # 2. Cookie Input Area
        lbl_guide = QLabel("Dán cookie vào bên dưới (Hỗ trợ: JSON list, JSON dict, Netscape format, hoặc Header string 'key=value;...')")
        lbl_guide.setStyleSheet("color: #666; font-style: italic; font-size: 11px;")
        layout.addWidget(lbl_guide)
        
        self.txt_cookie = QPlainTextEdit()
        self.txt_cookie.setPlaceholderText(
            'Ví dụ JSON: [{"domain": "labs.google", "name": "__Secure-next-auth.session-token", "value": "..."}]\n'
            'Hoặc Header: __Secure-next-auth.session-token=...; __Secure-1PSID=...; __Secure-1PSIDTS=...'
        )
        self.txt_cookie.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.txt_cookie.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.txt_cookie)
        
        # 3. Validation Status
        self.lbl_status = QLabel("Trạng thái: Chưa có dữ liệu")
        self.lbl_status.setStyleSheet("color: #666; font-weight: bold;")
        layout.addWidget(self.lbl_status)
        
        # 4. Preview Important Cookies
        self.preview_area = QTextEdit()
        self.preview_area.setReadOnly(True)
        self.preview_area.setMaximumHeight(120)
        self.preview_area.setStyleSheet("font-family: Consolas; font-size: 11px; color: #28a745; background: #f0f0f0;")
        layout.addWidget(self.preview_area)
        
        # 5. Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("💾 Lưu Cookie")
        self.btn_save.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold; padding: 8px 15px;")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.accept)
        
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_save)
        layout.addLayout(btn_box)
    
    def _on_text_changed(self):
        """Parse và validate cookie realtime"""
        text = self.txt_cookie.toPlainText().strip()
        if not text:
            self.lbl_status.setText("Trạng thái: Chưa có dữ liệu")
            self.lbl_status.setStyleSheet("color: #666;")
            self.preview_area.clear()
            self.btn_save.setEnabled(False)
            self.parsed_cookies = []
            return

        try:
            # Import parse function from complete_flow
            from complete_flow import _parse_cookie_string
            
            # 1. Thử parse JSON list (Cookie-Editor format)
            if (text.startswith('[') and text.endswith(']')):
                try:
                    data = json.loads(text)
                    if isinstance(data, list):
                        self.parsed_cookies = data
                        self._validate_cookies("JSON List")
                        return
                except:
                    pass
            
            # 2. Thử parse JSON dict
            if (text.startswith('{') and text.endswith('}')):
                try:
                    data = json.loads(text)
                    if isinstance(data, dict):
                        # Convert dict to list of cookie objects
                        self.parsed_cookies = [{"name": k, "value": v, "domain": "labs.google"} for k, v in data.items()]
                        self._validate_cookies("JSON Dict")
                        return
                except:
                    pass
            
            # 3. Thử parse Netscape format (Tab separated)
            if "\t" in text:
                cookies = []
                lines = text.split('\n')
                if len(lines) > 0 and len(lines[0].split('\t')) >= 6:
                    for line in lines:
                        parts = line.strip().split('\t')
                        if len(parts) >= 6:
                            val_idx = 6 if len(parts) >= 7 else 5
                            if len(parts) > val_idx:
                                cookies.append({
                                    "domain": parts[0],
                                    "name": parts[5],
                                    "value": parts[val_idx]
                                })
                if cookies:
                    self.parsed_cookies = cookies
                    self._validate_cookies("Netscape Format")
                    return
            
            # 4. Fallback: Parse Header String hoặc dùng _parse_cookie_string
            parsed_dict = _parse_cookie_string(text)
            if parsed_dict:
                # Convert dict to list of cookie objects
                self.parsed_cookies = [{"name": k, "value": v, "domain": "labs.google"} for k, v in parsed_dict.items()]
                self._validate_cookies("Header String")
                return
            
            self.lbl_status.setText("Trạng thái: ❌ Không nhận dạng được định dạng")
            self.lbl_status.setStyleSheet("color: red;")
            self.btn_save.setEnabled(False)
            self.parsed_cookies = []
            
        except Exception as e:
            self.lbl_status.setText(f"Trạng thái: ❌ Lỗi parse: {str(e)[:50]}")
            self.lbl_status.setStyleSheet("color: red;")
            self.btn_save.setEnabled(False)
            self.parsed_cookies = []

    def _validate_cookies(self, format_name):
        """Kiểm tra xem có đủ cookie quan trọng không"""
        REQUIRED = ["__Secure-next-auth.session-token", "__Secure-1PSID", "__Secure-1PSIDTS"]
        
        found_keys = [c.get('name') for c in self.parsed_cookies]
        
        # Check session-token (Critical)
        has_session = any("__Secure-next-auth.session-token" in k for k in found_keys)
        
        preview_text = f"Định dạng: {format_name}\nSố lượng cookie: {len(self.parsed_cookies)}\n\n"
        preview_text += "Các cookie quan trọng tìm thấy:\n"
        
        count_important = 0
        for req in REQUIRED:
            val = next((c.get('value') for c in self.parsed_cookies if c.get('name') == req), None)
            if val:
                preview_text += f"✅ {req}: {val[:20]}...\n"
                count_important += 1
            else:
                if req == "__Secure-next-auth.session-token":
                    preview_text += f"❌ {req}: (Thiếu - Cực kỳ quan trọng!)\n"
                else:
                    preview_text += f"⚠️ {req}: (Thiếu)\n"
        
        self.preview_area.setText(preview_text)
        
        if has_session:
            self.lbl_status.setText(f"Trạng thái: ✅ Hợp lệ ({format_name}, {len(self.parsed_cookies)} cookies)")
            self.lbl_status.setStyleSheet("color: green; font-weight: bold;")
            self.btn_save.setEnabled(True)
        else:
            self.lbl_status.setText(f"Trạng thái: ⚠️ Thiếu session-token ({format_name})")
            self.lbl_status.setStyleSheet("color: orange; font-weight: bold;")
            # Vẫn cho lưu nhưng warning
            self.btn_save.setEnabled(True)
    
    def get_data(self):
        """Return (email/name, list of cookie dicts)"""
        return self.txt_email.text().strip(), self.parsed_cookies


class ProxyDialog(QDialog):
    """Dialog cấu hình proxy cho account - chỉ hỗ trợ proxy thật."""

    def __init__(self, parent=None, email: str = "", current_proxy: Optional[Dict[str, str]] = None):
        super().__init__(parent)
        self.setWindowTitle(f"⚙ Cấu hình Proxy - {email}")
        self.setMinimumSize(520, 480)
        self._email = email

        # Parse current_proxy → ProxyConfig
        from proxy_manager import ProxyConfig
        if current_proxy and isinstance(current_proxy, dict) and current_proxy.get("proxy_type"):
            self._config = ProxyConfig.from_dict(current_proxy)
        elif current_proxy and current_proxy.get("server"):
            # Legacy format: {server, username, password}
            self._config = ProxyConfig(
                proxy_type="static",
                static_server=current_proxy.get("server", ""),
                static_username=current_proxy.get("username", ""),
                static_password=current_proxy.get("password", ""),
            )
        else:
            self._config = ProxyConfig()

        self._setup_ui()
        self._apply_config_to_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 12, 15, 12)

        # ── Radio buttons cho các loại proxy được hỗ trợ ──
        from PySide6.QtWidgets import QButtonGroup
        self._radio_group = QButtonGroup(self)

        radio_data = [
            ("none",     "🚫 Không dùng (IP gốc)"),
            ("static",   "📌 Proxy Tĩnh"),
            ("rotating", "🔄 Proxy Xoay"),
            ("proxyvn",  "🇻🇳 Proxy.vn Key Xoay"),
        ]
        self._radios: Dict[str, Any] = {}
        for idx, (key, label) in enumerate(radio_data):
            from PySide6.QtWidgets import QRadioButton
            rb = QRadioButton(label)
            rb.setStyleSheet("font-size: 13px; padding: 3px 0;")
            rb.toggled.connect(self._on_type_changed)
            self._radio_group.addButton(rb, idx)
            self._radios[key] = rb
            layout.addWidget(rb)

        # ── Stacked widget cho settings từng loại ──
        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: none (trống)
        page_none = QWidget()
        QVBoxLayout(page_none)
        self._stack.addWidget(page_none)

        # Page 1: static proxy
        page_static = QWidget()
        sl = QVBoxLayout(page_static)
        sl.setContentsMargins(0, 5, 0, 0)
        # Quick paste
        self.txt_static_paste = QLineEdit()
        self.txt_static_paste.setPlaceholderText("Dán: user:pass@host:port hoặc user:pass:host:port")
        self.txt_static_paste.setStyleSheet("font-family: Consolas; font-size: 11px; padding: 4px;")
        self.txt_static_paste.textChanged.connect(lambda: self._on_paste("static"))
        sl.addWidget(self.txt_static_paste)
        form_s = QFormLayout()
        self.txt_static_server = QLineEdit()
        self.txt_static_server.setPlaceholderText("http://host:port hoặc socks5://host:port")
        form_s.addRow("Server:", self.txt_static_server)
        self.txt_static_user = QLineEdit()
        self.txt_static_user.setPlaceholderText("Username (tùy chọn)")
        form_s.addRow("Username:", self.txt_static_user)
        self.txt_static_pass = QLineEdit()
        self.txt_static_pass.setEchoMode(QLineEdit.Password)
        self.txt_static_pass.setPlaceholderText("Password (tùy chọn)")
        form_s.addRow("Password:", self.txt_static_pass)
        sl.addLayout(form_s)
        self._stack.addWidget(page_static)

        # Page 2: rotating proxy
        page_rotating = QWidget()
        rl = QVBoxLayout(page_rotating)
        rl.setContentsMargins(0, 5, 0, 0)
        self.txt_rotating_paste = QLineEdit()
        self.txt_rotating_paste.setPlaceholderText("Dán: user:pass@gateway:port")
        self.txt_rotating_paste.setStyleSheet("font-family: Consolas; font-size: 11px; padding: 4px;")
        self.txt_rotating_paste.textChanged.connect(lambda: self._on_paste("rotating"))
        rl.addWidget(self.txt_rotating_paste)
        form_r = QFormLayout()
        self.txt_rotating_server = QLineEdit()
        self.txt_rotating_server.setPlaceholderText("http://gateway:port (proxy xoay tự đổi IP)")
        form_r.addRow("Gateway:", self.txt_rotating_server)
        self.txt_rotating_user = QLineEdit()
        self.txt_rotating_user.setPlaceholderText("Username")
        form_r.addRow("Username:", self.txt_rotating_user)
        self.txt_rotating_pass = QLineEdit()
        self.txt_rotating_pass.setEchoMode(QLineEdit.Password)
        self.txt_rotating_pass.setPlaceholderText("Password")
        form_r.addRow("Password:", self.txt_rotating_pass)
        rl.addLayout(form_r)
        info_r = QLabel("ℹ Proxy xoay: mỗi request sẽ tự động đổi IP qua gateway.")
        info_r.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        rl.addWidget(info_r)
        self._stack.addWidget(page_rotating)

        # Page 3: proxy.vn key xoay
        page_proxyvn = QWidget()
        pvl = QVBoxLayout(page_proxyvn)
        pvl.setContentsMargins(0, 5, 0, 0)
        form_pv = QFormLayout()
        self.txt_proxyvn_key = QLineEdit()
        self.txt_proxyvn_key.setPlaceholderText("Nhập key xoay từ proxy.vn")
        form_pv.addRow("Key xoay:", self.txt_proxyvn_key)
        self.txt_proxyvn_nhamang = QLineEdit()
        self.txt_proxyvn_nhamang.setPlaceholderText("Random | viettel | fpt | vnpt")
        form_pv.addRow("Nhà mạng:", self.txt_proxyvn_nhamang)
        self.txt_proxyvn_tinhthanh = QLineEdit()
        self.txt_proxyvn_tinhthanh.setPlaceholderText("0 = Random, hoặc mã tỉnh theo docs proxy.vn")
        form_pv.addRow("Tỉnh/thành:", self.txt_proxyvn_tinhthanh)
        self.txt_proxyvn_whitelist = QLineEdit()
        self.txt_proxyvn_whitelist.setPlaceholderText("IPv4 whitelist (tuỳ chọn)")
        form_pv.addRow("Whitelist:", self.txt_proxyvn_whitelist)
        self.txt_proxyvn_protocol = QLineEdit()
        self.txt_proxyvn_protocol.setPlaceholderText("http hoặc socks5")
        form_pv.addRow("Protocol:", self.txt_proxyvn_protocol)
        pvl.addLayout(form_pv)
        info_pv = QLabel("ℹ Proxy.vn key xoay: app sẽ gọi API get.php để lấy proxy mới ở lần dùng proxy đầu tiên hoặc khi cần rotate sau 403.")
        info_pv.setWordWrap(True)
        info_pv.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        pvl.addWidget(info_pv)
        self._stack.addWidget(page_proxyvn)

        # ── Status + Buttons ──
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-weight: bold; margin-top: 5px;")
        layout.addWidget(self.lbl_status)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        self.btn_test = QPushButton("🔍 Test Proxy")
        self.btn_test.setStyleSheet("background-color: #17a2b8; color: white; font-weight: bold; padding: 6px 12px;")
        self.btn_test.clicked.connect(self._test_proxy)
        btn_box.addWidget(self.btn_test)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        btn_save = QPushButton("💾 Lưu")
        btn_save.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 6px 12px;")
        btn_save.clicked.connect(self.accept)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    # ── Helpers ──

    def _apply_config_to_ui(self):
        """Load ProxyConfig vào UI."""
        c = self._config
        self._radios.get(c.proxy_type, self._radios["none"]).setChecked(True)
        self.txt_static_server.setText(c.static_server)
        self.txt_static_user.setText(c.static_username)
        self.txt_static_pass.setText(c.static_password)
        self.txt_rotating_server.setText(c.rotating_server)
        self.txt_rotating_user.setText(c.rotating_username)
        self.txt_rotating_pass.setText(c.rotating_password)
        self.txt_proxyvn_key.setText(c.proxyvn_key)
        self.txt_proxyvn_nhamang.setText(c.proxyvn_nhamang)
        self.txt_proxyvn_tinhthanh.setText(c.proxyvn_tinhthanh)
        self.txt_proxyvn_whitelist.setText(c.proxyvn_whitelist)
        self.txt_proxyvn_protocol.setText(c.proxyvn_protocol)
        self._on_type_changed()

    def _get_selected_type(self) -> str:
        for key, rb in self._radios.items():
            if rb.isChecked():
                return key
        return "none"

    def _on_type_changed(self):
        type_map = {"none": 0, "static": 1, "rotating": 2, "proxyvn": 3}
        idx = type_map.get(self._get_selected_type(), 0)
        self._stack.setCurrentIndex(idx)

    def _on_paste(self, target: str):
        """Auto-parse proxy paste cho static hoặc rotating."""
        src = self.txt_static_paste if target == "static" else self.txt_rotating_paste
        text = src.text().strip()
        if not text or len(text) < 8:
            return
        from proxy_manager import ProxyManager
        entry = ProxyManager._parse_proxy_line(text)
        if not entry:
            return
        if target == "static":
            self.txt_static_server.setText(entry.server)
            self.txt_static_user.setText(entry.username)
            self.txt_static_pass.setText(entry.password)
        else:
            self.txt_rotating_server.setText(entry.server)
            self.txt_rotating_user.setText(entry.username)
            self.txt_rotating_pass.setText(entry.password)
        src.blockSignals(True)
        src.clear()
        src.setPlaceholderText("✅ Đã parse!")
        src.blockSignals(False)

    def _test_proxy(self):
        """Test proxy hiện tại."""
        config = self._build_config()
        entry = config.get_active_proxy() if config else None
        if not entry:
            self.lbl_status.setText("❌ Chưa cấu hình proxy để test")
            self.lbl_status.setStyleSheet("color: red; font-weight: bold;")
            return
        self.lbl_status.setText("⏳ Đang test...")
        self.lbl_status.setStyleSheet("color: orange; font-weight: bold;")
        self.btn_test.setEnabled(False)

        import threading
        def _run():
            from proxy_manager import test_proxy_connection
            ok, info = test_proxy_connection(entry)
            if ok:
                self.lbl_status.setText(f"✅ Proxy OK! IP: {info}")
                self.lbl_status.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.lbl_status.setText(f"❌ Lỗi: {info}")
                self.lbl_status.setStyleSheet("color: red; font-weight: bold;")
            self.btn_test.setEnabled(True)
        threading.Thread(target=_run, daemon=True).start()

    def _build_config(self):
        from proxy_manager import ProxyConfig
        return ProxyConfig(
            proxy_type=self._get_selected_type(),
            static_server=self.txt_static_server.text().strip(),
            static_username=self.txt_static_user.text().strip(),
            static_password=self.txt_static_pass.text().strip(),
            rotating_server=self.txt_rotating_server.text().strip(),
            rotating_username=self.txt_rotating_user.text().strip(),
            rotating_password=self.txt_rotating_pass.text().strip(),
            proxyvn_key=self.txt_proxyvn_key.text().strip(),
            proxyvn_nhamang=self.txt_proxyvn_nhamang.text().strip() or "Random",
            proxyvn_tinhthanh=self.txt_proxyvn_tinhthanh.text().strip() or "0",
            proxyvn_whitelist=self.txt_proxyvn_whitelist.text().strip(),
            proxyvn_protocol=(self.txt_proxyvn_protocol.text().strip() or "http").lower(),
        )

    def get_data(self) -> Optional[Dict[str, str]]:
        """Return proxy config dict. Trả về None nếu chọn 'none'."""
        config = self._build_config()
        if config.proxy_type == "none":
            return None
        return config.to_dict()


class ProxyPoolDialog(QDialog):
    """
    Dialog for managing global proxy pool.
    
    This dialog allows users to:
    - View all proxies in the pool with their status
    - Add proxies (single or bulk paste)
    - Remove proxies (single or all)
    - Test proxy connectivity
    - Enable/disable the proxy pool
    
    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 5.4
    """
    
    # Signal emitted when proxy pool is modified
    proxy_pool_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý Proxy Pool")
        self.setMinimumSize(700, 500)
        
        # Import ProxyManager
        from proxy_manager import ProxyManager
        self.proxy_manager = ProxyManager.get_instance()
        
        self._setup_ui()
        self._refresh_table()
    
    def _setup_ui(self):
        """Setup dialog UI components"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # === Enable/Disable Checkbox ===
        self.chk_enabled = QCheckBox("🌐 Bật Proxy Pool")
        self.chk_enabled.setStyleSheet("font-size: 14px; font-weight: bold; color: #28a745;")
        self.chk_enabled.setChecked(self.proxy_manager.is_enabled())
        self.chk_enabled.stateChanged.connect(self._on_enabled_changed)
        layout.addWidget(self.chk_enabled)
        
        # === Proxy Table ===
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["#", "Server", "Username", "Status", "Last Used", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                font-family: Consolas; font-size: 11px;
                background-color: #2d2d2d;
                alternate-background-color: #3d3d3d;
                color: #ffffff;
                gridline-color: #555555;
            }
            QTableWidget::item {
                color: #ffffff;
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #343a40; color: white;
                padding: 6px; font-weight: bold;
            }
        """)
        layout.addWidget(self.table)
        
        # === Bulk Proxy Input ===
        lbl_bulk = QLabel("📋 Dán Proxy (mỗi dòng 1 proxy):")
        lbl_bulk.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(lbl_bulk)
        
        self.txt_bulk = QPlainTextEdit()
        self.txt_bulk.setPlaceholderText(
            "Hỗ trợ các định dạng:\n"
            "• host:port\n"
            "• user:pass:host:port\n"
            "• user:pass@host:port\n"
            "• http://host:port\n"
            "• http://user:pass@host:port\n"
            "• socks5://host:port"
        )
        self.txt_bulk.setMaximumHeight(100)
        self.txt_bulk.setStyleSheet("font-family: Consolas; font-size: 11px;")
        layout.addWidget(self.txt_bulk)
        
        # === Buttons Row ===
        btn_row = QHBoxLayout()
        
        # Add Proxies button
        self.btn_add = QPushButton("➕ Thêm Proxy")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: #28a745; color: white; font-weight: bold;
                padding: 8px 15px; border-radius: 5px;
            }
            QPushButton:hover { background-color: #218838; }
        """)
        self.btn_add.clicked.connect(self._on_add_proxies)
        btn_row.addWidget(self.btn_add)
        
        # Test All button
        self.btn_test_all = QPushButton("🔍 Test All")
        self.btn_test_all.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8; color: white; font-weight: bold;
                padding: 8px 15px; border-radius: 5px;
            }
            QPushButton:hover { background-color: #138496; }
        """)
        self.btn_test_all.clicked.connect(self._on_test_all)
        btn_row.addWidget(self.btn_test_all)
        
        # Clear All button
        self.btn_clear = QPushButton("🗑️ Xóa tất cả")
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #dc3545; color: white; font-weight: bold;
                padding: 8px 15px; border-radius: 5px;
            }
            QPushButton:hover { background-color: #c82333; }
        """)
        self.btn_clear.clicked.connect(self._on_clear_all)
        btn_row.addWidget(self.btn_clear)
        
        btn_row.addStretch()
        
        # Close button
        self.btn_close = QPushButton("Đóng")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #6c757d; color: white; font-weight: bold;
                padding: 8px 15px; border-radius: 5px;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        
        layout.addLayout(btn_row)
        
        # === Status Label ===
        self.lbl_status = QLabel("Proxy Pool: 0 proxies")
        self.lbl_status.setStyleSheet("color: #adb5bd; font-size: 12px; margin-top: 5px;")
        layout.addWidget(self.lbl_status)
    
    def _refresh_table(self):
        """Refresh proxy table from ProxyManager"""
        proxies = self.proxy_manager.get_all_proxies()
        
        self.table.setRowCount(len(proxies))
        
        for row, proxy in enumerate(proxies):
            # Index
            item_idx = QTableWidgetItem(str(row + 1))
            item_idx.setTextAlignment(Qt.AlignCenter)
            item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, item_idx)
            
            # Server
            item_server = QTableWidgetItem(proxy.server)
            item_server.setFlags(item_server.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, item_server)
            
            # Username
            item_user = QTableWidgetItem(proxy.username if proxy.username else "-")
            item_user.setFlags(item_user.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, item_user)
            
            # Status with color coding
            item_status = QTableWidgetItem(proxy.status.upper())
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setFlags(item_status.flags() & ~Qt.ItemIsEditable)
            status_color = self._get_status_color(proxy.status)
            item_status.setForeground(status_color)
            self.table.setItem(row, 3, item_status)
            
            # Last Used
            last_used_str = "-"
            if proxy.last_used:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(proxy.last_used.replace('Z', '+00:00'))
                    last_used_str = dt.strftime("%H:%M:%S")
                except:
                    last_used_str = proxy.last_used[:19] if len(proxy.last_used) > 19 else proxy.last_used
            item_last = QTableWidgetItem(last_used_str)
            item_last.setTextAlignment(Qt.AlignCenter)
            item_last.setFlags(item_last.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 4, item_last)
            
            # Actions (Test + Remove buttons)
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            
            btn_test = QPushButton("Test")
            btn_test.setStyleSheet("background-color: #17a2b8; color: white; padding: 3px 8px; font-size: 10px;")
            btn_test.clicked.connect(lambda checked, idx=row: self._on_test_proxy(idx))
            actions_layout.addWidget(btn_test)
            
            btn_remove = QPushButton("Xóa")
            btn_remove.setStyleSheet("background-color: #dc3545; color: white; padding: 3px 8px; font-size: 10px;")
            btn_remove.clicked.connect(lambda checked, idx=row: self._on_remove_proxy(idx))
            actions_layout.addWidget(btn_remove)
            
            self.table.setCellWidget(row, 5, actions_widget)
        
        # Update status label
        self.lbl_status.setText(f"Proxy Pool: {len(proxies)} proxies")
    
    def _get_status_color(self, status: str) -> QColor:
        """Get color for status display"""
        status_colors = {
            "working": QColor(40, 167, 69),    # Green
            "failed": QColor(220, 53, 69),     # Red
            "untested": QColor(108, 117, 125), # Gray
            "testing": QColor(255, 193, 7),    # Yellow
        }
        return status_colors.get(status.lower(), QColor(108, 117, 125))
    
    def _on_enabled_changed(self, state):
        """Handle enable/disable checkbox change"""
        enabled = state == Qt.Checked
        self.proxy_manager.set_enabled(enabled)
        self.proxy_pool_changed.emit()
    
    def _on_add_proxies(self):
        """Handle bulk proxy addition from text area"""
        text = self.txt_bulk.toPlainText().strip()
        if not text:
            SilentMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập proxy vào ô bên trên!")
            return
        
        added, failed = self.proxy_manager.add_proxies_from_text(text)
        
        # Clear text area after successful add
        if added > 0:
            self.txt_bulk.clear()
        
        # Refresh table
        self._refresh_table()
        
        # Show result
        if added > 0 and failed == 0:
            SilentMessageBox.information(self, "Thành công", f"Đã thêm {added} proxy!")
        elif added > 0 and failed > 0:
            SilentMessageBox.information(self, "Kết quả", f"Đã thêm {added} proxy.\n{failed} proxy không hợp lệ hoặc trùng lặp.")
        else:
            SilentMessageBox.warning(self, "Lỗi", f"Không thể thêm proxy nào.\n{failed} proxy không hợp lệ hoặc trùng lặp.")
        
        self.proxy_pool_changed.emit()
    
    def _on_remove_proxy(self, index: int):
        """Handle single proxy removal"""
        if self.proxy_manager.remove_proxy(index):
            self._refresh_table()
            self.proxy_pool_changed.emit()
    
    def _on_clear_all(self):
        """Handle clear all proxies"""
        proxies = self.proxy_manager.get_all_proxies()
        if not proxies:
            SilentMessageBox.information(self, "Thông báo", "Proxy pool đã trống!")
            return
        
        reply = SilentMessageBox.question(
            self, "Xác nhận",
            f"Bạn có chắc muốn xóa tất cả {len(proxies)} proxy?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.proxy_manager.clear_all()
            self._refresh_table()
            self.proxy_pool_changed.emit()
    
    def _on_test_proxy(self, index: int):
        """Handle single proxy test"""
        proxies = self.proxy_manager.get_all_proxies()
        if index < 0 or index >= len(proxies):
            return
        
        proxy = proxies[index]
        
        # Update status to testing
        proxy.status = "testing"
        self._refresh_table()
        
        # Test in background thread
        def test_thread():
            try:
                import requests
                from urllib.parse import quote
                
                proxy_dict = {'http': proxy.server, 'https': proxy.server}
                
                if proxy.username and proxy.password:
                    auth_server = proxy.server.replace('://', f'://{quote(proxy.username)}:{quote(proxy.password)}@')
                    proxy_dict = {'http': auth_server, 'https': auth_server}
                
                response = requests.get('http://httpbin.org/ip', proxies=proxy_dict, timeout=10)
                
                if response.status_code == 200:
                    self.proxy_manager.mark_proxy_working(proxy)
                else:
                    self.proxy_manager.mark_proxy_failed(proxy)
            except Exception:
                self.proxy_manager.mark_proxy_failed(proxy)
            
            # Refresh table in main thread
            from PySide6.QtCore import QMetaObject, Qt as QtCore_Qt
            QMetaObject.invokeMethod(self, "_refresh_table", QtCore_Qt.QueuedConnection)
        
        thread = threading.Thread(target=test_thread, daemon=True)
        thread.start()
    
    def _on_test_all(self):
        """Handle test all proxies"""
        proxies = self.proxy_manager.get_all_proxies()
        if not proxies:
            SilentMessageBox.information(self, "Thông báo", "Proxy pool trống!")
            return
        
        # Test all proxies sequentially in background
        def test_all_thread():
            for i, proxy in enumerate(proxies):
                proxy.status = "testing"
                from PySide6.QtCore import QMetaObject, Qt as QtCore_Qt
                QMetaObject.invokeMethod(self, "_refresh_table", QtCore_Qt.QueuedConnection)
                
                try:
                    import requests
                    from urllib.parse import quote
                    
                    proxy_dict = {'http': proxy.server, 'https': proxy.server}
                    
                    if proxy.username and proxy.password:
                        auth_server = proxy.server.replace('://', f'://{quote(proxy.username)}:{quote(proxy.password)}@')
                        proxy_dict = {'http': auth_server, 'https': auth_server}
                    
                    response = requests.get('http://httpbin.org/ip', proxies=proxy_dict, timeout=10)
                    
                    if response.status_code == 200:
                        self.proxy_manager.mark_proxy_working(proxy)
                    else:
                        self.proxy_manager.mark_proxy_failed(proxy)
                except Exception:
                    self.proxy_manager.mark_proxy_failed(proxy)
                
                QMetaObject.invokeMethod(self, "_refresh_table", QtCore_Qt.QueuedConnection)
        
        thread = threading.Thread(target=test_all_thread, daemon=True)
        thread.start()


# ✅ SINGLE PROCESS ARCHITECTURE: Global Browser instance (Playwright Async)
# Chỉ 1 Browser instance duy nhất, mỗi account/thread tạo BrowserContext riêng
_global_browser_async = None  # Global Browser instance (async)
_browser_lock_async = threading.Lock()  # Lock để bảo vệ browser initialization
_browser_contexts_async: Dict[str, Any] = {}  # {account_id: BrowserContext} - mỗi account có context riêng

async def _get_global_browser_async(headless: bool = False) -> Any:
    """
    Lấy hoặc khởi tạo global Browser instance (Playwright Async).
    Single Process Architecture: Chỉ 1 Browser, nhiều Context.
    
    Args:
        headless: Ignored; true headless is disabled, Chrome runs headful-hidden.
    
    Returns:
        Browser instance (async)
    """
    import platform
    
    global _global_browser_async, _browser_lock_async
    
    # ✅ Kiểm tra browser đã tồn tại chưa (không cần lock cho read)
    if _global_browser_async is not None:
        try:
            # Test browser còn hoạt động không
            _ = _global_browser_async.contexts
            return _global_browser_async
        except Exception:
            # Browser đã bị đóng, reset về None
            _global_browser_async = None
    
    # ✅ Cần lock để khởi tạo browser mới
    with _browser_lock_async:
        # Double-check sau khi acquire lock
        if _global_browser_async is None:
            try:
                from playwright.async_api import async_playwright
                import asyncio
                import random
                
                # Khởi tạo browser trong async context
                async def _init_browser():
                    # ✅ Thêm delay ngẫu nhiên để tránh khởi tạo dồn (giãn tải mạng)
                    await asyncio.sleep(random.uniform(3.0, 5.0))
                    playwright = await async_playwright().start()
                    
                    # Browser launch args: always headful; hidden mode moves the window off-screen.
                    hidden_args = ['--window-position=-32000,-32000', '--window-size=400,300'] if platform.system() == 'Windows' else ['--window-position=-3000,-3000', '--window-size=400,300']
                    launch_args = [
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-extensions',
                        '--disable-infobars',
                        '--disable-features=Translate,OptimizationGuideModelDownloading,OptimizationHints,InteractiveWindowOcclusion',
                        '--password-store=basic',
                        '--use-mock-keychain',
                        '--hide-crash-restore-bubble',
                        *hidden_args,
                    ]
                    
                    # Windows-specific: Set AppUserModelID để gom icon trên taskbar
                    # ✅ CÙNG AppUserModelID với complete_flow.py để gom icon thành 1
                    if platform.system() == 'Windows':
                        app_id = "GetCookieVeo3"  # Cùng ID với complete_flow.py
                        launch_args.append(f'--app-id={app_id}')
                        # Set AppUserModelID cho process (chỉ set 1 lần)
                        try:
                            import ctypes
                            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
                            print(f"  ✅ Đã set AppUserModelID: {app_id} (gom icon trên taskbar)")
                        except Exception as e:
                            print(f"  ⚠️ Không thể set AppUserModelID: {e}")
                    
                    # Launch browser
                    browser = await playwright.chromium.launch(
                        channel="chrome",
                        headless=False,
                        args=launch_args,
                    )
                    
                    return browser
                
                # ✅ Vì hàm này là async, có thể await trực tiếp
                _global_browser_async = await _init_browser()
                print(f"  🔍 Browser khởi tạo: type={type(_global_browser_async)}")
                
                # ✅ Kiểm tra browser có None không
                if _global_browser_async is None:
                    raise RuntimeError("Browser khởi tạo thất bại - trả về None")
                
                # ✅ Kiểm tra browser có phải là Browser instance hợp lệ không
                if not hasattr(_global_browser_async, 'new_context'):
                    raise RuntimeError(f"Browser instance không hợp lệ - không có method new_context. Type: {type(_global_browser_async)}")
                
                print("  ✅ Global Browser instance (async) đã khởi tạo thành công")
                
            except ImportError:
                raise RuntimeError("playwright chưa được cài đặt. Chạy: pip install playwright && playwright install chromium")
            except Exception as e:
                print(f"  ❌ Lỗi khởi tạo Browser: {e}")
                _global_browser_async = None  # Đặt về None để retry lần sau
                raise RuntimeError(f"Không thể khởi tạo Browser: {str(e)}")
        
        # ✅ Kiểm tra lại trước khi return
        if _global_browser_async is None:
            raise RuntimeError("Browser instance là None - không thể sử dụng")
        
        return _global_browser_async


class CookieWorker(QThread):
    """Worker thread for getting cookies - uses BrowserPool from main tool"""
    progress = Signal(int, int, str)  # current, total, email
    log = Signal(str)  # log message (terminal only - detailed)
    ui_log = Signal(str)  # UI log (simple - only important messages)
    finished_signal = Signal(dict)  # {email: cookie_string, ...}
    account_failed = Signal(str)  # email - báo khi account không có session-token
    account_done = Signal(str, list)  # email, cookies - báo khi account thành công
    
    def __init__(self, accounts: List[dict], force_login: bool = False, threads: int = 1, delay: int = 3, screen_size: tuple = (1920, 1080), use_proxy_pool: bool = False):
        super().__init__()
        self.accounts = accounts
        self.force_login = force_login
        self.threads = threads
        self.delay = delay
        self.screen_width = screen_size[0]
        self.screen_height = screen_size[1]
        self.semaphore = None
        self._stopped = False
        self.use_proxy_pool = use_proxy_pool  # ✅ Proxy pool support
    
    def stop(self):
        self._stopped = True
    
    def run(self):
        """Run cookie extraction using Chrome thật + CDP (không dùng Playwright/Selenium)"""
        results = {}
        total = len(self.accounts)
        
        self.log.emit(f"🚀 Bắt đầu lấy cookies cho {total} tài khoản (Chrome CDP)...")
        
        try:
            results = self._get_all_cookies_cdp()
        except Exception as e:
            self.log.emit(f"❌ Lỗi: {e}")
            import traceback
            self.log.emit(traceback.format_exc()[:200])
        
        self.finished_signal.emit(results)
    
    def _get_all_cookies_cdp(self) -> Dict[str, list]:
        """Get cookies cho tất cả accounts bằng Chrome CDP (threaded)."""
        from chrome_cdp_cookie import ChromeCDPSession, kill_chrome_for_profile, check_profile_has_cookies, PROFILES_DIR
        import concurrent.futures
        import random
        
        results = {}
        total = len(self.accounts)
        
        # Semaphore để giới hạn concurrent
        sem = threading.Semaphore(self.threads)
        results_lock = threading.Lock()
        completed = [0]
        
        def process_account(idx, account):
            if self._stopped:
                return
            
            with sem:
                if self._stopped:
                    return
                
                email = account.get('email', f'Account_{idx}')
                password = account.get('password', '')
                profile_path = account.get('profile_path', '')
                
                self.log.emit(f"📂 [{idx+1}/{total}] Bắt đầu: {email} (Chrome CDP)")
                self.ui_log.emit(f"📂 [{idx+1}/{total}] Bắt đầu: {email}")
                
                # Profile path
                if not profile_path:
                    profile_path = get_tool_account_profile_path(email)
                    self.log.emit(f"   ⚠️ [{email}] Dùng profile Chrome riêng cho tool: {profile_path}")

                profile_dir = Path(profile_path)
                if not profile_dir.exists():
                    try:
                        profile_dir.mkdir(parents=True, exist_ok=True)
                        self.log.emit(f"   📁 [{email}] Đã tạo profile dir: {profile_path}")
                    except Exception as mkdir_err:
                        self.log.emit(f"   ❌ [{email}] Không thể tạo profile dir: {profile_path} ({mkdir_err})")
                        self.account_failed.emit(email)
                        self.progress.emit(idx + 1, total, email)
                        return
                
                # Tính vị trí cửa sổ
                win_w, win_h = 500, 600
                cols = max(1, self.screen_width // win_w)
                slot = idx % self.threads
                col = slot % cols
                row = slot // cols
                pos_x = col * win_w
                pos_y = row * win_h
                
                # Tạo CDP session
                session = ChromeCDPSession(
                    profile_path=profile_path,
                    headless=False,  # True headless disabled; use headful/off-screen instead.
                    window_pos=(pos_x, pos_y),
                    window_size=(win_w, win_h),
                    log_fn=lambda msg: self.log.emit(msg),
                )
                
                try:
                    keep_session_alive = False
                    cookies = session.extract_cookies(
                        email=email,
                        password=password,
                        force_login=self.force_login,
                    )
                    
                    if cookies:
                        with results_lock:
                            results[email] = cookies
                        keep_session_alive = True
                        self.log.emit(f"   ✅ [{email}] Lấy được {len(cookies)} cookies!")
                        self.log.emit(f"   🔗 [{email}] Giữ Chrome/profile đang mở để tái dùng cho reCAPTCHA token")
                        self.ui_log.emit(f"🍪 Done - {email}")
                        self.account_done.emit(email, cookies)
                    else:
                        self.log.emit(f"   ❌ [{email}] Không lấy được cookies → FAIL")
                        self.ui_log.emit(f"🍪 Fail - {email}")
                        self.account_failed.emit(email)
                        
                except Exception as e:
                    self.log.emit(f"   ❌ [{email}] Error: {str(e)[:80]}")
                    self.ui_log.emit(f"🍪 Fail - {email}")
                    self.account_failed.emit(email)
                finally:
                    try:
                        session.close(keep_process=keep_session_alive)
                    except Exception:
                        pass
                    
                    if self.delay > 0:
                        time.sleep(self.delay)
                    
                    completed[0] += 1
                    self.progress.emit(completed[0], total, email)
        
        # Run with thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as executor:
            futures = []
            for idx, account in enumerate(self.accounts):
                if self._stopped:
                    break
                # Delay giữa các account
                if idx > 0 and self.delay > 0:
                    time.sleep(max(1, self.delay // 2))
                futures.append(executor.submit(process_account, idx, account))
            
            # Wait for all
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self.log.emit(f"⚠️ Thread error: {str(e)[:60]}")
        
        return results
    
    async def _get_cookies_simple(self) -> Dict[str, str]:
        """Cookie extraction with auto-login - threaded - Logic rõ ràng theo cookieauto_base.py"""
        from playwright.async_api import async_playwright
        import random
        
        results = {}
        total = len(self.accounts)
        completed_count = 0
        
        # Limit concurrency
        self.semaphore = asyncio.Semaphore(self.threads)
        
        # Position Argument Queue (0 to threads-1) to manage window slots
        slot_queue = asyncio.Queue()
        for i in range(self.threads):
            slot_queue.put_nowait(i)
        
        # ✅ BƯỚC 1: Khởi tạo Playwright instance (chỉ 1 lần cho tất cả accounts)
        # Thêm delay ngẫu nhiên để giãn tải khi khởi tạo (tránh nghẽn mạng)
        await asyncio.sleep(random.uniform(1.0, 2.0))
        
        async with async_playwright() as playwright:
            # ✅ BƯỚC 2: Xử lý tất cả accounts với playwright instance
            tasks = []
            for idx, account in enumerate(self.accounts):
                # ✅ Check delay logic giữa các accounts
                if idx > 0 and self.delay > 0:
                    self.log.emit(f"⏳ Waiting {self.delay}s before starting account {idx+1}...")
                    await asyncio.sleep(self.delay)

                task = asyncio.create_task(
                    self._process_single_account(playwright, account, idx, total, results, slot_queue)
                )
                tasks.append(task)
            
            # Wait for all tasks
            await asyncio.gather(*tasks)
        
        return results

    async def _process_single_account(self, playwright, account, idx, total, results, slot_queue):
        """Process a single account - Logic rõ ràng theo cookieauto_base.py
        
        BƯỚC 1: Check xem có cần login không (force_login hoặc không có cookies trong profile)
        BƯỚC 2: Mở browser:
            - Nếu CẦN LOGIN → visible để giải captcha
            - Nếu KHÔNG CẦN LOGIN → headful-hidden/off-screen, không dùng true headless
        BƯỚC 3: Nếu cần login → Gọi _do_google_login() để đăng nhập
        BƯỚC 4: Vào Labs để lấy session cookie
        BƯỚC 5: Lấy cookies và lưu vào results
        """
        import random
        
        # Constants for cookie check
        NEEDED_NAMES = {"__Secure-next-auth.session-token"}
        popup_selectors = [
             "#card-button", 
             "button[aria-label='Close']", 
             ".close-button",
             "div[role='dialog'] button:has-text('Not now')",
             "div[role='dialog'] button:has-text('No thanks')"
        ]

        async with self.semaphore:
            if self._stopped:
                return
            
            # Get a window slot for positioning
            slot_id = await slot_queue.get()
            try:
                # Calculate Position
                # Width 500, Height 600
                win_w, win_h = 500, 600
                cols = max(1, self.screen_width // win_w)
                
                col = slot_id % cols
                row = slot_id // cols
                
                pos_x = col * win_w
                pos_y = row * win_h
                
                email = account.get('email', f'Account_{idx}')
                password = account.get('password', '')
                profile_path = account.get('profile_path', '')
                
                # Note: idx is mostly for logging now, progress relies on completed count
                self.log.emit(f"📂 [{idx+1}/{total}] Bắt đầu: {email}")
                self.ui_log.emit(f"📂 [{idx+1}/{total}] Bắt đầu: {email}")
                
                # ✅ CRITICAL: Đảm bảo dùng đúng profile_path từ account dict
                if not profile_path:
                    profile_path = get_tool_account_profile_path(email)
                    self.log.emit(f"   ⚠️ [{email}] Không có profile_path trong account dict → dùng profile Chrome riêng cho tool: {profile_path}")

                profile_dir = Path(profile_path)
                if not profile_dir.exists():
                    try:
                        profile_dir.mkdir(parents=True, exist_ok=True)
                        self.log.emit(f"   📁 [{email}] Đã tạo profile dir: {profile_path}")
                    except Exception as mkdir_err:
                        self.log.emit(f"   ❌ [{email}] Không thể tạo profile dir: {profile_path} ({mkdir_err})")
                        self.ui_log.emit(f"🍪 Fail - {email} (Không tạo được profile)")
                        self.account_failed.emit(email)
                        self.progress.emit(idx + 1, total, email)
                        return
                else:
                    # ✅ Profile path tồn tại → dùng đúng profile này
                    self.log.emit(f"   ✅ [{email}] Dùng profile đã có: {profile_path}")
                
                # ✅ BƯỚC 1: Check if need login
                # need_login = True nếu: force_login được bật HOẶC profile không có cookies
                need_login = self.force_login or not self._check_profile_has_cookies(profile_path)
                
                if need_login:
                    self.log.emit(f"   🔐 [{email}] CẦN ĐĂNG NHẬP → Browser sẽ hiển thị")
                else:
                    self.log.emit(f"   🍪 [{email}] KHÔNG CẦN ĐĂNG NHẬP → Browser chạy headful-hidden/off-screen")

                # ✅ Ưu tiên Chrome thật + CDP giống web_app:
                # 1 account = 1 folder profile
                # Login lưu vào chính profile đó
                # Lấy cookie/token cũng mở lại đúng profile đó
                try:
                    from web_app.backend.chrome_cdp_cookie import ChromeCDPSession

                    self.log.emit(f"   🚀 [{email}] Dùng Chrome CDP profile thật (ưu tiên, cùng cơ chế với web_app)...")

                    proxy_server = None
                    proxy_username = None
                    proxy_password = None
                    if self.use_proxy_pool:
                        try:
                            from proxy_manager import ProxyManager
                            pm = ProxyManager.get_instance()
                            if pm.is_enabled():
                                proxy = pm.get_current_proxy()
                                if proxy:
                                    proxy_server = getattr(proxy, "server", None)
                                    proxy_username = getattr(proxy, "username", None)
                                    proxy_password = getattr(proxy, "password", None)
                                    self.log.emit(f"   🌐 [{email}] Using proxy (CDP): {proxy_server}")
                        except Exception as e:
                            self.log.emit(f"   ⚠️ [{email}] Proxy pool error (CDP): {e}")

                    def _cdp_log(msg: str):
                        self.log.emit(msg)

                    session = ChromeCDPSession(
                        profile_path=profile_path,
                        headless=False,
                        window_pos=(pos_x, pos_y),
                        window_size=(500, 600),
                        log_fn=_cdp_log,
                        proxy_server=proxy_server,
                        proxy_username=proxy_username,
                        proxy_password=proxy_password,
                    )

                    try:
                        keep_session_alive = False
                        valid_cookies = await asyncio.to_thread(
                            session.extract_cookies,
                            email,
                            password,
                            self.force_login,
                        )
                        if valid_cookies:
                            keep_session_alive = True
                    finally:
                        try:
                            await asyncio.to_thread(session.close, keep_session_alive)
                        except Exception:
                            pass

                    if valid_cookies:
                        results[email] = valid_cookies
                        self.log.emit(f"   ✅ [{email}] Lấy cookie bằng Chrome CDP thành công ({len(valid_cookies)} cookies)")
                        self.log.emit(f"   🔗 [{email}] Giữ Chrome/profile đang mở để dùng lại lúc lấy reCAPTCHA token")
                        self.ui_log.emit(f"🍪 Done - {email}")
                        self.account_done.emit(email, valid_cookies)
                    else:
                        self.log.emit(f"   ❌ [{email}] Chrome CDP không lấy được cookie!")
                        self.ui_log.emit(f"🍪 Fail - {email}")
                        self.account_failed.emit(email)

                    self.progress.emit(idx + 1, total, email)
                    return

                except Exception as cdp_err:
                    self.log.emit(f"   ⚠️ [{email}] Chrome CDP flow lỗi, fallback Playwright: {str(cdp_err)[:80]}")
                
                context = None
                
                # ✅ BƯỚC 2: Mở browser với retry logic
                for attempt in range(2):
                    try:
                        # Kill any Chrome process using this profile
                        self._kill_chrome_for_profile(profile_path)
                        await asyncio.sleep(2)  # Wait for locks
                        
                        # ✅ Thêm delay ngẫu nhiên để giãn tải khi khởi tạo browser (tránh nghẽn mạng)
                        await asyncio.sleep(random.uniform(1.0, 2.0))
                        
                        self.log.emit(f"   🚀 [{email}] Mở browser {'(VISIBLE - để giải captcha)' if need_login else '(HEADFUL-HIDDEN - off-screen)'}...")
                        
                        # ✅ Get proxy from pool if enabled
                        proxy_config = None
                        if self.use_proxy_pool:
                            try:
                                from proxy_manager import ProxyManager
                                pm = ProxyManager.get_instance()
                                if pm.is_enabled():
                                    proxy = pm.get_current_proxy()
                                    if proxy:
                                        proxy_config = proxy.to_playwright_proxy()
                                        self.log.emit(f"   🌐 [{email}] Using proxy: {proxy.server}")
                            except Exception as e:
                                self.log.emit(f"   ⚠️ [{email}] Proxy pool error: {e}")
                        
                        # ✅ Launch browser với headless phụ thuộc vào need_login
                        # - need_login=True → headless=False (VISIBLE để giải captcha)
                        # - need_login=False → headless=True (HEADLESS để nhanh hơn)
                        if need_login:
                            window_args = ['--window-size=500,600', f'--window-position={pos_x},{pos_y}']
                        else:
                            import platform
                            if platform.system() == 'Windows':
                                window_args = ['--window-position=-32000,-32000', '--window-size=400,300']
                            else:
                                window_args = ['--window-position=-3000,-3000', '--window-size=400,300']
                        launch_args = [
                            '--no-first-run',
                            '--no-default-browser-check',
                            '--disable-blink-features=AutomationControlled',
                            '--disable-extensions',
                            '--disable-infobars',
                            '--disable-features=Translate,OptimizationGuideModelDownloading,OptimizationHints,InteractiveWindowOcclusion',
                            '--password-store=basic',
                            '--use-mock-keychain',
                            '--hide-crash-restore-bubble',
                            *window_args,
                        ]
                        
                        context = await playwright.chromium.launch_persistent_context(
                            user_data_dir=str(profile_path),
                            headless=not need_login,  # ✅ Logic rõ ràng: cần login → visible, không cần → headless
                            channel="chrome",
                            args=launch_args,
                            viewport={'width': 500, 'height': 600},
                            proxy=proxy_config  # ✅ Apply proxy from pool
                        )
                        break 
                    except Exception as launch_err:
                        if attempt == 0:
                            self.log.emit(f"   ⚠️ [{email}] Launch failed, retrying...")
                            
                            # ✅ Proxy rotation on failure
                            if self.use_proxy_pool and proxy_config:
                                try:
                                    from proxy_manager import ProxyManager
                                    pm = ProxyManager.get_instance()
                                    if pm.is_enabled():
                                        current_proxy = pm.get_current_proxy()
                                        if current_proxy:
                                            pm.mark_proxy_failed(current_proxy)
                                            next_proxy = pm.rotate_to_next_proxy()
                                            if next_proxy:
                                                proxy_config = next_proxy.to_playwright_proxy()
                                                self.log.emit(f"   🌐 [{email}] Rotated to proxy: {next_proxy.server}")
                                except Exception as e:
                                    self.log.emit(f"   ⚠️ [{email}] Proxy rotation error: {e}")
                            
                            import shutil
                            try:
                                shutil.rmtree(profile_path, ignore_errors=True)
                                Path(profile_path).mkdir(parents=True, exist_ok=True)
                                need_login = True  # Force login sau khi xóa profile
                                await asyncio.sleep(2)
                            except:
                                pass
                        else:
                            self.log.emit(f"   ❌ [{email}] Launch error: {str(launch_err)[:60]}")
                
                if not context:
                    self.log.emit(f"   ❌ [{email}] Không thể mở browser!")
                    self.ui_log.emit(f"🍪 Fail - {email}")
                    self.account_failed.emit(email)
                    self.progress.emit(idx + 1, total, email)
                    return

                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    
                    # ✅ BƯỚC 3: Đăng nhập nếu cần
                    if need_login:
                        # Login Flow - Đợi người dùng giải captcha nếu có
                        self.log.emit(f"   🔐 [{email}] BƯỚC 3: Bắt đầu đăng nhập (browser đang hiển thị để giải captcha)...")
                        login_success = await self._do_google_login(page, email, password)
                        
                        if not login_success:
                            self.log.emit(f"   ❌ [{email}] Login thất bại!")
                            self.ui_log.emit(f"🍪 Fail - {email}")
                            self.account_failed.emit(email)
                            # ✅ Đợi một chút trước khi đóng browser để người dùng thấy lỗi
                            await asyncio.sleep(3)
                            return
                        else:
                            self.log.emit(f"   ✅ [{email}] Đăng nhập thành công, tiếp tục lấy cookies...")
                    else:
                        self.log.emit(f"   🍪 [{email}] BƯỚC 3: Bỏ qua đăng nhập (đã có cookies trong profile)")
                    
                    # ✅ BƯỚC 4: Vào Labs để lấy session cookie
                    # CRITICAL: Nếu bỏ qua bước này, chỉ lấy được google.com cookies, không có labs.google session
                    try:
                        target_url = "https://labs.google/fx/tools/image-to-video"
                        self.log.emit(f"   🌍 [{email}] BƯỚC 4: Vào Labs để lấy session cookie: {target_url}...")
                        try:
                            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                        except:
                            pass # Continue even if timeout
                        
                        await asyncio.sleep(3)
                        
                        # 1. Handle Popups
                        for p_sel in popup_selectors:
                            try:
                                btn = await page.wait_for_selector(p_sel, timeout=1000)
                                if btn and await btn.is_visible():
                                    await btn.click(force=True)
                                    await asyncio.sleep(1)
                            except:
                                pass
                        
                        # 2. Key Press to clear overlays
                        try:
                            await page.keyboard.press("Escape")
                        except:
                            pass

                        # 3. Find & Click "Sign in" (if generic blue button appears)
                        clicked_signin = await page.evaluate("""
                            () => {
                                const elements = document.querySelectorAll('button, a, [role="button"]');
                                for (const el of elements) {
                                    const style = window.getComputedStyle(el);
                                    if (style.backgroundColor.includes('66, 133, 244') || style.backgroundColor.includes('26, 115, 232')) {
                                        el.click(); return true;
                                    }
                                    const text = (el.innerText || '').toLowerCase();
                                    if (text.includes('sign in') || text.includes('đăng nhập')) {
                                        el.click(); return true;
                                    }
                                }
                                return false;
                            }
                        """)
                        if clicked_signin:
                            self.log.emit(f"   [{email}] Click 'Sign in'...")
                            await asyncio.sleep(3)

                        # 4. Find & Click "Create with Flow" (MANDATORY)
                        self.log.emit(f"   [{email}] Tìm nút 'Create with Flow'...")
                        clicked_create = await page.evaluate("""
                            () => {
                                const buttons = document.querySelectorAll('button, a, div[role="button"]');
                                for (const btn of buttons) {
                                    const text = (btn.innerText || '').trim().toLowerCase();
                                    if (text.includes('create with flow') || text === 'create' || text.includes('tạo') || text.includes('bắt đầu')) {
                                        btn.click();
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """)
                        
                        if clicked_create:
                            self.log.emit(f"   ✅ [{email}] Đã click nút Create!")
                            await asyncio.sleep(5) # Wait for token generation
                        else:
                            self.log.emit(f"   ⚠️ [{email}] Không thấy nút Create -> Đã login hoặc sai layout?")

                    except Exception as interact_err:
                        self.log.emit(f"   ⚠️ Interaction warning: {interact_err}")

                    # ✅ BƯỚC 5: Đợi và lấy cookies
                    self.log.emit(f"   🍪 [{email}] BƯỚC 5: Đang đợi session cookie được tạo...")
                    found_cookies = []
                    for i in range(15): # Loop check 15s
                        cookies = await context.cookies()
                        match_cookies = [c for c in cookies if "labs.google" in c.get("domain", "") and c.get("name") in NEEDED_NAMES]
                        if len(match_cookies) >= len(NEEDED_NAMES):
                            found_cookies = match_cookies
                            break
                        await asyncio.sleep(1)

                    # Also get Google/Youtube cookies as fallback/supplement
                    all_cookies = await context.cookies()
                    valid_cookies = [c for c in all_cookies if "google.com" in c['domain'] or "youtube.com" in c['domain'] or "labs.google" in c['domain']]
                    
                    if found_cookies:
                        self.log.emit(f"   ✅ [{email}] Đã có cookie Session Token!")
                        if valid_cookies:
                            results[email] = valid_cookies
                            self.log.emit(f"   💾 [{email}] Tổng {len(valid_cookies)} cookies")
                            
                            self.ui_log.emit(f"🍪 Done - {email}")
                            self.account_done.emit(email, valid_cookies)
                    else:
                        # Không có session-token -> báo FAIL
                        self.log.emit(f"   ❌ [{email}] Chưa thấy session-token -> FAIL! Cần Bật Login")
                        self.ui_log.emit(f"🍪 Fail - {email}")
                        self.account_failed.emit(email)
                        
                except Exception as e:
                    self.log.emit(f"   ❌ [{email}] Error: {str(e)[:60]}")
                    self.ui_log.emit(f"🍪 Fail - {email}")
                    self.account_failed.emit(email)
                finally:
                    # ✅ BƯỚC 6: Đóng browser context sau khi hoàn tất
                    # Đảm bảo browser không đóng sớm khi đang đợi captcha
                    if context:
                        try:
                            # ✅ Đợi một chút trước khi đóng để đảm bảo mọi thứ đã xong
                            await asyncio.sleep(1)
                            await context.close()
                            self.log.emit(f"   🔒 [{email}] Đã đóng browser context")
                        except Exception as close_err:
                            self.log.emit(f"   ⚠️ [{email}] Lỗi khi đóng context: {str(close_err)[:40]}")
                    
                    # Random delay between accounts for this thread
                    if self.delay > 0:
                        self.log.emit(f"   ⏳ [{email}] Delay {self.delay}s...")
                        await asyncio.sleep(self.delay)

                    self.progress.emit(idx + 1, total, email)

            finally:
                # Return slot to queue so next task can use it
                await slot_queue.put(slot_id)
    
    async def _do_google_login(self, page, email: str, password: str) -> bool:
        """Auto-login to Google - Đợi người dùng giải captcha nếu có"""
        try:
            self.log.emit(f"   🔐 Đăng nhập Google...")
            
            # Go to Google login
            await page.goto("https://accounts.google.com/signin", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            
            # Check if already logged in
            if "myaccount.google.com" in page.url or "accounts.google.com/b/" in page.url:
                self.log.emit(f"   ✅ Đã đăng nhập sẵn!")
                return True
            
            # Enter email - wait for element to be stable
            self.log.emit(f"   📧 Nhập email...")
            try:
                await page.wait_for_selector('input[type="email"]', state="visible", timeout=10000)
                await asyncio.sleep(0.5)  # Wait for stability
                await page.fill('input[type="email"]', email)
                await page.click("#identifierNext")
                await asyncio.sleep(4)  # Wait for password page
            except Exception as e:
                self.log.emit(f"   ⚠️ Email step failed: {str(e)[:40]}")
                return False
            
            # Enter password - wait for element with retry
            self.log.emit(f"   🔑 Nhập password...")
            try:
                # Wait for password field to appear and be stable
                await page.wait_for_selector('input[type="password"]', state="visible", timeout=15000)
                await asyncio.sleep(1)  # Critical: wait for element to be stable
                await page.fill('input[type="password"]', password)
                await asyncio.sleep(0.5)
                await page.click("#passwordNext")
                await asyncio.sleep(3)  # Wait for response
            except Exception as e:
                self.log.emit(f"   ⚠️ Password step failed: {str(e)[:40]}")
                return False
            
            # ✅ CRITICAL: Đợi người dùng giải captcha nếu có
            # Polling để check xem có captcha không và đợi đến khi login thành công
            self.log.emit(f"   ⏳ Đang đợi xử lý captcha (nếu có)...")
            self.log.emit(f"   💡 Vui lòng giải captcha trong browser nếu có!")
            
            max_wait_time = 300  # Tối đa 5 phút để giải captcha
            start_time = time.time()
            check_interval = 2  # Check mỗi 2 giây
            
            while time.time() - start_time < max_wait_time:
                current_url = page.url
                
                # ✅ Check nếu đã login thành công
                if "myaccount.google.com" in current_url or "accounts.google.com/b/" in current_url:
                    self.log.emit(f"   ✅ Đăng nhập thành công!")
                    return True
                
                # ✅ Check nếu đang ở trang captcha
                try:
                    # Check các dấu hiệu captcha
                    captcha_indicators = [
                        "challenge", "captcha", "recaptcha", 
                        "verify", "unusual activity", "suspicious"
                    ]
                    page_text = await page.evaluate("() => document.body.innerText.toLowerCase()")
                    has_captcha = any(indicator in page_text for indicator in captcha_indicators)
                    
                    if has_captcha:
                        # Có captcha, đợi người dùng giải
                        elapsed = int(time.time() - start_time)
                        if elapsed % 10 == 0:  # Log mỗi 10 giây
                            self.log.emit(f"   ⏳ Đang đợi giải captcha... ({elapsed}s/{max_wait_time}s)")
                except:
                    pass
                
                # ✅ Check nếu có lỗi không thể recover
                try:
                    error_indicators = ["couldn't sign you in", "wrong password", "account disabled"]
                    page_text = await page.evaluate("() => document.body.innerText.toLowerCase()")
                    has_error = any(indicator in page_text for indicator in error_indicators)
                    
                    if has_error and "captcha" not in page_text.lower():
                        # Có lỗi và không phải captcha -> fail
                        self.log.emit(f"   ❌ Phát hiện lỗi đăng nhập: {page_text[:100]}")
                        return False
                except:
                    pass
                
                await asyncio.sleep(check_interval)
            
            # Timeout - check lần cuối
            final_url = page.url
            if "myaccount.google.com" in final_url or "accounts.google.com/b/" in final_url:
                self.log.emit(f"   ✅ Đăng nhập thành công (sau timeout)!")
                return True
            else:
                self.log.emit(f"   ⚠️ Timeout đợi giải captcha ({max_wait_time}s)")
                self.log.emit(f"   ⚠️ URL hiện tại: {final_url[:50]}")
                return False
                
        except Exception as e:
            self.log.emit(f"   ❌ Login error: {str(e)[:50]}")
            return False
    
    def _check_profile_has_cookies(self, profile_path: str) -> bool:
        """Check if profile already has valid Google cookies"""
        try:
            info = resolve_chrome_profile(profile_path)
            user_data_dir = Path(info["user_data_dir"] or profile_path)

            local_state = user_data_dir / "Local State"
            if not local_state.exists():
                self.log.emit("   📋 No Local State - need login")
                return False

            for cookies_file in get_cookie_db_candidates(profile_path):
                if cookies_file.exists() and cookies_file.stat().st_size > 1000:
                    self.log.emit(f"   📋 Has cookies ({cookies_file.stat().st_size} bytes) - headless OK")
                    return True

            self.log.emit(f"   📋 No/small cookies file - need login")
            return False
        except Exception as e:
            self.log.emit(f"   📋 Cookie check error: {e}")
            return False
    
    def _kill_chrome_for_profile(self, profile_path: str):
        """Kill any Chrome/Chromium process using this profile and clean locks"""
        import subprocess
        import platform

        info = resolve_chrome_profile(profile_path)
        user_data_dir = info["user_data_dir"] or profile_path
        profile_name = Path(info["profile_storage_path"] or profile_path).name
        
        # Delete lock files first
        try:
            lock_files = [
                Path(user_data_dir) / "SingletonLock",
                Path(user_data_dir) / "SingletonSocket",
                Path(user_data_dir) / "SingletonCookie",
            ]
            for lock_file in lock_files:
                if lock_file.exists():
                    lock_file.unlink()
                    self.log.emit(f"   🔓 Deleted lock: {lock_file.name}")
        except:
            pass
        
        # Kill Chrome/Chromium processes (platform-specific)
        try:
            system = platform.system()
            
            if system == "Windows":
                # Windows: use wmic and taskkill
                for browser in ['chrome.exe', 'chromium.exe']:
                    try:
                        result = subprocess.run(
                            ['wmic', 'process', 'where', f"name='{browser}'", 'get', 'processid,commandline'],
                            capture_output=True, text=True, timeout=10, creationflags=0x08000000
                        )
                        
                        for line in result.stdout.split('\n'):
                            if profile_name in line:
                                parts = line.strip().split()
                                if parts:
                                    try:
                                        pid = int(parts[-1])
                                        subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                                    capture_output=True, timeout=5, creationflags=0x08000000)
                                        self.log.emit(f"   🔪 Killed {browser} PID {pid}")
                                    except:
                                        pass
                    except:
                        pass
            elif system == "Darwin":  # macOS
                # macOS: use ps and kill
                for browser in ['Google Chrome', 'Chromium']:
                    try:
                        # Find processes with this profile path
                        result = subprocess.run(
                            ['ps', 'aux'],
                            capture_output=True, text=True, timeout=10
                        )
                        
                        for line in result.stdout.split('\n'):
                            if browser in line and (user_data_dir in line or profile_name in line):
                                parts = line.split()
                                if len(parts) > 1:
                                    try:
                                        pid = int(parts[1])
                                        subprocess.run(['kill', '-9', str(pid)], 
                                                     capture_output=True, timeout=5)
                                        self.log.emit(f"   🔪 Killed {browser} PID {pid}")
                                    except:
                                        pass
                    except:
                        pass
            # Linux support can be added here if needed
        except:
            pass


class GetCookieJSWindow(QMainWindow):
    """Main window for Get Cookie Veo3 tool"""
    
    # ✅ Signal để refresh table từ background thread
    credits_updated_signal = Signal(str, int)  # email, credits
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Get Cookie Veo3 | HV |")
        
        # ✅ Connect signal để refresh table khi credits được update
        self.credits_updated_signal.connect(self._on_credits_updated)
        self.setMinimumSize(900, 600)
        
        # Set window icon - try cookie_icon first
        from PySide6.QtGui import QIcon
        icon_files = ["cookie_icon.ico", "cookie_icon.png", "icon.ico", "icon.png"]
        for icon_name in icon_files:
            icon_path = TOOL_DIR / icon_name
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                break
        
        self.accounts = []  # List of {email, profile_path}
        self.cookies_result = {}  # {email: list of cookie dicts} - supports both auto and manual
        self.failed_accounts = set()  # Set of emails that failed (no session-token)
        self.worker = None
        
        # Init DB
        init_db()
        
        self._setup_ui()
        self._load_saved_config()
        self._load_from_db()       # Load accounts from DB
        
        # Initialize cookies table
        self._refresh_cookies_table()
    
    def _setup_ui(self):
        """Setup UI components"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # === Header ===
        header = QLabel("🍪 Get Cookie JS Tool")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setStyleSheet("color: #FF6B35; padding: 10px;")
        layout.addWidget(header)
        
        # === Actions Row ===
        action_row = QHBoxLayout()
        
        # Import Excel button
        self.btn_import = QPushButton("📥 Import Excel")
        self.btn_import.setStyleSheet("""
            QPushButton {
                background-color: #28a745; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #218838; }
        """)
        self.btn_import.clicked.connect(self._on_import_excel)
        action_row.addWidget(self.btn_import)
        
        # Add Account button
        self.btn_add_account = QPushButton("➕ Thêm TK")
        self.btn_add_account.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #138496; }
        """)
        self.btn_add_account.clicked.connect(self._on_add_account)
        action_row.addWidget(self.btn_add_account)
        
        # Add Cookie Manual button
        self.btn_add_cookie_manual = QPushButton("🍪 Add Cookie")
        self.btn_add_cookie_manual.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #5a32a3; }
        """)
        self.btn_add_cookie_manual.clicked.connect(self._on_add_cookie_manual)
        action_row.addWidget(self.btn_add_cookie_manual)
        
        # Get Cookies button
        self.btn_get_cookies = QPushButton("🍪 Lấy Cookies")
        self.btn_get_cookies.setStyleSheet("""
            QPushButton {
                background-color: #007bff; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #0056b3; }
        """)
        self.btn_get_cookies.clicked.connect(self._on_get_cookies)
        action_row.addWidget(self.btn_get_cookies)
        
        # Export TXT button
        self.btn_export = QPushButton("💾 Xuất Cookie")
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #fd7e14; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #e56500; }
        """)
        self.btn_export.clicked.connect(self._on_export_txt)
        action_row.addWidget(self.btn_export)
        
        # Copy Cookie button
        self.btn_copy_cookie = QPushButton("📋 Copy Cookie")
        self.btn_copy_cookie.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #8e44ad; }
        """)
        self.btn_copy_cookie.clicked.connect(self._on_copy_cookie)
        action_row.addWidget(self.btn_copy_cookie)
        
        # Clean Profiles button
        self.btn_clean = QPushButton("🗑️ Xóa Profiles")
        self.btn_clean.setStyleSheet("""
            QPushButton {
                background-color: #dc3545; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 12px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #c82333; }
        """)
        self.btn_clean.clicked.connect(self._on_clean_profiles)
        action_row.addWidget(self.btn_clean)
        
        # Refresh UI button
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8; color: white; font-weight: bold;
                padding: 10px 15px; border-radius: 5px; font-size: 13px;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #138496; }
        """)
        self.btn_refresh.clicked.connect(self._on_refresh_ui)
        action_row.addWidget(self.btn_refresh)
        
        action_row.addStretch()
        layout.addLayout(action_row)
        
        # === Settings Row ===
        settings_row = QHBoxLayout()
        
        # Force Login checkbox
        self.chk_force_login = QCheckBox("Bật Login")
        self.chk_force_login.setStyleSheet("color: #FFD700; font-size: 13px; font-weight: bold;")
        self.chk_force_login.setToolTip("Bật để bắt buộc login lại dù đã có profile")
        settings_row.addWidget(self.chk_force_login)
        
        settings_row.addSpacing(15)
        
        # Use Proxy Pool checkbox
        self.chk_use_proxy_pool = QCheckBox("🌐 Dùng Proxy Pool")
        self.chk_use_proxy_pool.setStyleSheet("color: #6f42c1; font-size: 13px; font-weight: bold;")
        self.chk_use_proxy_pool.setToolTip("Bật để sử dụng proxy pool cho reCAPTCHA bypass")
        self.chk_use_proxy_pool.stateChanged.connect(self._on_proxy_pool_checkbox_changed)
        settings_row.addWidget(self.chk_use_proxy_pool)
        
        settings_row.addSpacing(20)
        
        # Threads
        lbl_threads = QLabel("Luồng:")
        lbl_threads.setStyleSheet("color: #ffffff; font-weight: bold;")
        settings_row.addWidget(lbl_threads)
        
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 10)
        self.spin_threads.setValue(5)
        self.spin_threads.setFixedWidth(50)
        self.spin_threads.setStyleSheet("""
            QSpinBox {
                background-color: #3d3d3d; color: white;
                border: 1px solid #555; padding: 5px;
            }
        """)
        self.spin_threads.setToolTip("Số luồng chạy song song (Max 10)")
        self.spin_threads.valueChanged.connect(self._save_settings)
        settings_row.addWidget(self.spin_threads)
        
        settings_row.addSpacing(15)
        
        # Delay
        lbl_delay = QLabel("Delay(s):")
        lbl_delay.setStyleSheet("color: #ffffff; font-weight: bold;")
        settings_row.addWidget(lbl_delay)
        
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 60)
        self.spin_delay.setValue(3)
        self.spin_delay.setFixedWidth(50)
        self.spin_delay.setStyleSheet("""
            QSpinBox {
                background-color: #3d3d3d; color: white;
                border: 1px solid #555; padding: 5px;
            }
        """)
        self.spin_delay.valueChanged.connect(self._save_settings)
        settings_row.addWidget(self.spin_delay)
        
        settings_row.addSpacing(30)
        
        # Select All button
        self.btn_select_all = QPushButton("✓ Chọn Tất")
        self.btn_select_all.setStyleSheet("""
            QPushButton {
                background-color: #6c757d; color: white; font-weight: bold;
                padding: 6px 15px; border-radius: 5px; font-size: 12px;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        self.btn_select_all.clicked.connect(self._on_select_all)
        settings_row.addWidget(self.btn_select_all)
        
        # Deselect All button
        self.btn_deselect_all = QPushButton("✗ Bỏ Chọn")
        self.btn_deselect_all.setStyleSheet("""
            QPushButton {
                background-color: #6c757d; color: white; font-weight: bold;
                padding: 6px 15px; border-radius: 5px; font-size: 12px;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        self.btn_deselect_all.clicked.connect(self._on_deselect_all)
        settings_row.addWidget(self.btn_deselect_all)
        
        settings_row.addSpacing(15)
        
        # Proxy Pool button
        self.btn_proxy_pool = QPushButton("🌐 Proxy Pool")
        self.btn_proxy_pool.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1; color: white; font-weight: bold;
                padding: 6px 15px; border-radius: 5px; font-size: 12px;
            }
            QPushButton:hover { background-color: #5a32a3; }
        """)
        self.btn_proxy_pool.setToolTip("Quản lý Proxy Pool cho reCAPTCHA bypass")
        self.btn_proxy_pool.clicked.connect(self._on_open_proxy_pool)
        settings_row.addWidget(self.btn_proxy_pool)
        
        settings_row.addStretch()
        
        # Proxy Pool status indicator
        self.lbl_proxy_status = QLabel("🌐 Proxy: OFF")
        self.lbl_proxy_status.setStyleSheet("color: #6c757d; font-size: 12px; margin-right: 10px;")
        settings_row.addWidget(self.lbl_proxy_status)
        
        # Status label
        self.lbl_status = QLabel("Accounts: 0 | Cookies: 0")
        self.lbl_status.setStyleSheet("color: #adb5bd; font-size: 13px;")
        settings_row.addWidget(self.lbl_status)
        
        layout.addLayout(settings_row)
        
        # Initialize proxy status
        self._update_proxy_status()
        
        # === Progress Bar ===
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc; border-radius: 5px;
                text-align: center; height: 25px;
            }
            QProgressBar::chunk { background-color: #28a745; }
        """)
        layout.addWidget(self.progress)
        
        # === Table ===
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["✓", "Email", "Password", "Cookies", "Status", "Credits", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)  # Checkbox column width
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Cookies
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Status
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Credits
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Actions
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                font-family: Consolas; font-size: 12px;
                background-color: #2d2d2d;
                alternate-background-color: #3d3d3d;
                color: #ffffff;
                gridline-color: #555555;
            }
            QTableWidget::item {
                color: #ffffff;
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #343a40; color: white;
                padding: 8px; font-weight: bold;
            }
        """)
        layout.addWidget(self.table)
        self.table.itemChanged.connect(self._on_item_changed)
        
        # === Cookies Table (Auto-added cookies) ===
        cookies_header = QHBoxLayout()
        cookies_label = QLabel("🍪 Cookies Đã Thêm:")
        cookies_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        cookies_header.addWidget(cookies_label)
        cookies_header.addStretch()
        
        # Toggle Log button
        self.btn_toggle_log = QPushButton("📋 Hiện Log")
        self.btn_toggle_log.setStyleSheet("""
            QPushButton {
                background-color: #6c757d; color: white; font-weight: bold;
                padding: 5px 12px; border-radius: 3px; font-size: 11px;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        self.btn_toggle_log.clicked.connect(self._on_toggle_log)
        cookies_header.addWidget(self.btn_toggle_log)
        layout.addLayout(cookies_header)
        
        # Cookies table (shows auto-added cookies)
        self.cookies_table = QTableWidget()
        self.cookies_table.setColumnCount(3)
        self.cookies_table.setHorizontalHeaderLabels(["Email/Tên", "Số Cookie", "Trạng thái"])
        self.cookies_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cookies_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.cookies_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.cookies_table.setMaximumHeight(150)
        self.cookies_table.setAlternatingRowColors(True)
        self.cookies_table.setStyleSheet("""
            QTableWidget {
                font-family: Consolas; font-size: 11px;
                background-color: #2d2d2d;
                alternate-background-color: #3d3d3d;
                color: #ffffff;
                gridline-color: #555555;
            }
            QTableWidget::item {
                color: #ffffff;
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #343a40; color: white;
                padding: 6px; font-weight: bold;
            }
        """)
        layout.addWidget(self.cookies_table)
        
        # === Log Area (Hidden by default) ===
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(130)
        self.log_area.setVisible(False)  # Hidden by default
        self.log_area.setStyleSheet("""
            QTextEdit {
                font-family: Consolas; font-size: 11px;
                background-color: #1e1e1e; color: #d4d4d4;
                border: 1px solid #444; border-radius: 5px;
            }
        """)
        layout.addWidget(self.log_area)
    
    def _log(self, message: str):
        """Log to TERMINAL only (detailed)"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        print(log_msg)  # Terminal only
    
    def _log_ui(self, message: str):
        """Log to UI only (simple messages)"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        self.log_area.append(log_msg)
        # Auto scroll to bottom
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )
    
    def _log_both(self, message: str):
        """Log to both UI and Terminal"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        self.log_area.append(log_msg)
        print(log_msg)
        # Auto scroll to bottom
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )
    
    def _update_status(self):
        """Update status label"""
        cookies_count = len(self.cookies_result)
        self.lbl_status.setText(f"Accounts: {len(self.accounts)} | Cookies: {cookies_count}")
    
    def _load_saved_config(self):
        """Load last saved Excel config and settings"""
        config = load_config()
        last_excel = config.get('last_excel', '')
        
        # Load threads and delay settings
        saved_threads = config.get('threads', 5)
        saved_delay = config.get('delay', 3)
        self.spin_threads.setValue(saved_threads)
        self.spin_delay.setValue(saved_delay)
        self._log(f"⚙️ Đã load cài đặt: Luồng={saved_threads}, Delay={saved_delay}s")  # Terminal only
        
        # Load proxy pool setting
        use_proxy_pool = config.get('use_proxy_pool', False)
        self.chk_use_proxy_pool.setChecked(use_proxy_pool)
        if use_proxy_pool:
            # Sync with ProxyManager and LabsFlowClient
            try:
                from proxy_manager import ProxyManager
                pm = ProxyManager.get_instance()
                pm.set_enabled(True)
                
                from complete_flow import LabsFlowClient
                LabsFlowClient.set_use_proxy_pool(True)
            except Exception as e:
                print(f"Error loading proxy pool setting: {e}")
        
        if last_excel and Path(last_excel).exists():
            self._log(f"📂 Tự động load Excel: {last_excel}")  # Terminal only
            self._import_excel_file(last_excel)
    
    def _save_settings(self):
        """Save threads and delay settings to config"""
        config = load_config()
        config['threads'] = self.spin_threads.value()
        config['delay'] = self.spin_delay.value()
        config['use_proxy_pool'] = self.chk_use_proxy_pool.isChecked()
        save_config(config)
    
    def _load_from_db(self):
        """Load accounts from SQLite DB"""
        db_accounts = db_get_all_accounts()
        if not db_accounts:
            return
            
        # Merge with existing (avoid duplicates)
        # ✅ CRITICAL: Preserve credits from existing accounts - credits không được lưu trong DB
        existing_credits = {}
        for acc in self.accounts:
            email = acc.get('email', '')
            credits = acc.get('credits')
            if email and credits is not None:
                existing_credits[email] = credits
        
        existing_emails = {a['email'] for a in self.accounts}
        added = 0
        updated = 0
        for acc in db_accounts:
            email = acc['email']
            if email not in existing_emails:
                # ✅ New account from DB - preserve credits if it was in memory (shouldn't happen but safe)
                if email in existing_credits:
                    acc['credits'] = existing_credits[email]
                self.accounts.append(acc)
                existing_emails.add(email)
                added += 1
            else:
                # ✅ Update existing account but PRESERVE credits và proxy_config
                for i, existing_acc in enumerate(self.accounts):
                    if existing_acc['email'] == email:
                        # ✅ CRITICAL: Preserve credits - đây là giá trị quan trọng không có trong DB
                        saved_credits = existing_acc.get('credits')
                        # Update other fields from DB (password, profile_path, proxy_config)
                        self.accounts[i]['password'] = acc.get('password', self.accounts[i].get('password', ''))
                        self.accounts[i]['profile_path'] = acc.get('profile_path', self.accounts[i].get('profile_path', ''))
                        # ✅ Update proxy_config từ DB nếu có
                        if 'proxy_config' in acc:
                            self.accounts[i]['proxy_config'] = acc.get('proxy_config')
                        # ✅ Credits được giữ nguyên (không update từ DB vì DB không có)
                        updated += 1
                        break
        
        if added > 0 or updated > 0:
            self._log(f"📂 Đã load {added} accounts mới, update {updated} accounts từ Database")  # Terminal only
            self._refresh_table()
            self._update_status()

    def _on_import_excel(self):
        """Handle Import Excel button"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file Excel",
            str(Path.home()),
            "Excel Files (*.xlsx *.xls);;All Files (*)"
        )
        
        if file_path:
            self._import_excel_file(file_path)
    
    def _import_excel_file(self, file_path: str):
        """Import accounts from Excel file (col1=email, col2=password)"""
        try:
            import openpyxl
            
            wb = openpyxl.load_workbook(file_path, read_only=True)
            sheet = wb.active
            
            self.accounts = []
            
            # Read email (column 1) and password (column 2) - start from row 1 (no header)
            for row_idx, row in enumerate(sheet.iter_rows(min_row=1, values_only=True), start=1):
                if not row or not row[0]:
                    continue
                
                email = str(row[0]).strip() if row[0] else ''
                password = str(row[1]).strip() if len(row) > 1 and row[1] else ''
                
                if not email:
                    continue
                
                profile_path = Path(get_tool_account_profile_path(email))

                
                self.accounts.append({
                    'email': email,
                    'password': password,
                    'profile_path': str(profile_path),
                    'proxy_config': None,  # Mặc định không có proxy
                    'profile_edited': False  # ✅ Flag để track đã "Sửa Profile" chưa
                })
            
            wb.close()
            
            # Save config
            save_config({'last_excel': file_path})
            
            self._log_ui(f"✅ Import {len(self.accounts)} accounts")
            self._log(f"✅ Đã import {len(self.accounts)} accounts từ Excel")  # Terminal only
            self._log(f"   📁 Profiles folder: {PROFILES_DIR}")  # Terminal only
            self._refresh_table()
            self._update_status()
            
        except ImportError:
            SilentMessageBox.warning(self, "Lỗi", "Cần cài đặt openpyxl:\npip install openpyxl")
        except Exception as e:
            self._log(f"❌ Lỗi import Excel: {e}")  # Terminal only
            SilentMessageBox.warning(self, "Lỗi", f"Không thể import Excel:\n{e}")
    
    def _edit_profile_manual_login(self, email: str):
        """Mở browser với profile để login thủ công (Sửa Profile)"""
        for acc in self.accounts:
            if acc['email'] == email:
                password = acc.get('password', '')
                profile_path = acc.get('profile_path', '')
                
                # Tạo profile_path nếu chưa có
                if not profile_path:
                    profile_path = get_tool_account_profile_path(email)
                    acc['profile_path'] = profile_path
                    self._log(f"📂 [{email}] Dùng profile Chrome riêng cho tool: {profile_path}")  # Terminal only
                
                # Mở browser với profile này
                self._open_browser_for_login(email, password, profile_path)
                
                # ✅ Set flag profile_edited = True sau khi mở browser
                # (User sẽ login thủ công trong browser)
                acc['profile_edited'] = True
                
                # ✅ Refresh table để cập nhật trạng thái nút "Sửa Profile"
                self._refresh_table()
                
                self._log_ui(f"✏️ Đã mở browser cho {email} - Vui lòng login thủ công")
                self._log(f"✏️ [{email}] Đã mở browser với profile: {profile_path}")  # Terminal only
                self._log(f"   💡 Sau khi login xong, nhấn 'Lấy Cookie' để lấy cookies")  # Terminal only
                
                # Hiển thị hướng dẫn
                SilentMessageBox.information(
                    self,
                    "Sửa Profile",
                    f"Đã mở browser cho: {email}\n\n"
                    f"📋 Hướng dẫn:\n"
                    f"1. Login vào Google trong browser\n"
                    f"2. Giải captcha/2FA nếu có\n"
                    f"3. Sau khi login xong, nhấn 'Lấy Cookie'\n\n"
                    f"✅ Profile đã được đánh dấu là 'đã sửa'"
                )
                break
    
    def _open_profile_folder(self, email: str):
        """Open profile folder for account"""
        import subprocess
        for acc in self.accounts:
            if acc['email'] == email:
                path = acc.get('profile_path')
                if path and os.path.exists(path):
                    try:
                        if sys.platform == 'win32':
                            os.startfile(path)
                        elif sys.platform == 'darwin':
                            subprocess.run(['open', path])
                        else:
                            subprocess.run(['xdg-open', path])
                        self._log(f"📂 Opened profile: {path}")
                    except Exception as e:
                        self._log(f"❌ Cannot open profile: {e}")
                else:
                    self._log(f"⚠️ Profile check: Path not found {path}")
                break

    def _check_live_single(self, email: str):
        """Check live status for single account"""
        cookies_list = self.cookies_result.get(email)
        if not cookies_list:
            SilentMessageBox.warning(self, "Lỗi", "Chưa có cookie! Hãy lấy cookie trước.")
            return
            
        try:
             from complete_flow import _parse_cookie_string, LabsFlowClient
             cookies_dict = {}
             if isinstance(cookies_list, list):
                for c in cookies_list:
                    if isinstance(c, dict):
                        cookies_dict[c.get('name', '')] = c.get('value', '')
             elif isinstance(cookies_list, str):
                cookies_dict = _parse_cookie_string(cookies_list)
                
             if not cookies_dict:
                 SilentMessageBox.warning(self, "Lỗi", "Cookie không hợp lệ!")
                 return
             
             self._log(f"🔍 Checking live for {email}...")
             # ✅ Proxy chỉ dùng cho reCAPTCHA token, không dùng cho check live
             client = LabsFlowClient(cookies_dict)
             
             if client.fetch_access_token():
                  # Verify by setting model
                  if client.set_video_model_key("veo_3_1_t2v_fast_ultra"):
                      SilentMessageBox.information(self, "Check Live", f"Account: {email}\n✅ Cookie Live (Set Model OK)")
                  else:
                      error = getattr(client, "last_error", "Unknown")
                      SilentMessageBox.warning(self, "Check Live", f"Account: {email}\n⚠️ Cookie Live but Set Model Failed\nError: {error}")
             else:
                 SilentMessageBox.warning(self, "Check Live", f"Account: {email}\n❌ Cookie Die (Fetch Token Failed)")
                 
        except Exception as e:
            SilentMessageBox.warning(self, "Lỗi", f"Check error: {e}")

    def _refresh_table(self):
        """Refresh table with accounts data"""
        # ✅ CRITICAL: Clear selection trước để tránh lỗi index
        self.table.clearSelection()
        self.table.blockSignals(True)
        
        try:
            # ✅ Clear table trước để đảm bảo xóa hết rows cũ
            # Xóa tất cả widgets trước (quan trọng!)
            for row in range(self.table.rowCount()):
                widget = self.table.cellWidget(row, 6)  # Actions column
                if widget:
                    widget.deleteLater()
            # Xóa tất cả items và widgets trước
            self.table.setRowCount(0)
            
            # Set lại số rows
            self.table.setRowCount(len(self.accounts))
            
            for row, account in enumerate(self.accounts):
                email = account.get('email', '')
                password = account.get('password', '')
                profile_path = account.get('profile_path', '')
                selected = account.get('selected', True)
                credits_value = account.get('credits', None)
                
                # ✅ DEBUG: Log credits value để kiểm tra
                if credits_value is not None:
                    self._log(f"🔍 [REFRESH TABLE] Account {email}: credits_value = {credits_value}")  # Terminal only
                
                # 0. Checkbox
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
            self.table.setItem(row, 0, checkbox_item)
            
            # 1. Email
            self.table.setItem(row, 1, QTableWidgetItem(email))
            
            # 2. Password (masked)
            if password:
                pwd_display = '*' * min(len(password), 8)
                pwd_item = QTableWidgetItem(pwd_display)
                pwd_item.setForeground(QColor("#00FF7F"))
            else:
                pwd_item = QTableWidgetItem("N/A")
                pwd_item.setForeground(QColor("#6c757d"))
            self.table.setItem(row, 2, pwd_item)
            
            # 3. Cookies count
            cookies_data = self.cookies_result.get(email, None)
            if cookies_data:
                if isinstance(cookies_data, list):
                    cookie_count = len(cookies_data)
                elif isinstance(cookies_data, str):
                    cookie_count = cookies_data.count(';') + 1
                else:
                    cookie_count = 1
                cookies_item = QTableWidgetItem(f"🍪 {cookie_count}")
                cookies_item.setForeground(QColor("#00FF7F"))
            else:
                cookies_item = QTableWidgetItem("N/A")
                cookies_item.setForeground(QColor("#6c757d"))
            self.table.setItem(row, 3, cookies_item)
            
            # 4. Status
            if cookies_data:
                status_item = QTableWidgetItem("✅ OK")
                status_item.setForeground(QColor("#00FF7F"))
            elif not profile_path or not Path(profile_path).exists():
                status_item = QTableWidgetItem("⏳ Chờ login")
                status_item.setForeground(QColor("#FFD700"))
            else:
                status_item = QTableWidgetItem("⏳ Chưa lấy")
                status_item.setForeground(QColor("#00BFFF"))
            self.table.setItem(row, 4, status_item)
            
            # 5. Credits
            # ✅ CRITICAL: Đảm bảo đọc đúng credits từ account dict
            if credits_value is not None:
                # ✅ Format credits với dấu phẩy ngăn cách hàng nghìn
                credits_display = f"💰 {credits_value:,}"
                credits_item = QTableWidgetItem(credits_display)
                if credits_value > 0:
                    credits_item.setForeground(QColor("#00FF7F"))
                else:
                    credits_item.setForeground(QColor("#FF6B6B"))
            else:
                credits_item = QTableWidgetItem("N/A")
                credits_item.setForeground(QColor("#6c757d"))
            self.table.setItem(row, 5, credits_item)
            
            # 6. Actions (Buttons)
            actions_widget = QWidget()
            layout = QHBoxLayout(actions_widget)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(5)
            
            # Btn Sửa Profile (Login thủ công)
            profile_edited = account.get('profile_edited', False)
            btn_edit_profile = QPushButton("✏️ Sửa Profile")
            if profile_edited:
                btn_edit_profile.setStyleSheet("background-color: #28a745; color: white; padding: 3px; font-size: 11px;")
                btn_edit_profile.setToolTip("✅ Đã login thủ công - Có thể lấy cookie")
            else:
                btn_edit_profile.setStyleSheet("background-color: #ffc107; color: black; padding: 3px; font-size: 11px;")
                btn_edit_profile.setToolTip("⚠️ Chưa login thủ công - Nhấn để mở browser login")
            btn_edit_profile.clicked.connect(lambda checked=False, e=email: self._edit_profile_manual_login(e))
            
            # Btn Open Profile Folder
            btn_profile = QPushButton("📂 Folder")
            btn_profile.setStyleSheet("background-color: #6c757d; color: white; padding: 3px; font-size: 11px;")
            if not profile_path:
                btn_profile.setEnabled(False)
                btn_profile.setToolTip("Không có đường dẫn profile")
            else:
                btn_profile.clicked.connect(lambda checked=False, e=email: self._open_profile_folder(e))
            
            # Btn Check Live
            btn_live = QPushButton("🟢 Live")
            btn_live.setStyleSheet("background-color: #28a745; color: white; padding: 3px; font-size: 11px;")
            btn_live.clicked.connect(lambda checked=False, e=email: self._check_live_single(e))
            
            # Btn Get Credits
            btn_credits = QPushButton("💰 Credits")
            btn_credits.setStyleSheet("background-color: #ffc107; color: black; padding: 3px; font-size: 11px;")
            btn_credits.clicked.connect(lambda checked=False, e=email: self._fetch_credits_for_account(e))
            
            # Btn Proxy
            btn_proxy = QPushButton("🌐 Proxy")
            btn_proxy.setStyleSheet("background-color: #6f42c1; color: white; padding: 3px; font-size: 11px;")
            btn_proxy.setToolTip("Cấu hình proxy cho account này")
            btn_proxy.clicked.connect(lambda checked=False, e=email: self._manage_proxy(e))
            
            # Btn Delete (Xóa account này)
            btn_delete = QPushButton("🗑️")
            btn_delete.setStyleSheet("background-color: #dc3545; color: white; padding: 3px; font-size: 11px;")
            btn_delete.setToolTip("Xóa account này")
            btn_delete.clicked.connect(lambda checked=False, e=email: self._delete_single_account(e))
            
            layout.addWidget(btn_edit_profile)
            layout.addWidget(btn_profile)
            layout.addWidget(btn_live)
            layout.addWidget(btn_credits)
            layout.addWidget(btn_proxy)
            layout.addWidget(btn_delete)
            
            self.table.setCellWidget(row, 6, actions_widget)
        
        finally:
            self.table.blockSignals(False)
            
            # ✅ CRITICAL: Force table to update immediately - repaint mạnh và process events
            self.table.viewport().update()
            self.table.viewport().repaint()
            self.table.update()
            self.table.repaint()
        self.table.resizeColumnsToContents()
        
        # ✅ Process events để đảm bảo UI được update ngay lập tức
        for _ in range(10):
            QApplication.processEvents()
        
        self._log(f"✅ [REFRESH TABLE] Đã refresh table với {len(self.accounts)} accounts")  # Terminal only
    
    def _on_item_changed(self, item):
        """Update account selection state when checkbox changes"""
        if item.column() == 0:
            row = item.row()
            if 0 <= row < len(self.accounts):
                self.accounts[row]['selected'] = (item.checkState() == Qt.Checked)
    
    def _on_get_cookies(self):
        """Start getting cookies for selected accounts only - Bỏ qua accounts thủ công (không có password)"""
        if not self.accounts:
            SilentMessageBox.warning(self, "Lỗi", "Chưa import file Excel!")
            return
        
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._log("⏹️ Đã dừng...")  # Terminal only
            self._log_ui("⏹️ Dừng")
            return
        
        # Get selected accounts from table checkboxes
        all_selected_accounts = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                all_selected_accounts.append(self.accounts[row])
        
        if not all_selected_accounts:
            SilentMessageBox.warning(self, "Lỗi", "Chưa chọn tài khoản nào!\nHãy tích chọn ít nhất 1 tài khoản.")
            return
        
        # ✅ Filter: Check các điều kiện để lấy cookie
        selected_accounts = []
        skipped_accounts = []
        skipped_reasons = {}
        
        for acc in all_selected_accounts:
            email = acc.get('email', '')
            password = acc.get('password', '')
            profile_path = acc.get('profile_path', '')
            profile_edited = acc.get('profile_edited', False)
            
            # ✅ Check 1: Account thủ công (không có password)
            if not password or password.strip() == '':
                skipped_accounts.append(email)
                skipped_reasons[email] = "Account thủ công (không có password)"
                self._log(f"⏭️ Bỏ qua {email}: Account thủ công (không có password)")  # Terminal only
                continue
            
            # ✅ Check 2: Chưa "Sửa Profile" (chưa login thủ công)
            if not profile_edited:
                skipped_accounts.append(email)
                skipped_reasons[email] = "Chưa 'Sửa Profile' để login thủ công"
                self._log(f"⏭️ Bỏ qua {email}: Chưa 'Sửa Profile' để login thủ công")  # Terminal only
                continue
            
            # ✅ Check 3: Profile path không tồn tại
            if not profile_path or not Path(profile_path).exists():
                skipped_accounts.append(email)
                skipped_reasons[email] = "Profile path không tồn tại"
                self._log(f"⏭️ Bỏ qua {email}: Profile path không tồn tại: {profile_path}")  # Terminal only
                continue
            
            # ✅ Tất cả điều kiện OK → thêm vào danh sách
            selected_accounts.append(acc)
        
        # ✅ Thông báo nếu có account bị bỏ qua
        if skipped_accounts:
            skipped_count = len(skipped_accounts)
            skipped_list = []
            for email in skipped_accounts[:5]:
                reason = skipped_reasons.get(email, "Không rõ lý do")
                skipped_list.append(f"{email} ({reason})")
            
            skipped_msg = '\n'.join(skipped_list)
            if skipped_count > 5:
                skipped_msg += f"\n... (+{skipped_count - 5} account khác)"
            
            self._log_ui(f"⚠️ Đã bỏ qua {skipped_count} account(s):\n{skipped_msg}")
            self._log(f"⚠️ Đã bỏ qua {skipped_count} account(s)")  # Terminal
            
            # Hiển thị dialog chi tiết
            SilentMessageBox.warning(
                self,
                "Có Account Bị Bỏ Qua",
                f"Đã bỏ qua {skipped_count} account(s) vì:\n\n"
                f"{skipped_msg}\n\n"
                f"⚠️ Lưu ý:\n"
                f"- Phải nhấn 'Sửa Profile' để login thủ công trước\n"
                f"- Sau khi login xong mới có thể 'Lấy Cookie'"
            )
        
        if not selected_accounts:
            SilentMessageBox.warning(
                self,
                "Không có Account Hợp Lệ",
                f"Tất cả {len(all_selected_accounts)} account(s) đã chọn đều không đủ điều kiện:\n\n"
                f"✅ Điều kiện để 'Lấy Cookie':\n"
                f"1. Có password\n"
                f"2. Đã nhấn 'Sửa Profile' để login thủ công\n"
                f"3. Profile path tồn tại\n\n"
                f"💡 Hướng dẫn:\n"
                f"1. Nhấn 'Sửa Profile' để mở browser\n"
                f"2. Login thủ công vào Google\n"
                f"3. Sau đó nhấn 'Lấy Cookie'"
            )
            return
        
        self._log_ui(f"🚀 Bắt đầu lấy cookies cho {len(selected_accounts)} tài khoản (đã bỏ qua {len(skipped_accounts)} account)...")
        self._log(f"🚀 Bắt đầu lấy cookies cho {len(selected_accounts)} tài khoản (đã bỏ qua {len(skipped_accounts)} account)...")  # Terminal
        self.progress.setVisible(True)
        self.progress.setMaximum(len(selected_accounts))
        self.progress.setValue(0)
        
        # Store total for finished handler
        self.total_selected_accounts = len(selected_accounts)
        
        # Get force_login option from checkbox
        force_login = self.chk_force_login.isChecked()
        threads = self.spin_threads.value()
        delay = self.spin_delay.value()
        
        if force_login:
            self._log("⚠️ Force Login: Bật - sẽ login lại tất cả")  # Terminal only
        self._log(f"⚡ Chạy với {threads} luồng, delay {delay}s")  # Terminal only
        
        # Get Screen size
        screen = QApplication.primaryScreen().size()
        screen_size = (screen.width(), screen.height())
        
        # Start worker with selected accounts only
        self.worker = CookieWorker(
            selected_accounts, 
            force_login=force_login, 
            threads=threads,
            delay=delay,
            screen_size=screen_size
        )
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.log.connect(self._log)  # Terminal only
        self.worker.ui_log.connect(self._log_ui)  # UI only
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.account_failed.connect(self._on_account_failed)
        self.worker.account_done.connect(self._on_account_done)
        self.failed_accounts.clear()  # Reset failed list
        self.worker.start()
    
    def _on_worker_progress(self, current: int, total: int, email: str):
        """Handle worker progress"""
        self.progress.setValue(current)
        self.progress.setFormat(f"{current}/{total} - {email}")
    
    def _on_worker_finished(self, results: dict):
        """Handle worker finished"""
        self.cookies_result.update(results)
        self.progress.setVisible(False)
        self._refresh_table()
        self._refresh_cookies_table()  # Update cookies table
        self._update_status()
        
        success_count = len(results)
        fail_count = len(self.failed_accounts)
        total_count = getattr(self, 'total_selected_accounts', success_count + fail_count)
        
        if fail_count > 0:
            self._log_ui(f"⚠️ Hoàn tất! Done: {success_count}/{total_count}, Fail: {fail_count}")
            self._log(f"⚠️ Hoàn tất! Thành công: {success_count}/{total_count}, THẤT BẠI: {fail_count}")
            
            # List failed accounts
            failed_list = ", ".join(list(self.failed_accounts)[:5])
            if len(self.failed_accounts) > 5:
                failed_list += f"... (+{len(self.failed_accounts) - 5} more)"
            self._log(f"   Accounts lỗi: {failed_list}")
            
            SilentMessageBox.warning(self, "Có Lỗi!", 
                f"Tổng: {total_count} accounts\n"
                f"✅ Thành công: {success_count}\n"
                f"❌ THẤT BẠI: {fail_count}\n\n"
                f"Các account FAIL cần BậT LOGIN để lấy lại cookie!")
        elif results:
            self._log_ui(f"✅ Hoàn tất! Done: {success_count}/{total_count} accounts")
            self._log(f"✅ Hoàn tất! Lấy được cookies từ {success_count}/{total_count} accounts")
            # ✅ Hiển thị popup ngay trên main thread không bị block (tránh chờ lâu)
            from PySide6.QtCore import QTimer
            def show_done_popup():
                result = SilentMessageBox.information(self, "Hoàn tất", 
                    f"✅ Đã lấy cookies từ {success_count}/{total_count} accounts.\nNhấn Coppy Cookie hoặc Xuất File .TXT")
                if result:
                    self._refresh_table()
                    self._refresh_cookies_table()
                    self._update_status()
            QTimer.singleShot(0, show_done_popup)
        else:
            self._log_ui(f"❌ Hoàn tất! Không lấy được cookie nào (0/{total_count})")
            self._log(f"❌ Hoàn tất! Không lấy được cookie nào (0/{total_count})")
    
    def _on_account_failed(self, email: str):
        """Handle when an account fails (no session-token)"""
        self.failed_accounts.add(email)
        # Update table for this email - set Status=Fail, Cookie=0
        for row in range(self.table.rowCount()):
            table_email = self.table.item(row, 1)
            if table_email and table_email.text() == email:
                # Column 3: Cookie = 0
                cookie_item = QTableWidgetItem("🍪 0")
                cookie_item.setForeground(QColor("#FF6B6B"))  # Red color
                self.table.setItem(row, 3, cookie_item)
                
                # Column 4: Status = Fail
                status_item = QTableWidgetItem("❌ FAIL")
                status_item.setForeground(QColor("#FF0000"))  # Bright Red
                status_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
                self.table.setItem(row, 4, status_item)
                break
    
    def _on_account_done(self, email: str, cookies: list):
        """Handle when an account succeeds (has session-token)"""
        # Save cookies immediately
        self.cookies_result[email] = cookies

        # Update table for this email - set Status=Done
        for row in range(self.table.rowCount()):
            table_email = self.table.item(row, 1)
            if table_email and table_email.text() == email:
                # Column 4: Status = Done
                status_item = QTableWidgetItem("✅ Done")
                status_item.setForeground(QColor("#00FF7F"))  # Green color
                status_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
                self.table.setItem(row, 4, status_item)
                
                # Column 3: Cookie count
                cookie_count = len(cookies)
                cookies_item = QTableWidgetItem(f"🍪 {cookie_count}")
                cookies_item.setForeground(QColor("#00FF7F"))
                self.table.setItem(row, 3, cookies_item)
                break
        
        # Update cookies table
        self._refresh_cookies_table()
        
        # ✅ Force UI update ngay lập tức
        self.table.repaint()
        self.table.update()
        QApplication.processEvents()
        
        # ✅ Fetch credits immediately và check credits <= 100
        self._fetch_credits_for_account(email, check_low_credits=True)
        
        # ✅ CRITICAL: Sử dụng QTimer để refresh table sau khi credits được fetch
        # Đảm bảo UI được update ngay sau khi credits được update (khoảng 1-2 giây)
        from PySide6.QtCore import QTimer
        def refresh_table_after_credits():
            """Refresh table sau khi credits được fetch"""
            self._refresh_table()
            self.table.repaint()
            self.table.update()
            QApplication.processEvents()
        
        # Refresh ngay lập tức và sau 500ms, 1000ms, 2000ms để đảm bảo UI được update
        QTimer.singleShot(0, refresh_table_after_credits)
        QTimer.singleShot(500, refresh_table_after_credits)
        QTimer.singleShot(1000, refresh_table_after_credits)
        QTimer.singleShot(2000, refresh_table_after_credits)
    
    def _update_credits_in_ui(self, email: str, credits: int, api_key: str = None):
        """Update credits in UI (thread-safe) - Helper function
        
        ✅ THREAD-SAFE: Emit signal từ background thread (signal luôn thread-safe trong Qt)
        Signal handler sẽ chạy trên main thread và update UI
        """
        # ✅ CRITICAL: Log ngay đầu hàm để đảm bảo hàm được gọi
        print(f"[COOKIAUTO] 📡 _update_credits_in_ui được gọi cho {email}: {credits:,}")  # Terminal only
        
        # ✅ CRITICAL: Update credits vào account dict trước (trong background thread)
        # Điều này đảm bảo khi handler được gọi trên main thread, giá trị đã có sẵn
        account_found = False
        for i, acc in enumerate(self.accounts):
            if acc.get('email') == email:
                old_credits = acc.get('credits')
                self.accounts[i]['credits'] = credits
                account_found = True
                print(f"[COOKIAUTO] ✅ Đã update account dict: {email} credits từ {old_credits} → {credits}")  # Terminal only
                break
        
        if not account_found:
            print(f"[COOKIAUTO] ⚠️ Không tìm thấy account {email} trong self.accounts")  # Terminal only
        
        # ✅ CRITICAL: Sử dụng QTimer.singleShot để đảm bảo handler được gọi trên main thread
        # Vì hàm này được gọi từ background thread, cần schedule update trên main thread
        from PySide6.QtCore import QTimer
        
        def update_on_main_thread():
            """Update credits trên main thread"""
            print(f"[COOKIAUTO] 📥 update_on_main_thread được gọi cho {email}: {credits:,}")  # Terminal only
            # ✅ Emit signal để handler được gọi
            self.credits_updated_signal.emit(email, credits)
            
            # ✅ CRITICAL: Gọi trực tiếp handler để đảm bảo update ngay lập tức
            self._on_credits_updated(email, credits)
        
        # ✅ Schedule update trên main thread (ngay lập tức với QTimer.singleShot(0))
        QTimer.singleShot(0, update_on_main_thread)
        print(f"[COOKIAUTO] ✅ Đã schedule QTimer.singleShot(0) cho {email}: {credits:,}")  # Terminal only
    
    def _on_credits_updated(self, email: str, credits: int):
        """Handle credits updated signal - refresh table from main thread
        
        ✅ THREAD-SAFE: Signal handler luôn chạy trên main thread
        """
        try:
            print(f"[COOKIAUTO] 📥 [SIGNAL HANDLER] _on_credits_updated được gọi cho {email}: {credits:,}")  # Terminal only
            self._log(f"📥 [SIGNAL HANDLER] _on_credits_updated được gọi cho {email}: {credits:,}")  # Terminal only
            
            # ✅ Update account dict trước (chạy trên main thread nên thread-safe)
            account_updated = False
            
            for i, acc in enumerate(self.accounts):
                if acc.get('email') == email:
                    # ✅ Update credits trực tiếp vào account object
                    old_credits = acc.get('credits')
                    self.accounts[i]['credits'] = credits
                    account_updated = True
                    self._log(f"✅ [SIGNAL HANDLER] Đã update account dict: {email} credits từ {old_credits} → {credits}")  # Terminal only
                    break
            
            if not account_updated:
                # Thử thêm account nếu chưa có
                new_acc = {
                    'email': email,
                    'password': '',
                    'profile_path': '',
                    'selected': True,
                    'credits': credits,
                    'profile_edited': False
                }
                self.accounts.append(new_acc)
            
            # ✅ CRITICAL: Update trực tiếp vào table item (column 5 - Credits) NGAY LẬP TỨC
            # Tìm row có email này và update credits item trực tiếp
            table_updated = False
            self.table.blockSignals(True)  # ✅ Block signals để tránh conflict khi update
            
            try:
                for row in range(self.table.rowCount()):
                    table_email_item = self.table.item(row, 1)  # Column 1: Email
                    if table_email_item and table_email_item.text() == email:
                        # ✅ Update credits item trực tiếp (column 5)
                        credits_item = QTableWidgetItem(f"💰 {credits:,}")
                        if credits > 0:
                            credits_item.setForeground(QColor("#00FF7F"))
                        else:
                            credits_item.setForeground(QColor("#FF6B6B"))
                        
                        # ✅ CRITICAL: Remove item cũ trước khi set item mới để đảm bảo update
                        old_item = self.table.item(row, 5)
                        if old_item:
                            self.table.removeCellWidget(row, 5)  # Remove widget nếu có
                        
                        self.table.setItem(row, 5, credits_item)
                        table_updated = True
                        self._log(f"✅ Đã update trực tiếp credits item trong table cho {email}: {credits:,}")  # Terminal only
                        break
            finally:
                self.table.blockSignals(False)  # ✅ Unblock signals
            
            # ✅ CRITICAL: Luôn refresh toàn bộ table để đảm bảo UI được update đúng
            # (Ngay cả khi đã update trực tiếp item, vẫn refresh để đảm bảo consistency)
            if table_updated:
                self._log(f"✅ [SIGNAL HANDLER] Đã update credits item, sẽ refresh toàn bộ table để đảm bảo UI được update")  # Terminal only
            else:
                self._log(f"⚠️ [SIGNAL HANDLER] Không tìm thấy row trong table cho {email}, sẽ refresh toàn bộ table")  # Terminal only
            
            # ✅ CRITICAL: Refresh toàn bộ table để đảm bảo UI được update đúng
            # Kiểm tra lại credits trong account dict trước khi refresh
            for acc in self.accounts:
                if acc.get('email') == email:
                    self._log(f"🔍 [SIGNAL HANDLER] Credits trong account dict trước khi refresh: {acc.get('credits')}")  # Terminal only
                    break
            
            self._log(f"🔄 [SIGNAL HANDLER] Bắt đầu refresh table...")  # Terminal only
            self._refresh_table()
            self._log(f"✅ [SIGNAL HANDLER] Đã refresh table xong")  # Terminal only
            
            # ✅ Refresh cookies table và status
            self._refresh_cookies_table()
            self._update_status()
            
            # ✅ CRITICAL: Force UI update NGAY LẬP TỨC - repaint mạnh và process events nhiều lần
            # Update viewport trước
            self.table.viewport().update()
            self.table.viewport().repaint()
            
            # Update table
            self.table.update()
            self.table.repaint()
            
            # Resize columns để đảm bảo hiển thị đúng
            self.table.resizeColumnsToContents()
            
            # ✅ Process events nhiều lần để đảm bảo UI được update
            for _ in range(20):  # Tăng số lần process events
                QApplication.processEvents()
            
            # ✅ Force update lại table một lần nữa sau khi process events
            self.table.viewport().update()
            self.table.repaint()
            
            # ✅ CRITICAL: Refresh lại một lần nữa sau khi process events để đảm bảo UI được update
            from PySide6.QtCore import QTimer
            def final_refresh():
                """Final refresh để đảm bảo UI được update"""
                self._refresh_table()
                self.table.repaint()
                QApplication.processEvents()
            
            QTimer.singleShot(100, final_refresh)  # Refresh sau 100ms
            QTimer.singleShot(500, final_refresh)  # Refresh sau 500ms
            
            self._log(f"✅ Đã update credits cho {email}: {credits:,} và refresh UI")  # Terminal only
        except Exception as e:
            self._log(f"⚠️ Lỗi khi refresh table từ signal: {e}")  # Debug
            import traceback
            self._log(traceback.format_exc()[:200])  # Debug
    
    def _fetch_credits_for_account(self, email: str):
        """Fetch credits for an account (async in background thread) - Sử dụng logic từ gui_app_mac"""
        try:
            from complete_flow import _parse_cookie_string, LabsFlowClient
            import requests
            from bs4 import BeautifulSoup
            import re
            
            # Get cookies for this account
            cookies_data = self.cookies_result.get(email)
            if not cookies_data:
                return
            
            # Convert cookies to dict format
            if isinstance(cookies_data, list):
                # List of cookie dicts -> convert to cookie string dict
                cookies_dict = {}
                for c in cookies_data:
                    if isinstance(c, dict):
                        cookies_dict[c.get('name', '')] = c.get('value', '')
            elif isinstance(cookies_data, str):
                cookies_dict = _parse_cookie_string(cookies_data)
            else:
                return
            
            if not cookies_dict:
                return
            
            # ✅ Lấy credits (tương tự logic trong gui_app_mac.py)
            self._log(f"💰 Đang lấy credits cho {email}...")  # Terminal only
            
            # Run in background thread to avoid blocking UI
            import threading
            # ✅ Capture check_low_credits trong closure
            check_low_credits_flag = check_low_credits
            
            def fetch_credits_thread():
                try:
                    # ✅ Step 0: Thử dùng API key đã lưu trước (nếu có)
                    # Import ở đây để tránh circular import
                    saved_api_key = db_get_account_api_key(email)
                    access_token = None
                    api_key_to_use = None
                    
                    # ✅ Proxy chỉ dùng cho reCAPTCHA token, không dùng cho fetch credits
                    if saved_api_key:
                        self._log(f"🔑 Tìm thấy API key đã lưu cho {email}, đang thử dùng...")  # Terminal only
                        # Fetch access token
                        client = LabsFlowClient(cookies_dict)
                        if client.fetch_access_token():
                            access_token = client.access_token
                            if access_token:
                                # Thử dùng API key đã lưu
                                try:
                                    credits_url = f"https://aisandbox-pa.googleapis.com/v1/credits?key={saved_api_key}"
                                    credits_headers = {
                                        "accept": "*/*",
                                        "accept-language": "vi-VN,vi;q=0.9",
                                        "authorization": f"Bearer {access_token}",
                                        "origin": "https://labs.google",
                                        "referer": "https://labs.google/",
                                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                    }
                                    
                                    credits_response = requests.get(credits_url, headers=credits_headers, timeout=30)
                                    credits_response.raise_for_status()
                                    credits_data = credits_response.json()
                                    credits = credits_data.get("credits", 0)
                                    
                                    # ✅ Success với API key đã lưu
                                    self._log(f"✅ Dùng API key đã lưu thành công cho {email}")  # Terminal only
                                    api_key_to_use = saved_api_key
                                    # Update credits và refresh UI (thread-safe)
                                    self._update_credits_in_ui(email, credits, api_key_to_use)
                                    
                                    # ✅ CRITICAL: Đợi một chút để đảm bảo signal được xử lý và UI được refresh
                                    import time
                                    time.sleep(0.1)  # Đợi 100ms để signal được xử lý
                                    
                                    # ✅ Check credits <= 100 và báo lỗi nếu cần
                                    if check_low_credits_flag and credits <= 100:
                                        self._log(f"⚠️ [{email}] Credits thấp ({credits} <= 100) - Cần check Ultra!")  # Terminal only
                                        # ✅ Sử dụng QTimer để đảm bảo dialog hiển thị sau khi UI đã được refresh
                                        from PySide6.QtCore import QTimer
                                        def show_warning_dialog():
                                            SilentMessageBox.warning(
                                                self,
                                                "Credits Thấp",
                                                f"Account: {email}\n"
                                                f"Credits: {credits:,} (<= 100)\n\n"
                                                f"⚠️ Credits quá thấp! Vui lòng:\n"
                                                f"1. Nhấn 'Sửa Profile' để mở browser\n"
                                                f"2. Check xem còn Ultra không\n"
                                                f"3. Nạp thêm credits nếu cần"
                                            )
                                        QTimer.singleShot(200, show_warning_dialog)  # Đợi 200ms sau khi refresh UI
                                    return
                                    
                                except Exception as e:
                                    self._log(f"⚠️ API key đã lưu không work, sẽ lấy lại từ đầu: {str(e)[:60]}")  # Terminal only
                                    # Fall through to get new API key
                    
                    # ✅ Nếu không có API key đã lưu hoặc không work, lấy lại từ đầu
                    base = "https://labs.google"
                    url = "https://labs.google/fx/vi/tools/flow/project/"
                    
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                    }
                    
                    # Step 1: Lấy HTML và tìm _app-*.js
                    response = requests.get(url, headers=headers, cookies=cookies_dict, timeout=30)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.text, "html.parser")
                    app_js_url = None
                    
                    for tag in soup.find_all("script", src=True):
                        src = tag.get("src", "")
                        if "/_next/static/chunks/pages/_app-" in src:
                            app_js_url = base + src
                            break
                    
                    if not app_js_url:
                        self._log(f"⚠️ Không tìm thấy _app-*.js cho {email}")
                        return
                    
                    # Step 2: Lấy JS file và tìm API key
                    js_response = requests.get(app_js_url, cookies=cookies_dict, timeout=30)
                    js_response.raise_for_status()
                    js_content = js_response.text
                    
                    # Tìm API keys
                    possible_api_keys = []
                    for match in re.finditer(r'AIzaSy[0-9A-Za-z_\-]{20,}', js_content):
                        key = match.group(0)
                        if key not in possible_api_keys:
                            possible_api_keys.append(key)
                    
                    if not possible_api_keys:
                        self._log(f"⚠️ Không tìm thấy API key cho {email}")
                        return
                    
                    # Step 3: Fetch access token (nếu chưa có)
                    # ✅ Proxy chỉ dùng cho reCAPTCHA token, không dùng cho fetch access token
                    if not access_token:
                        client = LabsFlowClient(cookies_dict)
                        if not client.fetch_access_token():
                            self._log(f"⚠️ Không fetch được access token cho {email}")
                            return
                        access_token = client.access_token
                        if not access_token:
                            return
                    
                    # Step 4: Thử từng API key
                    for api_key in possible_api_keys:
                        try:
                            credits_url = f"https://aisandbox-pa.googleapis.com/v1/credits?key={api_key}"
                            credits_headers = {
                                "accept": "*/*",
                                "accept-language": "vi-VN,vi;q=0.9",
                                "authorization": f"Bearer {access_token}",
                                "origin": "https://labs.google",
                                "referer": "https://labs.google/",
                                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            }
                            
                            credits_response = requests.get(credits_url, headers=credits_headers, timeout=30)
                            credits_response.raise_for_status()
                            credits_data = credits_response.json()
                            
                            credits = credits_data.get("credits", 0)
                            
                            # ✅ Lưu API key thành công vào DB
                            api_key_to_use = api_key
                            db_update_account_api_key(email, api_key_to_use)
                            self._log(f"💾 Đã lưu API key cho {email}")  # Terminal only
                            
                            # ✅ Update credits và refresh UI (thread-safe)
                            self._update_credits_in_ui(email, credits, api_key_to_use)
                            
                            # ✅ CRITICAL: Đợi một chút để đảm bảo signal được xử lý và UI được refresh
                            import time
                            time.sleep(0.1)  # Đợi 100ms để signal được xử lý
                            
                            # ✅ Check credits <= 100 và báo lỗi nếu cần
                            if check_low_credits_flag and credits <= 100:
                                self._log(f"⚠️ [{email}] Credits thấp ({credits} <= 100) - Cần check Ultra!")  # Terminal only
                                # ✅ Sử dụng QTimer để đảm bảo dialog hiển thị sau khi UI đã được refresh
                                from PySide6.QtCore import QTimer
                                def show_warning_dialog():
                                    SilentMessageBox.warning(
                                        self,
                                        "Credits Thấp",
                                        f"Account: {email}\n"
                                        f"Credits: {credits:,} (<= 100)\n\n"
                                        f"⚠️ Credits quá thấp! Vui lòng:\n"
                                        f"1. Nhấn 'Sửa Profile' để mở browser\n"
                                        f"2. Check xem còn Ultra không\n"
                                        f"3. Nạp thêm credits nếu cần"
                                    )
                                QTimer.singleShot(200, show_warning_dialog)  # Đợi 200ms sau khi refresh UI
                            return
                            
                        except Exception as e:
                            continue
                    
                    self._log(f"⚠️ Không lấy được credits cho {email}")  # Terminal only
                    
                except Exception as e:
                    self._log(f"⚠️ Lỗi lấy credits cho {email}: {e}")  # Terminal only
            
            thread = threading.Thread(target=fetch_credits_thread, daemon=True)
            thread.start()
            
        except Exception as e:
            self._log(f"⚠️ Lỗi khởi tạo thread lấy credits: {e}")  # Terminal only
    
    def _on_export_txt(self):
        """Export all cookies to a single .txt file (JSON format, 2 lines between accounts)"""
        if not self.cookies_result:
            SilentMessageBox.warning(self, "Lỗi", "Chưa có cookies để xuất!\nHãy nhấn 'Lấy Cookies' trước.")
            return
        
        # Ask for save location - default to Desktop for user convenience
        default_name = f"cookies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        desktop_path = Path(os.path.expanduser("~")) / "Desktop"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Lưu file cookies",
            str(desktop_path / default_name),  # Default to Desktop
            "Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            import json
            import subprocess
            import platform
            
            def to_cookiedemo_format(raw: dict) -> dict:
                """Convert Playwright cookie -> Cookiedemo-like dict (Strict Match)"""
                # Copy raw values first
                name = raw.get("name", "")
                expires = raw.get("expires", -1)
                
                # Special handling for session-token to match demo
                if name == "__Secure-next-auth.session-token":
                    # Demo file has expirationDate for session token -> force it
                    if expires is None or expires == -1:
                        import time
                        expires = time.time() + (365 * 24 * 3600) # Fake 1 year
                        
                is_session = (expires is None) or (expires == -1)
                
                # Manual dict construction for order
                out = {}
                out["domain"] = "labs.google" # Force normalize
                
                if not is_session:
                    out["expirationDate"] = float(expires)
                    
                out["hostOnly"] = True
                out["httpOnly"] = bool(raw.get("httpOnly", False))
                out["name"] = name
                out["path"] = raw.get("path", "/")
                out["sameSite"] = (raw.get("sameSite") or "lax").lower()
                out["secure"] = bool(raw.get("secure", False))
                out["session"] = is_session
                out["storeId"] = None
                out["value"] = raw.get("value", "")
                
                return out
            
            # Xuất JSON với indent 4 (mỗi account cách nhau 2 dòng)
            all_output_str = ""
            
            for email, cookies in self.cookies_result.items():
                # Handle both list of dicts and string (legacy)
                if isinstance(cookies, list):
                    cookie_list = cookies
                elif isinstance(cookies, str):
                    # Legacy: parse string to list of dicts
                    from complete_flow import _parse_cookie_string
                    parsed = _parse_cookie_string(cookies)
                    cookie_list = [{"name": k, "value": v, "domain": "labs.google"} for k, v in parsed.items()]
                else:
                    cookie_list = []
                
                if not cookie_list:
                    continue
                
                self._log(f"📋 Account {email}: {len(cookie_list)} cookies")  # Terminal only
                
                # Sort cookies by name to match demo order somewhat
                cookie_list.sort(key=lambda x: x.get("name", ""))
                
                converted_cookies = []
                for c in cookie_list:
                    converted = to_cookiedemo_format(c)
                    converted_cookies.append(converted)
                    self._log(f"   ✓ {c.get('name')}")  # Terminal only
                
                # Append to big string: JSON block + 2 newlines
                json_block = json.dumps(converted_cookies, indent=4, ensure_ascii=False)
                all_output_str += json_block + "\n\n"
            
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(all_output_str)
            
            # UI only shows simple message
            self._log_ui(f"💾 Xuất Cookie Done - {len(self.cookies_result)} accounts")
            self._log(f"✅ Đã xuất vào: {file_path}")  # Terminal only
            result = SilentMessageBox.information(self, "Thành công", 
                f"Đã xuất cookies vào:\n{file_path}\n(Mỗi account cách nhau 2 dòng)")
            # Refresh UI sau khi đóng popup
            if result:
                self._refresh_table()
                self._refresh_cookies_table()
                self._update_status()
            
            # Open folder (platform-specific)
            folder_path = Path(file_path).parent
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['open', str(folder_path)])
            else:  # Linux
                subprocess.run(['xdg-open', str(folder_path)])
            
        except Exception as e:
            import traceback
            self._log_ui(f"💾 Xuất Cookie Fail")
            self._log(f"❌ Lỗi xuất file: {e}")  # Terminal only
            self._log(traceback.format_exc())  # Terminal only
            SilentMessageBox.warning(self, "Lỗi", f"Không thể xuất file:\n{e}")
    
    def _on_copy_cookie(self):
        """Copy all cookies to clipboard (same JSON format as export)"""
        if not self.cookies_result:
            SilentMessageBox.warning(self, "Lỗi", "Chưa có cookies để copy!\nHãy nhấn 'Lấy Cookies' trước.")
            return
        
        try:
            import json
            
            def to_cookiedemo_format(raw: dict) -> dict:
                """Convert Playwright cookie -> Cookiedemo-like dict (Strict Match)"""
                name = raw.get("name", "")
                expires = raw.get("expires", -1)
                
                # Special handling for session-token to match demo
                if name == "__Secure-next-auth.session-token":
                    if expires is None or expires == -1:
                        import time
                        expires = time.time() + (365 * 24 * 3600)  # Fake 1 year
                        
                is_session = (expires is None) or (expires == -1)
                
                out = {}
                out["domain"] = "labs.google"
                
                if not is_session:
                    out["expirationDate"] = float(expires)
                    
                out["hostOnly"] = True
                out["httpOnly"] = bool(raw.get("httpOnly", False))
                out["name"] = name
                out["path"] = raw.get("path", "/")
                out["sameSite"] = (raw.get("sameSite") or "lax").lower()
                out["secure"] = bool(raw.get("secure", False))
                out["session"] = is_session
                out["storeId"] = None
                out["value"] = raw.get("value", "")
                
                return out
            
            all_output_str = ""
            
            for email, cookies in self.cookies_result.items():
                # Handle both list of dicts and string (legacy)
                if isinstance(cookies, list):
                    cookie_list = cookies
                elif isinstance(cookies, str):
                    # Legacy: parse string to list of dicts
                    from complete_flow import _parse_cookie_string
                    parsed = _parse_cookie_string(cookies)
                    cookie_list = [{"name": k, "value": v, "domain": "labs.google"} for k, v in parsed.items()]
                else:
                    cookie_list = []
                
                if not cookie_list:
                    continue
                
                self._log(f"📋 Copy - Account {email}: {len(cookie_list)} cookies")
                
                cookie_list.sort(key=lambda x: x.get("name", ""))
                
                converted_cookies = []
                for c in cookie_list:
                    converted = to_cookiedemo_format(c)
                    converted_cookies.append(converted)
                
                json_block = json.dumps(converted_cookies, indent=4, ensure_ascii=False)
                all_output_str += json_block + "\n\n"
            
            # Copy to clipboard
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(all_output_str.strip())
            
            self._log_ui(f"📋 Đã copy Cookie - {len(self.cookies_result)} accounts")
            self._log(f"✅ Đã copy {len(self.cookies_result)} accounts vào clipboard")
            result = SilentMessageBox.information(self, "Thành công", 
                f"Đã copy cookies của {len(self.cookies_result)} accounts vào clipboard!\n(Mỗi account cách nhau 2 dòng)")
            # Refresh UI sau khi đóng popup
            if result:
                self._refresh_table()
                self._refresh_cookies_table()
                self._update_status()
            
        except Exception as e:
            import traceback
            self._log_ui(f"📋 Copy Cookie Fail")
            self._log(f"❌ Lỗi copy: {e}")
            self._log(traceback.format_exc())
            SilentMessageBox.warning(self, "Lỗi", f"Không thể copy:\n{e}")
    
    def _on_add_account(self):
        """Add new account by opening custom dialog"""
        dialog = AddAccountDialog(self)
        if dialog.exec():
            email, password, selected_profile_path = dialog.get_data()
            if not email:
                SilentMessageBox.warning(self, "Lỗi", "Email không được để trống!")
                return
            
            if selected_profile_path:
                profile_path = Path(selected_profile_path).expanduser()
            else:
                profile_path = Path(get_tool_account_profile_path(email))
            
            # Save to DB
            db_add_account(email, password, str(profile_path))
            
            # Add to memory
            new_account = {
                'email': email,
                'password': password,
                'profile_path': str(profile_path),
                'proxy_config': None,  # Mặc định không có proxy
                'selected': True,
                'profile_edited': False  # ✅ Flag để track đã "Sửa Profile" chưa
            }
            
            # Check duplicate in memory
            exists = False
            for i, acc in enumerate(self.accounts):
                if acc['email'] == email:
                    self.accounts[i] = new_account # Update
                    exists = True
                    break
            if not exists:
                self.accounts.append(new_account)
            
            self._log_ui(f"➕ Thêm TK: {email}")
            self._log(f"➕ Đã thêm tài khoản: {email}")  # Terminal
            self._refresh_table()
            self._update_status()
            
            # Auto Run
            self._log(f"🚀 Auto-running cookie fetch for {email}...")  # Terminal only
            if self.worker and self.worker.isRunning():
                self._log("⚠️ Worker đang chạy, không thể auto-run ngay. Đã thêm vào danh sách.")  # Terminal
            else:
                # Run just for this one
                self.worker = CookieWorker([new_account], force_login=False) 
                # Note: force_login=False because we just added it, standard flow. 
                # If user wants forced login they use checkbox, but for "Add" usually we try standard first.
                self.worker.progress.connect(self._on_worker_progress)
                self.worker.log.connect(self._log)
                self.worker.ui_log.connect(self._log_ui)
                self.worker.finished_signal.connect(self._on_worker_finished)
                self.worker.start()
    
    def _on_add_cookie_manual(self):
        """Add cookie manually by opening ManualCookieDialog"""
        dialog = ManualCookieDialog(self)
        if dialog.exec():
            parsed_accounts = dialog.get_data()  # List of (username, cookie_list) tuples
            
            if not parsed_accounts:
                SilentMessageBox.warning(self, "Lỗi", "Không có account hợp lệ nào!")
                return
            
            # ✅ Xử lý từng account
            success_count = 0
            
            for email_name, cookie_list in parsed_accounts:
                # Convert cookie list to format compatible with cookies_result
                self.cookies_result[email_name] = cookie_list
                
                # Add to accounts list if not exists
                exists = False
                for acc in self.accounts:
                    if acc.get('email') == email_name:
                        exists = True
                        break
                
                if not exists:
                    new_account = {
                        'email': email_name,
                        'password': '',  # No password for manual
                        'profile_path': '',
                        'proxy_config': None,  # Mặc định không có proxy
                        'selected': True,
                        'credits': None  # Will be fetched
                    }
                    self.accounts.append(new_account)
                
                success_count += 1
                
                # ✅ Lấy credits cho account thủ công (async) - Đảm bảo account đã có trong self.accounts
                # Delay nhỏ để đảm bảo account đã được thêm vào list
                # Fix lambda closure: capture email_name in default parameter
                from PySide6.QtCore import QTimer
                def fetch_credits_delayed(email):
                    """Helper function to fetch credits with delay"""
                    self._fetch_credits_for_account(email)
                
                QTimer.singleShot(100, lambda email=email_name: fetch_credits_delayed(email))
            
            # Update UI
            self._refresh_table()
            self._refresh_cookies_table()
            self._update_status()
            
            self._log_ui(f"✅ Đã thêm {success_count} account(s) thủ công")
            self._log(f"✅ Đã thêm {success_count} account(s) thủ công")  # Terminal
            
            result = SilentMessageBox.information(self, "Thành công", 
                f"Đã thêm {success_count} account(s) thủ công!\nĐang lấy credits...")
            # Refresh UI sau khi đóng popup
            if result:
                self._refresh_table()
                self._refresh_cookies_table()
                self._update_status()
    
    def _on_refresh_ui(self):
        """Refresh UI manually - refresh cả table và cookies_table"""
        try:
            # Refresh cả 2 table
            self._refresh_table()
            self._refresh_cookies_table()
            self._update_status()
            
            # Force UI update - repaint mạnh
            self.table.repaint()
            self.table.update()
            self.table.viewport().repaint()
            self.table.viewport().update()
            
            self.cookies_table.repaint()
            self.cookies_table.update()
            self.cookies_table.viewport().repaint()
            self.cookies_table.viewport().update()
            
            # Force process events nhiều lần
            for _ in range(10):
                QApplication.processEvents()
            
            self._log_ui("🔄 Đã refresh UI")
        except Exception as e:
            self._log(f"⚠️ Lỗi khi refresh UI: {e}")
    
    def _on_toggle_log(self):
        """Toggle log area visibility"""
        if self.log_area.isVisible():
            self.log_area.setVisible(False)
            self.btn_toggle_log.setText("📋 Hiện Log")
        else:
            self.log_area.setVisible(True)
            self.btn_toggle_log.setText("📋 Ẩn Log")
    
    def _refresh_cookies_table(self):
        """Refresh cookies table with auto-added cookies"""
        self.cookies_table.clearSelection()
        self.cookies_table.blockSignals(True)
        
        # ✅ Clear table trước - xóa widgets nếu có
        for row in range(self.cookies_table.rowCount()):
            widget = self.cookies_table.cellWidget(row, 0)
            if widget:
                widget.deleteLater()
        self.cookies_table.setRowCount(0)
        self.cookies_table.setRowCount(len(self.cookies_result))
        
        for row, (email_name, cookies) in enumerate(self.cookies_result.items()):
            # Email/Tên (column 0)
            self.cookies_table.setItem(row, 0, QTableWidgetItem(email_name))
            
            # Số Cookie (column 1)
            cookie_count = len(cookies) if isinstance(cookies, list) else 1
            count_item = QTableWidgetItem(f"🍪 {cookie_count}")
            count_item.setForeground(QColor("#00FF7F"))
            self.cookies_table.setItem(row, 1, count_item)
            
            # Trạng thái (column 2)
            # Check if this is from manual add or auto-fetched
            is_manual = email_name not in [acc.get('email') for acc in self.accounts]
            if is_manual:
                status_item = QTableWidgetItem("✅ Manual")
                status_item.setForeground(QColor("#6f42c1"))  # Purple for manual
            else:
                status_item = QTableWidgetItem("✅ Auto")
                status_item.setForeground(QColor("#00FF7F"))  # Green for auto
            self.cookies_table.setItem(row, 2, status_item)
        
        self.cookies_table.blockSignals(False)
        
        # ✅ Force update - repaint mạnh
        self.cookies_table.viewport().update()
        self.cookies_table.viewport().repaint()
        self.cookies_table.update()
        self.cookies_table.repaint()
        self.cookies_table.resizeColumnsToContents()
        
        # Force process events
        for _ in range(5):
            QApplication.processEvents()
    
    def _open_browser_for_login(self, email: str, password: str, profile_path: str):
        """Open browser for manual login"""
        import subprocess
        import platform
        
        self._log(f"🌐 Mở browser cho {email}...")  # Terminal only
        
        # ✅ Kill Chrome cũ đang dùng profile này trước khi mở mới (tránh lock profile → treo)
        self._kill_chrome_for_profile_static(profile_path)
        time.sleep(1)
        
        # Find Chrome executable (platform-specific)
        system = platform.system()
        chrome_exe = None
        
        if system == "Windows":
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
            for path in chrome_paths:
                if Path(path).exists():
                    chrome_exe = path
                    break
        elif system == "Darwin":  # macOS
            chrome_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
            for path in chrome_paths:
                if Path(path).exists():
                    chrome_exe = path
                    break
        
        if not chrome_exe:
            SilentMessageBox.warning(self, "Lỗi", "Không tìm thấy Chrome!")
            return

        profile_info = resolve_chrome_profile(profile_path)
        user_data_dir = profile_info["user_data_dir"] or profile_path
        profile_directory = profile_info["profile_directory"]
        
        # Launch Chrome with profile
        args = [
            chrome_exe,
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--disable-blink-features=AutomationControlled",
            "https://accounts.google.com"
        ]
        if profile_directory:
            args.insert(2, f"--profile-directory={profile_directory}")
        
        try:
            if system == "Windows":
                subprocess.Popen(args, creationflags=0x08000000)
            else:
                subprocess.Popen(args)
            self._log("✅ Đã mở Chrome - hãy đăng nhập thủ công!")  # Terminal only
            self._log("   Sau khi đăng nhập xong, nhấn 'Lấy Cookies' để lấy cookies.")  # Terminal
        except Exception as e:
            self._log(f"❌ Lỗi mở Chrome: {e}")  # Terminal only
    
    def _kill_chrome_for_profile_static(self, profile_path: str):
        """Kill Chrome processes đang dùng profile này (dùng ngoài CookieWorker)."""
        import subprocess as sp
        import platform

        info = resolve_chrome_profile(profile_path)
        user_data_dir = info["user_data_dir"] or profile_path
        profile_name = Path(info["profile_storage_path"] or profile_path).name
        
        # Xóa lock files
        for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_file = Path(user_data_dir) / lock_name
            try:
                if lock_file.exists():
                    lock_file.unlink()
            except Exception:
                pass
        
        system = platform.system()
        try:
            if system == "Windows":
                for browser in ['chrome.exe', 'chromium.exe']:
                    try:
                        result = sp.run(
                            ['wmic', 'process', 'where', f"name='{browser}'", 'get', 'processid,commandline'],
                            capture_output=True, text=True, timeout=10, creationflags=0x08000000
                        )
                        for line in result.stdout.split('\n'):
                            if profile_name in line or user_data_dir in line:
                                parts = line.strip().split()
                                if parts:
                                    try:
                                        pid = int(parts[-1])
                                        sp.run(['taskkill', '/F', '/PID', str(pid)],
                                               capture_output=True, timeout=5, creationflags=0x08000000)
                                    except (ValueError, Exception):
                                        pass
                    except Exception:
                        pass
            elif system == "Darwin":
                result = sp.run(
                    ['ps', 'aux'], capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if ('Google Chrome' in line or 'Chromium' in line) and (user_data_dir in line or profile_name in line):
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                sp.run(['kill', '-9', str(pid)], capture_output=True, timeout=5)
                            except Exception:
                                pass
        except Exception:
            pass
    
    def _on_select_all(self):
        """Select all accounts"""
        for row in range(self.table.rowCount()):
            checkbox = self.table.item(row, 0)
            if checkbox:
                checkbox.setCheckState(Qt.Checked)
        self._log("✓ Đã chọn tất cả")  # Terminal only
    
    def _on_deselect_all(self):
        """Deselect all accounts"""
        for row in range(self.table.rowCount()):
            checkbox = self.table.item(row, 0)
            if checkbox:
                checkbox.setCheckState(Qt.Unchecked)
        self._log("✗ Đã bỏ chọn tất cả")  # Terminal only
    
    def _on_open_proxy_pool(self):
        """Open Proxy Pool management dialog"""
        dialog = ProxyPoolDialog(self)
        dialog.proxy_pool_changed.connect(self._on_proxy_pool_changed)
        dialog.exec()
    
    def _on_proxy_pool_changed(self):
        """Handle proxy pool changes - sync to LabsFlowClient"""
        self._update_proxy_status()
        # Sync proxy pool data to LabsFlowClient
        try:
            from complete_flow import LabsFlowClient
            LabsFlowClient.sync_proxy_pool()
        except Exception as e:
            print(f"Error syncing proxy pool: {e}")
    
    def _on_proxy_pool_checkbox_changed(self, state):
        """Handle proxy pool checkbox change"""
        enabled = state == Qt.Checked
        
        # Update ProxyManager
        try:
            from proxy_manager import ProxyManager
            pm = ProxyManager.get_instance()
            pm.set_enabled(enabled)
        except Exception as e:
            print(f"Error setting proxy pool: {e}")
        
        # Update LabsFlowClient
        try:
            from complete_flow import LabsFlowClient
            LabsFlowClient.set_use_proxy_pool(enabled)
        except Exception as e:
            print(f"Error setting LabsFlowClient proxy pool: {e}")
        
        # Update status indicator
        self._update_proxy_status()
        
        # Save setting
        self._save_settings()
    
    def _update_proxy_status(self):
        """Update proxy pool status indicator"""
        try:
            from proxy_manager import ProxyManager
            pm = ProxyManager.get_instance()
            count = len(pm.get_all_proxies())
            enabled = pm.is_enabled()
            
            if enabled and count > 0:
                self.lbl_proxy_status.setText(f"🌐 Proxy: ON ({count})")
                self.lbl_proxy_status.setStyleSheet("color: #28a745; font-size: 12px; margin-right: 10px; font-weight: bold;")
            elif count > 0:
                self.lbl_proxy_status.setText(f"🌐 Proxy: OFF ({count})")
                self.lbl_proxy_status.setStyleSheet("color: #ffc107; font-size: 12px; margin-right: 10px;")
            else:
                self.lbl_proxy_status.setText("🌐 Proxy: OFF")
                self.lbl_proxy_status.setStyleSheet("color: #6c757d; font-size: 12px; margin-right: 10px;")
        except Exception as e:
            self.lbl_proxy_status.setText("🌐 Proxy: N/A")
            self.lbl_proxy_status.setStyleSheet("color: #6c757d; font-size: 12px; margin-right: 10px;")
    
    def _manage_proxy(self, email: str):
        """Mở dialog để quản lý proxy cho account"""
        # Load proxy config hiện tại
        current_proxy = db_get_account_proxy_config(email)
        
        dialog = ProxyDialog(self, email=email, current_proxy=current_proxy)
        if dialog.exec():
            proxy_config = dialog.get_data()
            # Lưu vào DB
            if db_update_account_proxy_config(email, proxy_config):
                # Update trong memory
                for acc in self.accounts:
                    if acc.get('email') == email:
                        acc['proxy_config'] = proxy_config
                        break
                
                if proxy_config:
                    self._log_ui(f"✅ Đã lưu proxy cho {email}: {proxy_config.get('server', 'N/A')}")
                    self._log(f"✅ Đã lưu proxy cho {email}: {proxy_config.get('server', 'N/A')}")
                else:
                    self._log_ui(f"✅ Đã xóa proxy cho {email} (dùng None)")
                    self._log(f"✅ Đã xóa proxy cho {email} (dùng None)")
            else:
                SilentMessageBox.warning(self, "Lỗi", "Không thể lưu proxy config!")
    
    def _delete_single_account(self, email: str):
        """Xóa 1 account đơn giản - không confirm, xóa trực tiếp"""
        import shutil
        
        # Tìm account
        account = None
        for acc in self.accounts:
            if acc.get('email') == email:
                account = acc
                break
        
        if not account:
            return
        
        # Xóa trực tiếp (không confirm)
        profile_path = account.get('profile_path', '')
        
        # 1. Xóa profile folder
        if profile_path and Path(profile_path).exists():
            try:
                if is_managed_profile_path(profile_path, str(PROFILES_DIR)):
                    shutil.rmtree(profile_path)
                    self._log(f"🗑️ Đã xóa profile: {email}")
                else:
                    self._log(f"🛡️ Bỏ qua xóa profile ngoài tool: {profile_path}")
            except Exception as e:
                self._log(f"⚠️ Lỗi xóa profile: {e}")
        
        # 2. Xóa khỏi DB
        try:
            db_delete_account(email)
            self._log(f"🗑️ Đã xóa khỏi DB: {email}")
        except Exception as e:
            self._log(f"⚠️ Lỗi xóa DB: {e}")
        
        # 3. Xóa khỏi accounts list
        self.accounts = [acc for acc in self.accounts if acc.get('email') != email]
        
        # 4. Xóa cookies
        self.cookies_result.pop(email, None)
        
        # 5. Refresh UI NGAY LẬP TỨC - tự động gọi refresh
        self._on_refresh_ui()
        self._log_ui(f"✅ Đã xóa: {email}")
    
    def _on_clean_profiles(self):
        """Xóa nhiều accounts đã chọn - không confirm, xóa trực tiếp"""
        import shutil
        
        # Lấy danh sách accounts đã chọn
        selected_accounts = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                if row < len(self.accounts):
                    account = self.accounts[row]
                    email = account.get('email', '')
                    if email:
                        selected_accounts.append((email, account))
        
        if not selected_accounts:
            return
        
        # Xóa trực tiếp (không confirm)
        emails_to_remove = []
        for email, account in selected_accounts:
            profile_path = account.get('profile_path', '')
            
            # Xóa profile folder
            if profile_path and Path(profile_path).exists():
                try:
                    if is_managed_profile_path(profile_path, str(PROFILES_DIR)):
                        shutil.rmtree(profile_path)
                        self._log(f"🗑️ Đã xóa profile: {email}")
                    else:
                        self._log(f"🛡️ Bỏ qua xóa profile ngoài tool: {profile_path}")
                except Exception as e:
                    self._log(f"⚠️ Lỗi xóa profile {email}: {e}")
            
            # Xóa khỏi DB
            try:
                db_delete_account(email)
                self._log(f"🗑️ Đã xóa khỏi DB: {email}")
            except Exception as e:
                self._log(f"⚠️ Lỗi xóa DB {email}: {e}")
            
            emails_to_remove.append(email)
        
        # Xóa khỏi accounts list
        self.accounts = [acc for acc in self.accounts if acc.get('email') not in emails_to_remove]
        
        # Xóa cookies
        for email in emails_to_remove:
            self.cookies_result.pop(email, None)
        
        # Refresh UI NGAY LẬP TỨC - tự động gọi refresh
        self._on_refresh_ui()
        self._log_ui(f"✅ Đã xóa {len(emails_to_remove)} account(s)")


def main():
    # Disable beep sounds (cross-platform)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Set app icon for taskbar
    from PySide6.QtGui import QIcon
    icon_files = ["cookie_icon.ico", "cookie_icon.png", "icon.ico", "icon.png"]
    for icon_name in icon_files:
        icon_path = TOOL_DIR / icon_name
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break
    
    # Override QApplication beep (works on all platforms)
    app.beep = lambda: None
    
    # Dark palette
    from PySide6.QtGui import QPalette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)
    
    window = GetCookieJSWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

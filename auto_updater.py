"""
Auto Updater Module - Tự động cập nhật ứng dụng
Kiểm tra version từ Supabase và tải bản mới từ GitHub Releases
"""

import os
import sys
import tempfile
import subprocess
import requests
import threading
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime

# Supabase config
SUPABASE_URL = "https://vmgqbkadkxaucnzfmpmo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZtZ3Fia2Fka3hhdWNuemZtcG1vIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE3OTcwMDQsImV4cCI6MjA3NzM3MzAwNH0.kCwSd_MEptWVonItr2VFWReLopF7BKWpK5hI8u97txc"

# ============================================
# THÔNG TIN PHIÊN BẢN HIỆN TẠI
# ============================================
CURRENT_VERSION = "0601"
CURRENT_VERSION_CODE = 601  # ✅ Phải là int để so sánh
APP_NAME = "veo3_ultra"


class AutoUpdater:
    """Quản lý việc kiểm tra và cập nhật ứng dụng"""
    
    def __init__(self, log_callback=None):
        """
        Args:
            log_callback: Hàm để log message (ví dụ: self.log từ GUI)
        """
        self.log_callback = log_callback
        self.update_info = None
        self.download_progress = 0
        self.is_downloading = False
    
    def log(self, message: str):
        """Log message"""
        print(message)
        if self.log_callback:
            try:
                self.log_callback(message)
            except:
                pass
    
    def check_for_updates(self) -> Tuple[bool, Optional[Dict]]:
        """
        Kiểm tra xem có bản cập nhật mới không
        
        Returns:
            (has_update, update_info) hoặc (False, None) nếu không có
        """
        try:
            url = f"{SUPABASE_URL}/rest/v1/app_versions"
            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}"
            }
            # Lấy record mới nhất (không filter app_name)
            params = {
                "order": "version_code.desc",
                "limit": "1"
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            versions = response.json()
            if not versions:
                self.log("ℹ️ Không tìm thấy thông tin phiên bản trên server")
                return False, None
            
            latest = versions[0]
            latest_code = int(latest.get("version_code", 0))
            
            self.log(f"🔍 Phiên bản hiện tại: {CURRENT_VERSION} (code: {CURRENT_VERSION_CODE})")
            self.log(f"🔍 Phiên bản mới nhất: {latest.get('version')} (code: {latest_code})")
            
            if latest_code > CURRENT_VERSION_CODE:
                self.update_info = latest
                self.log(f"🆕 Có bản cập nhật mới: v{latest.get('version')}")
                return True, latest
            else:
                self.log("✅ Bạn đang dùng phiên bản mới nhất!")
                return False, None
            
        except requests.exceptions.RequestException as e:
            self.log(f"⚠️ Không thể kiểm tra cập nhật (lỗi mạng): {e}")
            return False, None
        except Exception as e:
            self.log(f"❌ Lỗi kiểm tra cập nhật: {e}")
            return False, None
    
    def get_current_exe_path(self) -> Optional[Path]:
        """
        Lấy đường dẫn file exe hiện tại đang chạy
        Hỗ trợ cả PyInstaller và Nuitka
        """
        try:
            # Cách 1: sys.executable khi frozen (PyInstaller/Nuitka)
            if getattr(sys, 'frozen', False):
                return Path(sys.executable)
            
            # Cách 2: Kiểm tra __compiled__ (Nuitka specific)
            if "__compiled__" in dir():
                return Path(sys.executable)
            
            # Cách 3: Kiểm tra tên file executable có phải .exe không
            exe_path = Path(sys.executable)
            if exe_path.suffix.lower() == '.exe' and 'python' not in exe_path.name.lower():
                return exe_path
            
            # Không phải exe
            return None
        except:
            return None
    
    def download_update(self, download_url: str, progress_callback=None) -> Optional[Path]:
        """
        Tải file cập nhật về CÙNG THƯ MỤC với exe hiện tại
        
        Args:
            download_url: URL file cập nhật
            progress_callback: Hàm callback(percent) để cập nhật progress
        
        Returns:
            Path đến file đã tải hoặc None nếu thất bại
        """
        try:
            self.is_downloading = True
            
            # Lấy thư mục chứa exe hiện tại
            current_exe = self.get_current_exe_path()
            if current_exe:
                # Download vào cùng thư mục với exe
                download_dir = current_exe.parent
                # Tên file mới: thêm _update vào cuối
                new_filename = f"{current_exe.stem}_update{current_exe.suffix}"
            else:
                # Fallback: dùng thư mục tạm
                download_dir = Path(tempfile.gettempdir()) / "veo3_updates"
                download_dir.mkdir(exist_ok=True)
                new_filename = download_url.split("/")[-1]
            
            download_file = download_dir / new_filename
            
            self.log(f"📥 Đang tải: {new_filename}")
            self.log(f"📁 Lưu tại: {download_dir}")
            
            # Stream download
            response = requests.get(download_url, stream=True, timeout=300)
            response.raise_for_status()
            
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            
            with open(download_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):  # 64KB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            self.download_progress = int((downloaded / total_size) * 100)
                            
                            # Log progress mỗi 10%
                            if self.download_progress % 10 == 0:
                                self.log(f"📥 Đang tải: {self.download_progress}% ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)")
                            
                            if progress_callback:
                                progress_callback(self.download_progress)
            
            self.log(f"✅ Tải xong: {download_file}")
            self.is_downloading = False
            return download_file
            
        except Exception as e:
            self.log(f"❌ Lỗi tải cập nhật: {e}")
            self.is_downloading = False
            return None
    
    def apply_update(self, update_file: Path) -> bool:
        """
        Áp dụng bản cập nhật
        
        Quy trình đơn giản:
        1. Tạo updater.bat script
        2. Script sẽ: đợi app đóng → xóa file cũ → rename file mới → restart
        """
        try:
            current_exe = self.get_current_exe_path()
            
            if not current_exe:
                # Không phải exe - hiển thị đường dẫn file đã tải
                self.log("⚠️ Không phát hiện đang chạy từ file .exe")
                self.log(f"📁 File mới đã tải tại: {update_file}")
                return False
            
            self.log(f"📍 File exe hiện tại: {current_exe}")
            self.log(f"📦 File cập nhật: {update_file}")
            self.log(f"🔧 Đang tạo script cập nhật...")
            
            # Tạo updater script
            updater_script = self._create_updater_script(current_exe, update_file)
            
            self.log(f"🚀 Đang khởi động updater và đóng ứng dụng...")
            
            # Chạy updater script trong process mới
            if sys.platform == "win32":
                subprocess.Popen(
                    ["cmd", "/c", "start", "", str(updater_script)],
                    creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS
                )
            
            return True
            
        except Exception as e:
            self.log(f"❌ Lỗi áp dụng cập nhật: {e}")
            return False
    
    def _create_updater_script(self, current_exe: Path, new_file: Path) -> Path:
        """Tạo batch script đơn giản để thay thế file và restart"""
        script_path = current_exe.parent / "veo3_updater.bat"
        
        script_content = f'''@echo off
chcp 65001 >nul
title VEO3 Ultra - Auto Updater
color 0A

echo.
echo ========================================
echo   VEO3 Ultra - Dang cap nhat...
echo ========================================
echo.

echo [1/3] Dang doi ung dung dong...
timeout /t 2 /nobreak > nul

:waitloop
tasklist /FI "IMAGENAME eq {current_exe.name}" 2>NUL | find /I /N "{current_exe.name}">NUL
if "%ERRORLEVEL%"=="0" (
    echo      Ung dung van dang chay, doi them...
    timeout /t 2 /nobreak > nul
    goto waitloop
)

echo [2/3] Dang thay the file...
del /f /q "{current_exe}" 2>nul
timeout /t 1 /nobreak > nul
ren "{new_file}" "{current_exe.name}"

echo [3/3] Dang khoi dong lai...
timeout /t 1 /nobreak > nul
start "" "{current_exe}"

echo.
echo ========================================
echo   Cap nhat hoan tat!
echo ========================================
timeout /t 2 /nobreak > nul

:: Xoa script
del "%~f0"
'''
        
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        
        return script_path


def get_current_version() -> str:
    """Lấy phiên bản hiện tại"""
    return CURRENT_VERSION


def get_current_version_code() -> int:
    """Lấy version code hiện tại"""
    return CURRENT_VERSION_CODE


# ============================================
# TEST
# ============================================

if __name__ == "__main__":
    print("="*50)
    print("TEST AUTO UPDATER")
    print("="*50)
    
    updater = AutoUpdater()
    
    # 1. Check for updates
    has_update, info = updater.check_for_updates()
    
    if has_update:
        print(f"\n📦 Update info: {info}")
        
        # 2. Download (uncomment để test)
        # update_file = updater.download_update(info['download_url'])
        # if update_file:
        #     updater.apply_update(update_file)
    else:
        print("\n✅ No updates available")

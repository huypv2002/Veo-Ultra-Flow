"""
Auto-Update System - Kiểm tra và cập nhật ứng dụng từ GitHub Releases
Theo documentation: CREATE_NEW_CONSOLE only, KHÔNG dùng DETACHED_PROCESS
"""

import os
import sys
import subprocess
import zipfile
import shutil
import traceback
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None

from PySide6.QtCore import QThread, Signal

from src.core.version import APP_VERSION


# ============================================================
# CẤU HÌNH — SỬA CHO PHÙ HỢP PROJECT CỦA BẠN
# ============================================================
GITHUB_OWNER = "huypv2002"
GITHUB_REPO = "Veo-Ultra-Flow"
ASSET_NAME = "Veo3-Ultra-windows.zip"
EXE_NAME = "Veo3-Ultra.exe"
# ============================================================

RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _log(msg: str):
    """Log ra console VÀ file để debug."""
    print(msg)
    try:
        app_dir = _get_app_dir()
        log_file = os.path.join(app_dir, "updater.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def _get_app_dir() -> str:
    """Lấy thư mục chứa exe hiện tại."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_version(tag: str) -> tuple:
    """Parse 'v1.2.3' → (1, 2, 3) để so sánh."""
    tag = tag.lstrip("vV").strip()
    parts = []
    for p in tag.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _is_newer(remote_tag: str) -> bool:
    return _parse_version(remote_tag) > _parse_version(APP_VERSION)


class UpdateChecker(QThread):
    """Check GitHub Releases API cho bản mới (chạy background thread)."""
    # Signal: (has_update, tag, download_url, release_notes, error)
    result = Signal(bool, str, str, str, str)

    def run(self):
        if httpx is None:
            self.result.emit(False, "", "", "", "httpx not installed")
            return
        try:
            r = httpx.get(RELEASES_API, timeout=15, follow_redirects=True)
            if r.status_code != 200:
                self.result.emit(False, "", "", "", f"HTTP {r.status_code}")
                return

            data = r.json()
            tag = data.get("tag_name", "")
            body = data.get("body", "") or ""

            if not tag or not _is_newer(tag):
                self.result.emit(False, tag, "", "", "")
                return

            # Tìm asset ZIP trong release
            dl_url = ""
            for asset in data.get("assets", []):
                if asset.get("name", "") == ASSET_NAME:
                    dl_url = asset.get("browser_download_url", "")
                    break

            if not dl_url:
                self.result.emit(False, tag, "", body, f"Không tìm thấy {ASSET_NAME} trong release")
                return

            self.result.emit(True, tag, dl_url, body, "")
        except Exception as e:
            self.result.emit(False, "", "", "", str(e))


class UpdateDownloader(QThread):
    """Download ZIP + extract vào thư mục tạm."""
    progress = Signal(int)           # percent 0-100
    finished = Signal(bool, str)     # (ok, new_app_dir hoặc error)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        if httpx is None:
            self.finished.emit(False, "httpx not installed")
            return
        try:
            app_dir = _get_app_dir()
            update_dir = os.path.join(app_dir, "_update_tmp")

            # Dọn thư mục tạm cũ nếu có
            if os.path.exists(update_dir):
                shutil.rmtree(update_dir, ignore_errors=True)
            os.makedirs(update_dir, exist_ok=True)

            zip_path = os.path.join(update_dir, ASSET_NAME)

            # Download với progress (stream 64KB chunks)
            with httpx.stream("GET", self.download_url, timeout=300, follow_redirects=True) as r:
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        if self._stopped:
                            self.finished.emit(False, "Đã hủy")
                            return
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(int(downloaded * 100 / total))

            self.progress.emit(100)

            # Extract ZIP
            extract_dir = os.path.join(update_dir, "extracted")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Tìm thư mục chứa EXE trong ZIP
            new_app_dir = None
            for item in os.listdir(extract_dir):
                candidate = os.path.join(extract_dir, item)
                if os.path.isdir(candidate):
                    if os.path.exists(os.path.join(candidate, EXE_NAME)):
                        new_app_dir = candidate
                        break

            # Fallback: exe nằm trực tiếp trong extract_dir
            if not new_app_dir:
                if os.path.exists(os.path.join(extract_dir, EXE_NAME)):
                    new_app_dir = extract_dir
                else:
                    # Thử tìm bất kỳ .exe nào
                    for root, dirs, files in os.walk(extract_dir):
                        for f in files:
                            if f.endswith(".exe"):
                                new_app_dir = root
                                break
                        if new_app_dir:
                            break

            if not new_app_dir:
                self.finished.emit(False, f"Không tìm thấy {EXE_NAME} trong ZIP")
                return

            self.finished.emit(True, new_app_dir)
        except Exception as e:
            self.finished.emit(False, str(e))


def apply_update(new_app_dir: str):
    """
    Tạo _updater.bat rồi launch nó, sau đó app thoát.
    Theo docs: CHỈ dùng CREATE_NEW_CONSOLE, KHÔNG kết hợp DETACHED_PROCESS
    """
    app_dir = _get_app_dir()
    current_pid = os.getpid()
    bat_path = os.path.join(app_dir, "_updater.bat")

    _log(f"[updater] app_dir: {app_dir}")
    _log(f"[updater] new_app_dir: {new_app_dir}")
    _log(f"[updater] PID: {current_pid}")

    # ============================================================
    # NỘI DUNG BATCH SCRIPT (theo documentation)
    # ============================================================
    bat_content = f'''@echo off
chcp 65001 >nul
title Updating {EXE_NAME}...
echo ============================================
echo   Dang cap nhat...
echo ============================================
echo.

:: ========== BUOC 1: Cho process cu tat ==========
echo Cho ung dung cu dong lai...
set /a count=0
:wait_loop
tasklist /FI "PID eq {current_pid}" 2>nul | find /I "{current_pid}" >nul
if not errorlevel 1 (
    set /a count+=1
    if %count% GEQ 30 (
        echo Timeout! Force kill...
        taskkill /PID {current_pid} /F >nul 2>&1
        timeout /t 2 /nobreak >nul
        goto :do_update
    )
    timeout /t 1 /nobreak >nul
    goto :wait_loop
)

:do_update
echo Dang cap nhat files...
timeout /t 1 /nobreak >nul

:: ========== BUOC 2: Xoa files/folders cu ==========
:: Xoa TAT CA files trong app_dir, NGOAI TRU _updater.bat va _update_tmp
for %%F in ("{app_dir}\\*") do (
    if /I not "%%~nxF"=="_updater.bat" (
        if /I not "%%~nxF"=="_update_tmp" (
            del /F /Q "%%F" >nul 2>&1
        )
    )
)
:: Xoa TAT CA folders, NGOAI TRU data/, output/, _update_tmp/
for /D %%D in ("{app_dir}\\*") do (
    if /I not "%%~nxD"=="data" (
        if /I not "%%~nxD"=="output" (
            if /I not "%%~nxD"=="_update_tmp" (
                rmdir /S /Q "%%D" >nul 2>&1
            )
        )
    )
)

:: ========== BUOC 3: Copy ban moi vao ==========
:: Copy files (KHONG ghi de data/ va output/ — giu data cua user)
echo Copy ban moi...
for %%F in ("{new_app_dir}\\*") do (
    copy /Y "%%F" "{app_dir}\\" >nul 2>&1
)
for /D %%D in ("{new_app_dir}\\*") do (
    if /I not "%%~nxD"=="data" (
        if /I not "%%~nxD"=="output" (
            xcopy /E /I /Y "%%D" "{app_dir}\\%%~nxD" >nul 2>&1
        )
    )
)

:: ========== BUOC 4: Don dep ==========
echo Don dep...
rmdir /S /Q "{app_dir}\\_update_tmp" >nul 2>&1

:: ========== BUOC 5: Start ban moi ==========
echo Khoi dong ban moi...
start "" "{app_dir}\\{EXE_NAME}"

:: ========== BUOC 6: Tu xoa batch file ==========
echo Cap nhat thanh cong!
timeout /t 2 /nobreak >nul
del /F /Q "%~f0" >nul 2>&1
exit
'''

    # Ghi batch file
    _log(f"[updater] Writing batch to: {bat_path}")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    # Launch batch script trong console riêng
    # THEO DOCS: CHI dung CREATE_NEW_CONSOLE, KHONG ket hop DETACHED_PROCESS
    _log(f"[updater] Launching batch with CREATE_NEW_CONSOLE...")
    try:
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        _log(f"[updater] Batch launched, exiting app...")
    except Exception as e:
        _log(f"[updater] Failed to launch batch: {e}")
        # Fallback: thu cach khac
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                cwd=app_dir,
            )
            _log(f"[updater] Batch launched via cmd.exe fallback")
        except Exception as e2:
            _log(f"[updater] Fallback also failed: {e2}")
            raise

    # App thoat ngay de batch script co the xoa/ghi de files
    # Dung os._exit() thay vi sys.exit() de force kill tat ca threads
    os._exit(0)

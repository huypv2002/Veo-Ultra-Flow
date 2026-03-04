"""
Auto-Update System - Kiểm tra và cập nhật ứng dụng từ GitHub Releases
Dùng httpx cho cả check API và download (streaming, timeout, follow_redirects)
"""

import os
import sys
import subprocess
import zipfile
import shutil
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None

from PySide6.QtCore import QThread, Signal

from src.core.version import APP_VERSION

# ============================================
# Cấu hình GitHub
# ============================================
GITHUB_OWNER = "huypv2002"
GITHUB_REPO = "Veo-Ultra-Flow"
ASSET_NAME = "Veo3-Ultra-windows.zip"


def _parse_version(tag: str) -> tuple:
    """Parse version string thành tuple để so sánh.

    Examples:
        "v1.8"   -> (1, 8)
        "v2.0.1" -> (2, 0, 1)
        "1.0"    -> (1, 0)
    """
    tag = tag.lstrip("v")
    parts = tag.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0, 0, 0)


class UpdateChecker(QThread):
    """Thread kiểm tra phiên bản mới từ GitHub Releases API."""

    # Signal: (has_update, tag, download_url, release_notes, error)
    check_finished = Signal(bool, str, str, str, str)

    def run(self):
        if httpx is None:
            self.check_finished.emit(False, "", "", "", "httpx not installed")
            return
        try:
            url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
            response.raise_for_status()
            data = response.json()

            tag = data.get("tag_name", "")
            if not tag:
                self.check_finished.emit(False, "", "", "", "No tag found in release")
                return

            # So sánh version
            remote = _parse_version(tag)
            local = _parse_version(APP_VERSION)
            if remote <= local:
                self.check_finished.emit(False, tag, "", "", "")
                return

            # Tìm asset download URL
            download_url = ""
            for asset in data.get("assets", []):
                if asset.get("name") == ASSET_NAME:
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url:
                self.check_finished.emit(False, tag, "", "", f"Asset '{ASSET_NAME}' not found")
                return

            release_notes = data.get("body", "") or ""
            self.check_finished.emit(True, tag, download_url, release_notes, "")

        except Exception as e:
            self.check_finished.emit(False, "", "", "", f"Error: {e}")


class UpdateDownloader(QThread):
    """Thread tải bản cập nhật ZIP và extract."""

    # Signal: (success, extracted_path_or_error)
    download_finished = Signal(bool, str, str)
    # Signal: (percent, downloaded_mb, total_mb)
    progress_updated = Signal(int, float, float)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url

    def run(self):
        if httpx is None:
            self.download_finished.emit(False, "", "httpx not installed")
            return
        try:
            # Xác định thư mục app
            if getattr(sys, "frozen", False):
                app_dir = Path(sys.executable).parent
            else:
                app_dir = Path(__file__).parent.parent.parent

            update_tmp = app_dir / "_update_tmp"
            if update_tmp.exists():
                shutil.rmtree(update_tmp, ignore_errors=True)
            update_tmp.mkdir(exist_ok=True)

            zip_path = update_tmp / ASSET_NAME

            # Download với progress (stream, 64KB chunks)
            with httpx.stream("GET", self.download_url, timeout=300, follow_redirects=True) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("content-length", 0))
                total_mb = total_size / (1024 * 1024) if total_size > 0 else 0
                downloaded = 0
                last_pct = -1

                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 100)
                                if pct != last_pct:
                                    last_pct = pct
                                    self.progress_updated.emit(
                                        pct,
                                        downloaded / (1024 * 1024),
                                        total_mb,
                                    )

            # Extract ZIP
            extracted_dir = update_tmp / "extracted"
            extracted_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extracted_dir)

            # Tìm thư mục chứa exe trong ZIP
            new_app_dir = None
            for item in extracted_dir.iterdir():
                if item.is_dir():
                    exe_files = list(item.glob("*.exe"))
                    if exe_files:
                        new_app_dir = item
                        break

            if not new_app_dir:
                for item in extracted_dir.rglob("*.exe"):
                    new_app_dir = item.parent
                    break

            if new_app_dir:
                self.download_finished.emit(True, str(new_app_dir), "")
            else:
                self.download_finished.emit(False, "", "Không tìm thấy .exe trong ZIP")

        except Exception as e:
            self.download_finished.emit(False, "", f"Error: {e}")


def apply_update(new_app_dir: str) -> bool:
    """Áp dụng bản cập nhật: tạo _updater.bat, thoát app.

    Batch script logic:
      1. Chờ process cũ tắt (poll PID, timeout 30s → force kill)
      2. Xóa files/folders CŨ, NGOẠI TRỪ: data/, output/, _update_tmp/, _updater.bat
      3. Copy bản mới vào (NGOẠI TRỪ data/ và output/)
      4. Start exe mới
      5. Xóa _update_tmp/ và tự xóa _updater.bat
    """
    if not getattr(sys, "frozen", False):
        print("[updater] Không phải frozen exe, bỏ qua apply_update.")
        return False

    try:
        current_exe = Path(sys.executable)
        app_dir = current_exe.parent
        exe_name = "Veo3-Ultra.exe"
        new_app_path = Path(new_app_dir).resolve()
        pid = os.getpid()

        batch_content = f'''@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Veo3 Ultra - Updating...
color 0A

echo.
echo ========================================
echo   Veo3 Ultra - Dang cap nhat...
echo ========================================
echo.

echo [1/5] Dang doi ung dung dong...

:: Wait for old process (PID {pid}) to exit, timeout 30s
set /a WAIT=0
:wait_loop
tasklist /FI "PID eq {pid}" 2>NUL | findstr /I "{pid}" >NUL
if %ERRORLEVEL%==0 (
    set /a WAIT+=2
    if !WAIT! GEQ 30 (
        echo    Timeout - force kill PID {pid}
        taskkill /F /PID {pid} >NUL 2>&1
        timeout /t 2 /nobreak >nul
        goto done_wait
    )
    echo    Ung dung van chay, doi them... (!WAIT!s)
    timeout /t 2 /nobreak >nul
    goto wait_loop
)
:done_wait
echo    OK - Ung dung da dong.

echo [2/5] Dang xoa file cu...
:: Xóa tất cả files/folders CŨ, NGOẠI TRỪ: data, output, _update_tmp, _updater.bat
for /d %%D in ("{app_dir}\\*") do (
    set "FNAME=%%~nxD"
    if /i not "!FNAME!"=="data" (
        if /i not "!FNAME!"=="output" (
            if /i not "!FNAME!"=="_update_tmp" (
                rd /s /q "%%D" 2>nul
            )
        )
    )
)
for %%F in ("{app_dir}\\*") do (
    set "FNAME=%%~nxF"
    if /i not "!FNAME!"=="_updater.bat" (
        del /f /q "%%F" 2>nul
    )
)

echo [3/5] Dang copy file moi...
:: Copy bản mới vào app_dir (NGOẠI TRỪ data/ và output/)
for /d %%D in ("{new_app_path}\\*") do (
    set "FNAME=%%~nxD"
    if /i not "!FNAME!"=="data" (
        if /i not "!FNAME!"=="output" (
            xcopy /e /y /q "%%D" "{app_dir}\\%%~nxD\\" >nul
        )
    )
)
for %%F in ("{new_app_path}\\*") do (
    copy /y "%%F" "{app_dir}\\" >nul 2>&1
)

echo [4/5] Dang khoi dong ung dung moi...
timeout /t 1 /nobreak >nul
start "" "{app_dir}\\{exe_name}"

echo [5/5] Don dep...
timeout /t 2 /nobreak >nul
rd /s /q "{app_dir}\\_update_tmp" 2>nul

echo.
echo ========================================
echo   Cap nhat hoan tat!
echo ========================================
timeout /t 3 /nobreak >nul

:: Self delete
del "%~f0"
'''

        batch_path = app_dir / "_updater.bat"
        with open(batch_path, "w", encoding="utf-8") as f:
            f.write(batch_content)

        # Launch batch với CREATE_NEW_CONSOLE
        subprocess.Popen(
            ["cmd", "/c", str(batch_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=str(app_dir),
        )

        # Thoát app ngay
        os._exit(0)

    except Exception as e:
        print(f"[updater] Error applying update: {e}")
        return False

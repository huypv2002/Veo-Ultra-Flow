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
    """Parse version string thành tuple để so sánh."""
    tag = tag.lstrip("v")
    parts = tag.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0, 0, 0)


class UpdateChecker(QThread):
    """Thread kiểm tra phiên bản mới từ GitHub Releases API."""

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

            remote = _parse_version(tag)
            local = _parse_version(APP_VERSION)
            if remote <= local:
                self.check_finished.emit(False, tag, "", "", "")
                return

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

    download_finished = Signal(bool, str, str)
    progress_updated = Signal(int, float, float)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url

    def run(self):
        if httpx is None:
            self.download_finished.emit(False, "", "httpx not installed")
            return
        try:
            if getattr(sys, "frozen", False):
                app_dir = Path(sys.executable).parent
            else:
                app_dir = Path(__file__).parent.parent.parent

            update_tmp = app_dir / "_update_tmp"
            if update_tmp.exists():
                shutil.rmtree(update_tmp, ignore_errors=True)
            update_tmp.mkdir(exist_ok=True)

            zip_path = update_tmp / ASSET_NAME

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
                                    self.progress_updated.emit(pct, downloaded / (1024 * 1024), total_mb)

            extracted_dir = update_tmp / "extracted"
            extracted_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extracted_dir)

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
      1. Chờ process cũ tắt (poll PID, timeout 30s -> force kill)
      2. Xóa files/folders CŨ, NGOẠI TRỪ: data/, output/, _update_tmp/, _updater.bat
      3. Copy bản mới vào (NGOẠI TRỪ data/ và output/)
      4. Start exe mới
      5. Xóa _update_tmp/ và tự xóa _updater.bat
    """
    try:
        # Xác định app_dir và exe_name
        if getattr(sys, "frozen", False):
            current_exe = Path(sys.executable)
            app_dir = current_exe.parent
            exe_name = current_exe.name
        else:
            # Dev mode - vẫn cho chạy để test
            app_dir = Path(__file__).parent.parent.parent
            exe_name = "Veo3-Ultra.exe"

        new_app_path = Path(new_app_dir).resolve()
        pid = os.getpid()

        # Tìm exe trong thư mục mới
        new_exe_candidates = list(new_app_path.glob("*.exe"))
        if new_exe_candidates:
            # Ưu tiên exe có tên Veo3-Ultra
            target_exe = None
            for candidate in new_exe_candidates:
                if "veo3" in candidate.name.lower() or "ultra" in candidate.name.lower():
                    target_exe = candidate.name
                    break
            if not target_exe:
                target_exe = new_exe_candidates[0].name
            exe_name = target_exe

        print(f"[updater] app_dir: {app_dir}")
        print(f"[updater] new_app_path: {new_app_path}")
        print(f"[updater] exe_name: {exe_name}")
        print(f"[updater] PID: {pid}")

        # Escape paths cho batch (dùng short path nếu có spaces)
        app_dir_str = str(app_dir)
        new_app_str = str(new_app_path)

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
timeout /t 2 /nobreak >nul

echo [2/5] Dang xoa file cu...
:: Xoa tat ca files/folders CU, NGOAI TRU: data, output, _update_tmp, _updater.bat
for /d %%D in ("{app_dir_str}\\*") do (
    set "FNAME=%%~nxD"
    if /i not "!FNAME!"=="data" (
        if /i not "!FNAME!"=="output" (
            if /i not "!FNAME!"=="_update_tmp" (
                echo    Xoa folder: %%~nxD
                rd /s /q "%%D" 2>nul
            )
        )
    )
)
for %%F in ("{app_dir_str}\\*") do (
    set "FNAME=%%~nxF"
    if /i not "!FNAME!"=="_updater.bat" (
        echo    Xoa file: %%~nxF
        del /f /q "%%F" 2>nul
    )
)

echo [3/5] Dang copy file moi...
:: Copy ban moi vao app_dir (NGOAI TRU data/ va output/)
for /d %%D in ("{new_app_str}\\*") do (
    set "FNAME=%%~nxD"
    if /i not "!FNAME!"=="data" (
        if /i not "!FNAME!"=="output" (
            echo    Copy folder: %%~nxD
            xcopy /e /y /q "%%D" "{app_dir_str}\\%%~nxD\\" >nul 2>&1
        )
    )
)
for %%F in ("{new_app_str}\\*") do (
    echo    Copy file: %%~nxF
    copy /y "%%F" "{app_dir_str}\\" >nul 2>&1
)

echo [4/5] Dang khoi dong ung dung moi...
timeout /t 2 /nobreak >nul
if exist "{app_dir_str}\\{exe_name}" (
    echo    Khoi dong: {exe_name}
    start "" "{app_dir_str}\\{exe_name}"
) else (
    echo    CANH BAO: Khong tim thay {exe_name}
    echo    Thu tim exe khac...
    for %%E in ("{app_dir_str}\\*.exe") do (
        echo    Tim thay: %%~nxE
        start "" "%%E"
        goto cleanup
    )
)

:cleanup
echo [5/5] Don dep...
timeout /t 3 /nobreak >nul
rd /s /q "{app_dir_str}\\_update_tmp" 2>nul

echo.
echo ========================================
echo   Cap nhat hoan tat!
echo ========================================
timeout /t 3 /nobreak >nul

:: Self delete
del "%~f0"
'''

        batch_path = app_dir / "_updater.bat"
        print(f"[updater] Writing batch to: {batch_path}")

        with open(batch_path, "w", encoding="utf-8") as f:
            f.write(batch_content)

        print(f"[updater] Launching updater batch...")

        # Launch batch - dùng nhiều cách để đảm bảo chạy được
        try:
            if sys.platform == "win32":
                # Cách 1: CREATE_NEW_CONSOLE
                subprocess.Popen(
                    ["cmd.exe", "/c", str(batch_path)],
                    creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS,
                    cwd=str(app_dir),
                    close_fds=True,
                )
            else:
                # macOS/Linux fallback
                subprocess.Popen(
                    ["bash", "-c", f'sleep 2 && echo "Update not supported on this OS"'],
                    start_new_session=True,
                )
        except Exception as launch_err:
            print(f"[updater] Launch method 1 failed: {launch_err}")
            try:
                # Cách 2: os.startfile
                os.startfile(str(batch_path))
            except Exception as launch_err2:
                print(f"[updater] Launch method 2 failed: {launch_err2}")
                try:
                    # Cách 3: start command
                    subprocess.Popen(
                        f'start "" "{batch_path}"',
                        shell=True,
                        cwd=str(app_dir),
                    )
                except Exception as launch_err3:
                    print(f"[updater] All launch methods failed: {launch_err3}")
                    return False

        print(f"[updater] Batch launched, exiting app...")

        # Thoát app ngay
        os._exit(0)

    except Exception as e:
        print(f"[updater] Error applying update: {e}")
        import traceback
        traceback.print_exc()
        return False

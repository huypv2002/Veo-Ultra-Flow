"""Shared UI widgets and worker classes extracted from gui_app_mac.py."""

from __future__ import annotations

import atexit
import math
import requests
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QPushButton, QDoubleSpinBox, QGridLayout, QLabel, QSpinBox, QToolButton, QWidget, QComboBox



# ==================== NO SCROLL WIDGETS ====================
# Custom widgets để vô hiệu hóa scroll wheel trên ComboBox và SpinBox
class NoScrollComboBox(QComboBox):
    """ComboBox không thay đổi giá trị khi lăn chuột"""
    def wheelEvent(self, event):
        # Ignore wheel event - không làm gì cả
        event.ignore()


class NoScrollSpinBox(QSpinBox):
    """SpinBox không thay đổi giá trị khi lăn chuột"""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """DoubleSpinBox không thay đổi giá trị khi lăn chuột"""
    def wheelEvent(self, event):
        event.ignore()
# ==================== END NO SCROLL WIDGETS ====================

# Import TOÀN BỘ logic từ gui_app.py (tkinter version)
from gui_app import (
    PromptTask, ImageTask, DownloadTask,
    _safe_json, _alphanum_key, natural_sort_paths,
    _extract_strings_recursive, _extract_file_urls,
    DEFAULT_GEMINI_KEYS
)

from complete_flow import LabsFlowClient, _parse_cookie_string
from captcha_bridge_server import run_bridge_server
from project_manager import ProjectManager
from iting_api import authenticate_iting_user, check_iting_session, logout_iting_user, ItingAPI
from subscription_policies import get_subscription_limits, normalize_subscription_type
from story_script_manager import StoryScriptManager, ProjectStage, SetupMode, CharacterProfile
from character_profile_parser import parse_character_profile_from_text, parse_multiple_profiles
from src.core.updater import UpdateChecker, UpdateDownloader, apply_update, APP_VERSION
from src.gui.update_dialog import UpdateDialog, UpdateButton
from chrome_profile_utils import is_managed_profile_path, resolve_chrome_profile, get_default_system_chrome_profile_path, get_tool_system_chrome_profile_path, get_tool_account_profile_path

# Import CookieWorker and AddAccountDialog from cookiauto.py
try:
    from cookiauto import CookieWorker, AddAccountDialog
except ImportError as e:
    # Fallback if cookiauto.py is not available
    CookieWorker = None
    AddAccountDialog = None
    print(f"⚠️ Warning: Could not import from cookiauto.py: {e}")


# ==================== FLOW TASK DATA ====================
@dataclass
class FlowTaskData:
    """Data model cho mỗi task row trong Task_Grid."""
    index: int                                          # STT (1-based)
    prompt: str                                         # Prompt text
    model_code: str                                     # "NARWHAL" / "GEM_PIX_2"
    aspect_ratio: str                                   # "IMAGE_ASPECT_RATIO_LANDSCAPE" / "PORTRAIT"
    seed: int                                           # Seed value
    reference_images: List[str] = field(default_factory=list)  # Paths to reference images (max 15 cho Banana Pro)
    status: str = "pending"                             # "pending" / "running" / "success" / "error"
    error_message: Optional[str] = None                 # Error detail if status == "error"
    output_path: Optional[str] = None                   # Path to saved image if success
# ==================== END FLOW TASK DATA ====================


# ==================== THUMBNAIL GRID WIDGET ====================
class ThumbnailGridWidget(QWidget):
    """Widget hiển thị grid thumbnail + nút "+" trong cell của QTableWidget."""

    images_changed = Signal(int, list)  # (row_index, image_paths)
    height_hint_changed = Signal(int, int)  # (row_index, suggested_height)

    def __init__(
        self,
        row_index: int,
        max_images: int = 3,
        parent=None,
        thumbnail_size: int = 48,
        columns: Optional[int] = None,
    ):
        super().__init__(parent)
        self.row_index = row_index
        self.max_images = max_images
        self.image_paths: List[str] = []
        self.thumbnail_size = thumbnail_size
        self.grid_columns = max(1, columns or min(max_images, 3))
        self._locked = False

        self._layout = QGridLayout(self)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._add_btn = QPushButton("+")
        self._add_btn.setFixedSize(self.thumbnail_size, self.thumbnail_size)
        self._add_btn.setStyleSheet(
            "background: #f0f9ff; border: 1px dashed #93c5fd; border-radius: 8px; "
            "font-size: 18px; font-weight: 600; color: #3b82f6;"
        )
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._layout.addWidget(self._add_btn, 0, 0)
        self.setMinimumHeight(self._compute_height())

    def add_images(self, paths: List[str]) -> None:
        """Thêm ảnh, giới hạn tối đa max_images."""
        remaining = self.max_images - len(self.image_paths)
        if remaining <= 0:
            return
        self.image_paths.extend(paths[:remaining])
        self._rebuild_layout()
        self.images_changed.emit(self.row_index, list(self.image_paths))

    def remove_image_at(self, index: int) -> None:
        """Xóa 1 ảnh theo index và cập nhật UI ngay."""
        if index < 0 or index >= len(self.image_paths):
            return
        self.image_paths.pop(index)
        self._rebuild_layout()
        self.images_changed.emit(self.row_index, list(self.image_paths))

    def _rebuild_layout(self) -> None:
        """Rebuild grid layout khi ảnh thay đổi."""
        # Clear all widgets from layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        # Add thumbnail items with a corner delete button.
        for index, path in enumerate(self.image_paths):
            item = QWidget()
            item.setFixedSize(self.thumbnail_size, self.thumbnail_size)

            lbl = QLabel(item)
            lbl.setGeometry(0, 0, self.thumbnail_size, self.thumbnail_size)
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    self.thumbnail_size, self.thumbnail_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            lbl.setPixmap(pixmap)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("border: 1px solid #e2e8f0; border-radius: 6px; background: #f8fafc;")

            remove_btn = QToolButton(item)
            remove_btn.setText("x")
            remove_btn.setCursor(Qt.PointingHandCursor)
            remove_btn.setEnabled(not self._locked)
            remove_btn.setGeometry(self.thumbnail_size - 18, 2, 16, 16)
            remove_btn.setStyleSheet(
                "QToolButton {"
                "background: rgba(239, 68, 68, 0.95);"
                "color: white;"
                "border: none;"
                "border-radius: 8px;"
                "font-size: 10px;"
                "font-weight: 700;"
                "padding: 0;"
                "}"
                "QToolButton:hover { background: rgba(220, 38, 38, 1); }"
                "QToolButton:disabled { background: rgba(148, 163, 184, 0.9); color: #e2e8f0; }"
            )
            remove_btn.clicked.connect(lambda checked=False, idx=index: self.remove_image_at(idx))
            row = index // self.grid_columns
            col = index % self.grid_columns
            self._layout.addWidget(item, row, col)

        # Show "+" button only if under max
        if len(self.image_paths) < self.max_images:
            self._add_btn = QPushButton("+")
            self._add_btn.setFixedSize(self.thumbnail_size, self.thumbnail_size)
            locked = getattr(self, '_locked', False)
            self._add_btn.setEnabled(not locked)
            self._add_btn.setStyleSheet(
                f"background: {'#e2e8f0' if locked else '#f0f9ff'}; "
                f"border: 1px {'solid #cbd5e1' if locked else 'dashed #93c5fd'}; "
                f"border-radius: 8px; font-size: 18px; font-weight: 600; "
                f"color: {'#94a3b8' if locked else '#3b82f6'};"
            )
            self._add_btn.clicked.connect(self._on_add_clicked)
            next_index = len(self.image_paths)
            next_row = next_index // self.grid_columns
            next_col = next_index % self.grid_columns
            self._layout.addWidget(self._add_btn, next_row, next_col)

        suggested_height = self._compute_height()
        self.setMinimumHeight(suggested_height)
        self.height_hint_changed.emit(self.row_index, suggested_height)

    def set_locked(self, locked: bool) -> None:
        """Lock/unlock the '+' button (disable adding images while running)."""
        self._locked = locked
        # Find and disable/enable the add button
        for i in range(self._layout.count()):
            w = self._layout.itemAt(i).widget()
            if isinstance(w, QPushButton) and w.text() == "+":
                w.setEnabled(not locked)
                w.setStyleSheet(
                    f"background: {'#e2e8f0' if locked else '#f0f9ff'}; "
                    f"border: 1px {'solid #cbd5e1' if locked else 'dashed #93c5fd'}; "
                    f"border-radius: 8px; font-size: 18px; font-weight: 600; "
                    f"color: {'#94a3b8' if locked else '#3b82f6'};"
                )

    def _on_add_clicked(self) -> None:
        """Mở QFileDialog cho PNG/JPG/JPEG/WEBP, gọi add_images()."""
        if getattr(self, '_locked', False):
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            f"Chọn ảnh tham chiếu (tối đa {self.max_images} ảnh)",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if files:
            self.add_images(files)

    def _compute_height(self) -> int:
        visible_items = len(self.image_paths) + (1 if len(self.image_paths) < self.max_images else 0)
        rows = max(1, math.ceil(visible_items / self.grid_columns))
        return rows * self.thumbnail_size + max(4, (rows - 1) * self._layout.spacing()) + 8
# ==================== END THUMBNAIL GRID WIDGET ====================


def ensure_captcha_bridge_server(
    server_url: str = "http://127.0.0.1:3003",
    auto_start: bool = True,
) -> bool:
    """
    Đảm bảo Extension Bridge Server (WebSocket + HTTP) đang chạy.

    Server hỗ trợ:
      - WebSocket /ws   : Chrome Extension kết nối, nhận job, gửi token về
      - HTTP /health    : Health check (dùng để kiểm tra server còn sống)
      - HTTP /request-token, /get-captcha : Python tool gọi để request/poll token

    Extension Bridge thay thế hoàn toàn cơ chế Playwright/Patchright:
    token được lấy từ browser thật của user → trust score cao hơn.

    Args:
        server_url: URL HTTP của server (mặc định http://127.0.0.1:3003)
        auto_start: Tự động khởi động server nếu chưa chạy

    Returns:
        True nếu server đang chạy (hoặc đã start thành công)
    """
    from captcha_bridge_server import ensure_captcha_bridge_server as _ensure_bridge_server

    return _ensure_bridge_server(server_url, auto_start=auto_start)


def get_captcha_bridge_ws_url(http_url: str = "http://127.0.0.1:3003") -> str:
    """Chuyển HTTP URL thành WebSocket URL cho extension.

    Ví dụ:
        http://localhost:3003  →  ws://localhost:3003/ws
        http://127.0.0.1:3003  →  ws://127.0.0.1:3003/ws
    """
    from urllib.parse import urlparse
    parsed = urlparse(http_url.rstrip("/"))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3003
    return f"ws://{host}:{port}/ws"


def _stop_captcha_bridge_server():
    """Best-effort cleanup. Daemon thread tự thoát khi main process kết thúc."""
    global _CAPTCHA_BRIDGE_HANDLE
    _CAPTCHA_BRIDGE_HANDLE = None


atexit.register(_stop_captcha_bridge_server)


def _download_via_requests_simple(url: str, filename: Path) -> bool:
    """Download file using requests - global function for Qt6"""
    try:
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        }
        
        # Ensure directory exists
        filename.parent.mkdir(parents=True, exist_ok=True)
        
        with requests.get(url, headers=headers, stream=True, timeout=120) as r:
            r.raise_for_status()
            
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        # Verify file exists and has reasonable size
        if filename.exists() and filename.stat().st_size > 0:
            return True
        
        return False
        
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False


class WorkerSignals(QObject):
    """Thread-safe signals for worker - PHẢI là QObject"""
    new_log = Signal(str)
    add_task = Signal(object, int)  # (task, index)
    update_status = Signal(int, str)  # (task_index, status)
    update_progress = Signal(int, int)  # (task_index, progress_percent)
    update_batch = Signal(int, int)  # (current, total)
    update_image_status = Signal(int, str)  # (index, status) - cho image tab
    update_image_path = Signal(int, str)  # (index, file_path) - cho image tab
    update_image_progress = Signal(int, int, int)  # (index, current, total) - cho image progress: (index, current_image, total_images)
    matching_results_ready = Signal(dict, list)  # (matching_results, prompts) - cho custom integrate
    create_image_card = Signal(int, str, int)  # (prompt_index, prompt_text, num_images) - ✅ Tạo card động
    update_reference_image_preview_signal = Signal(str)  # (image_type) - update preview sau khi upload xong
    update_extend_project = Signal(str, int)  # (project_name, progress_percent) - cho extend project
    update_extend_segment = Signal(str, int, int)  # (project_name, segment_idx, progress_percent) - cho extend segment
    finished = Signal()
    subscription_expired = Signal(str)  # (expiry_message) - khi subscription hết hạn
    subscription_warning = Signal(str, int)  # (message, days_remaining) - cảnh báo gần hết hạn
    sync_log_message = Signal(str)  # Signal cho sync tab logs
    update_prompts_table = Signal(list)  # Signal để update prompts_table với list of video files
    wrap_cli_rotate_needed = Signal(int)  # (job_idx) - khi cần rotate IP bằng WRAP CLI
    update_character_tree = Signal()  # Signal để update character tree
    update_progress_bar = Signal(int, int)  # Signal để update progress bar: (row_index, percent)
    refresh_video_preview = Signal()  # Signal để refresh video preview  
    update_calculations = Signal()  # Signal để update số video/phân cảnh
    show_upload_dialog = Signal()  # Signal để tự động hiển thị upload dialog
    # Frame extraction signals
    extraction_progress_update = Signal(int)  # Progress percentage for frame extraction
    extraction_finished = Signal(bool)  # Success/failure for frame extraction
    show_review_dialog = Signal()  # Signal để hiển thị review dialog trước khi integrate
    rewrite_log_message = Signal(str)  # Signal cho rewrite tab logs
    update_rewrite_subtitle_ui = Signal(str, bool)  # Signal để update subtitle UI: (text, success)
    update_rewrite_rewritten_ui = Signal(str, bool)  # Signal để update rewritten UI: (text, success)
    # Flow image signals
    flow_update_tile_status = Signal(int, str)  # (tile_index, status_text)
    flow_set_tile_image = Signal(int, str)  # (tile_index, image_path)
    flow_update_success_label = Signal(int)  # (success_count)
    flow_update_status_text = Signal(str)  # (status_text)
    flow_update_hint_text = Signal(str)  # (hint_text)
    flow_enable_run_button = Signal(bool)  # (enabled)
    flow_start_next_batch = Signal()  # Signal để start next batch từ worker thread
    flow_worker_done = Signal(bool, object)  # (success, batch_context)
    show_update_available = Signal(object)  # (update_info dict) - hiển thị dialog cập nhật
    show_flow_success_popup = Signal(int)  # (success_count) - hiển thị popup thành công Banana Pro
    show_error_popup = Signal(str, str)  # (title, message) - hiển thị popup lỗi cho người dùng
    flow_update_task_grid_status = Signal(int, str, str)  # (task_index, status, error_msg) - update Task_Grid row
    flow_update_task_grid_preview = Signal(int, str)  # (task_index, image_path) - update preview column


class FrameExtractionWorker(QThread):
    """Worker thread for frame extraction"""
    
    def __init__(self, video_path, output_dir, interval_seconds, output_format, signals):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.interval_seconds = interval_seconds
        self.output_format = output_format
        self.signals = signals
        self.stop_flag = False
    
    def stop(self):
        """Stop the extraction process"""
        self.stop_flag = True
    
    def run(self):
        """Main extraction logic"""
        try:
            import subprocess
            import time
            
            self.signals.new_log.emit(f"🚀 Bắt đầu trích xuất frames từ: {Path(self.video_path).name}")
            self.signals.new_log.emit(f"📁 Thư mục lưu: {self.output_dir}")
            self.signals.new_log.emit(f"⏱️ Khoảng cách: {self.interval_seconds}s/frame")
            
            # Find ffmpeg
            ffmpeg = self.find_ffmpeg()
            if not ffmpeg:
                self.signals.new_log.emit("❌ Không tìm thấy ffmpeg. Vui lòng cài đặt ffmpeg!")
                self.signals.extraction_finished.emit(False)
                return
            
            # Create output directory
            output_path = Path(self.output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Get video info first
            duration = self.get_video_duration(ffmpeg, self.video_path)
            if not duration:
                self.signals.new_log.emit("❌ Không thể lấy thông tin video")
                self.signals.extraction_finished.emit(False)
                return
            
            self.signals.new_log.emit(f"📊 Video duration: {duration:.1f}s")
            
            # Calculate expected frames
            expected_frames = int(duration / self.interval_seconds) + 1
            self.signals.new_log.emit(f"📊 Dự kiến trích xuất: ~{expected_frames} frames")
            
            # Base filename from video
            video_name = Path(self.video_path).stem
            safe_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_') or "video"
            
            # FFmpeg command for frame extraction
            output_pattern = output_path / f"{safe_name}_frame_%04d.{self.output_format}"
            
            # Use fps filter to extract frames at specified intervals
            fps_value = 1.0 / self.interval_seconds
            
            cmd = [
                ffmpeg,
                "-i", str(self.video_path),
                "-vf", f"fps={fps_value}",
                "-y",  # Overwrite existing files
                str(output_pattern)
            ]
            
            self.signals.new_log.emit("🔄 Đang trích xuất frames...")
            self.signals.new_log.emit(f"🔧 FFmpeg command: {' '.join(cmd)}")
            self.signals.extraction_progress_update.emit(10)
            
            # Run ffmpeg with progress monitoring
            success = self.run_ffmpeg_with_progress(cmd, duration, expected_frames)
            
            if success and not self.stop_flag:
                # Count actual extracted frames
                extracted_files = list(output_path.glob(f"{safe_name}_frame_*.{self.output_format}"))
                self.signals.new_log.emit(f"✅ Hoàn thành! Đã trích xuất {len(extracted_files)} frames")
                self.signals.new_log.emit(f"📁 Vị trí: {output_path}")
                self.signals.extraction_progress_update.emit(100)
                self.signals.extraction_finished.emit(True)
            elif self.stop_flag:
                self.signals.new_log.emit("🛑 Đã dừng bởi người dùng")
                self.signals.extraction_finished.emit(False)
            else:
                self.signals.new_log.emit("❌ Trích xuất thất bại")
                self.signals.extraction_finished.emit(False)
                
        except Exception as e:
            self.signals.new_log.emit(f"❌ Lỗi: {e}")
            self.signals.extraction_finished.emit(False)
    
    def find_ffmpeg(self):
        """Find ffmpeg executable"""
        import subprocess
        candidates = [
            "ffmpeg",  # In PATH
            "ffmpeg.exe",  # In PATH (Windows)
            str(Path.cwd() / "ffmpeg.exe"),  # Local directory
        ]
        
        for candidate in candidates:
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                result = subprocess.run(
                    [candidate, "-version"], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE,
                    timeout=5,
                    creationflags=creationflags
                )
                if result.returncode == 0:
                    return candidate
            except Exception:
                continue
        return None
    
    def get_video_duration(self, ffmpeg_path, video_path):
        """Get video duration using ffprobe"""
        try:
            import subprocess
            ffprobe = ffmpeg_path.replace("ffmpeg", "ffprobe")
            
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            result = subprocess.run([
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
            creationflags=creationflags)
            
            if result.returncode == 0 and result.stdout:
                return float(result.stdout.strip())
        except Exception as e:
            self.signals.new_log.emit(f"⚠️ Lỗi lấy duration: {e}")
        return None
    
    def run_ffmpeg_with_progress(self, cmd, duration, expected_frames):
        """Run ffmpeg with progress monitoring"""
        try:
            import subprocess
            import time
            
            # Run ffmpeg
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=creationflags
            )
            
            # Monitor progress
            start_time = time.time()
            last_progress = 10
            
            while True:
                if self.stop_flag:
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except:
                        process.kill()
                    return False
                
                # Check if process is still running
                poll = process.poll()
                if poll is not None:
                    # Process finished
                    break
                
                # Read output to get progress info from ffmpeg
                try:
                    if process.stdout:
                        line = process.stdout.readline()
                        if line:
                            # Parse ffmpeg progress from output
                            if "time=" in line:
                                # Extract time information for better progress
                                try:
                                    time_part = line.split("time=")[1].split()[0]
                                    # Convert time format (HH:MM:SS.ss) to seconds
                                    time_parts = time_part.split(":")
                                    if len(time_parts) >= 3:
                                        hours = float(time_parts[0])
                                        minutes = float(time_parts[1])
                                        seconds = float(time_parts[2])
                                        current_time = hours * 3600 + minutes * 60 + seconds
                                        
                                        if duration > 0:
                                            progress = min(90, int((current_time / duration) * 80) + 10)
                                            if progress > last_progress:
                                                self.signals.extraction_progress_update.emit(progress)
                                                last_progress = progress
                                except Exception:
                                    pass
                except Exception:
                    pass
                
                # Fallback: Update progress based on elapsed time
                elapsed = time.time() - start_time
                if duration > 0:
                    # Conservative time-based progress
                    estimated_process_time = duration * 0.1  # Assume processing takes 10% of video duration
                    time_progress = min(90, int((elapsed / max(estimated_process_time, 10)) * 80) + 10)
                    if time_progress > last_progress:
                        self.signals.extraction_progress_update.emit(time_progress)
                        last_progress = time_progress
                
                time.sleep(0.1)  # Check more frequently
            
            # Get final result
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                self.signals.new_log.emit("✅ FFmpeg execution completed successfully")
                return True
            else:
                self.signals.new_log.emit(f"❌ FFmpeg error (code {process.returncode})")
                if stderr:
                    self.signals.new_log.emit(f"Error details: {stderr}")
                return False

        except Exception as e:
            self.signals.new_log.emit(f"❌ Lỗi run ffmpeg: {e}")
            return False

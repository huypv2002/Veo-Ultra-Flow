#!/usr/bin/env python3
"""
Extend Videos Module - Xử lý kéo dài video với Google Flow

Quy trình:
1. Đọc file txt với nhiều đoạn text (mỗi dòng 1 đoạn)
2. Gom nhóm theo số lượng người dùng chọn (1-17 đoạn/project)
3. Mỗi project:
   - Tạo scene đầu tiên bằng Text-to-Video
   - Upload frame cuối của scene vừa tạo
   - Extend video bằng ExtendVideo API (lặp đến đủ số đoạn)
   - Concat tất cả scenes thành 1 video hoàn chỉnh
4. Xử lý lỗi thông minh: nếu 1 đoạn lỗi → dừng project đó và báo cho user sửa

Tác giả: mavanhuy30
"""

import json
import time
import uuid
import subprocess
import tempfile
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass

import requests
from complete_flow import LabsFlowClient, _parse_cookie_string


# ✅ Danh sách từ nhạy cảm/vi phạm chính sách (có thể mở rộng)
SENSITIVE_WORDS = [
    # Violence
    "kill", "murder", "death", "blood", "weapon", "gun", "knife", "violence", "war", "fight",
    # Adult content
    "nude", "naked", "sex", "porn", "adult", "explicit", "erotic",
    # Hate speech
    "hate", "racist", "discrimination", "offensive",
    # Illegal activities
    "drug", "cocaine", "heroin", "illegal", "crime", "theft", "robbery",
    # Other sensitive topics
    "suicide", "self-harm", "terrorism", "bomb", "explosive"
]

# ✅ Từ nhạy cảm tiếng Việt
SENSITIVE_WORDS_VI = [
    "giết", "chết", "máu", "vũ khí", "súng", "dao", "bạo lực", "chiến tranh", "đánh nhau",
    "khỏa thân", "nude", "sex", "khiêu dâm", "người lớn", "tục tĩu",
    "thù hận", "phân biệt", "xúc phạm",
    "ma túy", "cần sa", "bất hợp pháp", "tội phạm", "ăn cắp", "cướp",
    "tự tử", "tự hại", "khủng bố", "bom", "nổ"
]


def sanitize_prompt(prompt: str, log_callback: Optional[Callable[[str], None]] = None) -> str:
    """Loại bỏ các từ nhạy cảm/vi phạm chính sách khỏi prompt
    
    Args:
        prompt: Prompt text cần sanitize
        log_callback: Callback để log (optional)
        
    Returns:
        Prompt đã được sanitize (đã loại bỏ từ nhạy cảm)
    """
    log = log_callback or (lambda x: None)
    
    try:
        original_prompt = prompt
        sanitized_prompt = prompt
        
        # Tạo pattern để tìm từ nhạy cảm (case-insensitive)
        all_sensitive_words = SENSITIVE_WORDS + SENSITIVE_WORDS_VI
        
        # Split prompt thành các từ
        words = re.findall(r'\b\w+\b', prompt.lower())
        
        # Tìm từ nhạy cảm
        found_sensitive = []
        for word in words:
            if word.lower() in [w.lower() for w in all_sensitive_words]:
                found_sensitive.append(word)
        
        if found_sensitive:
            log(f"⚠️ Phát hiện từ nhạy cảm: {', '.join(set(found_sensitive))}\n")
            
            # Loại bỏ từ nhạy cảm khỏi prompt
            # Tạo pattern để match từ nhạy cảm (word boundary)
            for sensitive_word in all_sensitive_words:
                # Match cả từ đầy đủ (case-insensitive)
                pattern = r'\b' + re.escape(sensitive_word) + r'\b'
                sanitized_prompt = re.sub(pattern, '', sanitized_prompt, flags=re.IGNORECASE)
            
            # Clean up: loại bỏ khoảng trắng thừa
            sanitized_prompt = re.sub(r'\s+', ' ', sanitized_prompt).strip()
            
            # Nếu prompt trở thành rỗng hoặc quá ngắn, giữ lại một phần
            if len(sanitized_prompt.strip()) < 5:
                log(f"⚠️ Prompt sau khi loại bỏ quá ngắn, giữ lại phần an toàn\n")
                # Giữ lại các từ không phải từ nhạy cảm
                safe_words = [w for w in re.findall(r'\b\w+\b', original_prompt) 
                             if w.lower() not in [sw.lower() for sw in all_sensitive_words]]
                sanitized_prompt = ' '.join(safe_words)
            
            log(f"✅ Đã sanitize prompt: '{original_prompt[:50]}...' → '{sanitized_prompt[:50]}...'\n")
        
        return sanitized_prompt.strip()
        
    except Exception as e:
        log(f"⚠️ Lỗi khi sanitize prompt: {e}, giữ nguyên prompt gốc\n")
        return prompt


def _extract_strings_recursive(obj: Any, keys: Tuple[str, ...]) -> List[str]:
    """Recursively extract string values from nested dict/list by keys"""
    results: List[str] = []
    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k in keys and isinstance(v, str):
                    results.append(v)
                results.extend(_extract_strings_recursive(v, keys))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                results.extend(_extract_strings_recursive(item, keys))
    except Exception:
        pass
    return results


def _extract_file_urls(obj: Any) -> List[str]:
    """Extract video/file URLs from API response"""
    candidates = _extract_strings_recursive(obj, (
        "fileUrl", "fifeUrl", "downloadUrl", "mediaUrl", "imageUrl",
        "url", "link", "href", "src", "path", "uri", "videoUrl",
        "thumbnailUrl", "previewUrl", "outputUrl", "resultUrl",
        "file", "media", "video", "image", "download", "content", "outputUri"
    ))
    
    # Filter valid URLs
    urls: List[str] = []
    for u in candidates:
        if isinstance(u, str) and u.startswith("http"):
            lower_u = u.lower()
            # Prioritize URLs with file extensions
            if any(ext in lower_u for ext in [".mp4", ".jpg", ".png", ".gif", ".webp", ".jpeg", ".mov", ".avi", ".webm"]):
                urls.append(u)
            # Or URLs from Google storage/CDN
            elif any(domain in lower_u for domain in ["googleapis.com", "googleusercontent.com", "storage.cloud.google.com", "storage.googleapis.com"]):
                urls.append(u)
            # Or URLs with video/media pattern
            elif any(pattern in lower_u for pattern in ["/video/", "/media/", "/file/", "/download/"]):
                urls.append(u)
    
    return urls


@dataclass
class ExtendSegment:
    """Thông tin 1 đoạn text trong project"""
    index: int  # Thứ tự trong project (1, 2, 3...)
    global_index: int  # Thứ tự global trong file txt
    text: str
    status: str = "pending"  # pending, processing, completed, error
    error_message: str = ""
    media_id: Optional[str] = None  # Media ID sau khi tạo xong
    video_url: Optional[str] = None  # URL của video đã tạo


@dataclass
class ExtendProject:
    """Thông tin 1 project (gom nhóm)"""
    project_id: str
    project_name: str
    segments: List[ExtendSegment]
    status: str = "pending"  # pending, processing, completed, error
    video_urls: List[str] = None  # URLs của các scenes đã tạo
    concat_url: Optional[str] = None  # URL video đã concat
    resume_from_index: int = 1  # Giữ vị trí segment cần chạy tiếp (1-based)
    
    def __post_init__(self):
        if self.video_urls is None:
            self.video_urls = []
        if not isinstance(self.resume_from_index, int) or self.resume_from_index < 1:
            self.resume_from_index = 1


class ExtendVideoProcessor:
    """Xử lý extend video với Google Flow API"""
    
    def __init__(self, client: LabsFlowClient, log_callback: Callable[[str], None] = None, aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE", stop_event: Optional[threading.Event] = None, cookie_index: Optional[int] = None, renew_cookie_callback: Optional[Callable[[str, Dict[str, str]], Optional[Dict[str, str]]]] = None):
        self.client = client
        self.log = log_callback or print
        self.project_id = str(uuid.uuid4())  # Project ID chung cho tất cả scenes
        self.aspect_ratio = aspect_ratio  # Store aspect ratio for video operations
        self.stop_event = stop_event  # ✅ Cho phép dừng ngay khi app đóng
        self.cookie_index = cookie_index  # ✅ Cookie index để track retry
        self.renew_cookie_callback = renew_cookie_callback  # ✅ Callback để renew cookie
        # ✅ Track số lần retry cho cookie này
        self._cookie_retry_count = 0
        self._cookie_restarted = False  # ✅ Track xem cookie đã được restart chưa
        # Map aspect ratio for image operations (portrait video = portrait image)
        if aspect_ratio == "VIDEO_ASPECT_RATIO_PORTRAIT":
            self.image_aspect_ratio = "IMAGE_ASPECT_RATIO_PORTRAIT"
        else:
            self.image_aspect_ratio = "IMAGE_ASPECT_RATIO_LANDSCAPE"
    
    @staticmethod
    def _parse_project_index(project_name: str) -> int:
        """Parse project index từ project name - xử lý cả Project_X và tên tùy ý
        
        Args:
            project_name: Tên project (ví dụ: "Project_1", "prom", "prom2")
            
        Returns:
            Index number (1-based), fallback về 1 nếu không parse được
        """
        try:
            # Thử parse theo format "Project_X" hoặc "name_X"
            parts = project_name.split("_")
            if len(parts) > 1:
                last_part = parts[-1]
                # Kiểm tra nếu last_part là số
                if last_part.isdigit():
                    return int(last_part)
        except Exception:
            pass
        
        # Fallback: dùng hash của tên để tạo index duy nhất (1-999)
        # Hoặc đơn giản return 1
        return 1
    
    def _get_extend_model_key(self) -> str:
        """Lấy model key cho extend video dựa trên aspect ratio"""
        try:
            # Map aspect ratio để kiểm tra
            mapped_aspect = LabsFlowClient._map_video_aspect(self.aspect_ratio)
            
            # Chọn model extend phù hợp
            if mapped_aspect == "VIDEO_ASPECT_RATIO_PORTRAIT":
                return "veo_3_1_extend_fast_portrait_ultra"
            else:
                return "veo_3_1_extend_fast_landscape_ultra"
        except Exception:
            # Fallback về landscape nếu có lỗi
            return "veo_3_1_extend_fast_landscape_ultra"
    
    def create_scene_from_text(self, prompt: str, scene_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Tạo scene đầu tiên bằng Text-to-Video (8 giây)
        
        Returns:
            Dict với keys: operations, media_id, status
        """
        try:
            if self.stop_event and self.stop_event.is_set():
                self.log("⏹️ Stop requested, bỏ qua create_scene_from_text\n")
                return None
            self.log(f"📹 Tạo scene đầu từ text: '{prompt[:50]}...'\n")
            
            scene_id = scene_id or str(uuid.uuid4())
            seed = int(time.time() * 1000) % 100000
            
            url = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoText"
            client_context = {
                "projectId": self.project_id,
                "tool": "PINHOLE",
                "userPaygateTier": "PAYGATE_TIER_TWO"
            }
            
            # ✅ Inject recaptchaToken cho text-to-video generation
            try:
                if hasattr(self.client, '_maybe_inject_recaptcha'):
                    self.client._maybe_inject_recaptcha(client_context)
            except Exception as e:
                self.log(f"  ⚠️ Lỗi inject recaptchaToken: {e}\n")
            
            payload = {
                "clientContext": client_context,
                "requests": [{
                    "aspectRatio": self.aspect_ratio,
                    "seed": seed,
                    "textInput": {"prompt": prompt},
                    "videoModelKey": self.client._get_effective_model("veo_3_1_t2v_fast_ultra", self.aspect_ratio),
                    "metadata": {"sceneId": scene_id}
                }]
            }
            
            # ✅ Sanitize prompt trước khi gửi
            sanitized_prompt = sanitize_prompt(prompt, self.log)
            if sanitized_prompt != prompt:
                self.log(f"  🔒 Prompt đã được sanitize để loại bỏ từ nhạy cảm\n")
                prompt = sanitized_prompt
                # Update payload với prompt đã sanitize
                payload["requests"][0]["textInput"]["prompt"] = prompt
            
            # Retry cho HIGH_TRAFFIC (3 lần) và lỗi khác (5 lần)
            max_retries_429 = 3  # Retry cho 429/HIGH_TRAFFIC
            max_retries_other = 5  # ✅ Tăng từ 3 lên 5 cho lỗi khác
            retry_count_429 = 0
            retry_count_other = 0
            
            for attempt in range(max(max_retries_429, max_retries_other)):
                if self.stop_event and self.stop_event.is_set():
                    self.log("⏹️ Stop requested, dừng create_scene_from_text\n")
                    return None
                try:
                    resp = self.client.session.post(
                        url,
                        headers=self.client._aisandbox_headers(),
                        json=payload,
                        timeout=120
                    )
                    
                    # Check HIGH_TRAFFIC error
                    is_429_error = False
                    if resp.status_code == 500:
                        error_data = resp.json()
                        error_msg = json.dumps(error_data)
                        if "PUBLIC_ERROR_HIGH_TRAFFIC" in error_msg or "HIGH_TRAFFIC" in error_msg:
                            is_429_error = True
                            retry_count_429 += 1
                            if retry_count_429 < max_retries_429:
                                wait_time = retry_count_429 * 5
                                self.log(f"  ⚠️ VEO 3 quá tải (429), chờ {wait_time}s và thử lại ({retry_count_429}/{max_retries_429})...\n")
                                time.sleep(wait_time)
                                continue
                            else:
                                self.log(f"  ❌ VEO 3 quá tải sau {max_retries_429} lần thử\n")
                                return None
                    
                    resp.raise_for_status()
                    result = resp.json()
                    
                    operations = result.get("operations", [])
                    if operations:
                        op_name = operations[0].get("operation", {}).get("name", "")
                        self.log(f"  ✅ Scene đầu đã bắt đầu: {op_name}\n")
                        return {
                            "operations": [{
                                "operation": {"name": op_name},
                                "sceneId": scene_id,
                                "status": "MEDIA_GENERATION_STATUS_PENDING"
                            }],
                            "media_id": None,  # Sẽ lấy sau khi poll xong
                            "status": "pending"
                        }
                    return None
                    
                except Exception as e:
                    if self.stop_event and self.stop_event.is_set():
                        self.log("⏹️ Stop requested, dừng create_scene_from_text\n")
                        return None
                    # ✅ Phân biệt lỗi 429 và lỗi khác
                    error_str = str(e).lower()
                    is_429 = "429" in error_str or "high_traffic" in error_str or "too many" in error_str
                    
                    if is_429:
                        retry_count_429 += 1
                        if retry_count_429 < max_retries_429:
                            wait_time = retry_count_429 * 5
                            self.log(f"  ⚠️ Lỗi 429 (attempt {retry_count_429}/{max_retries_429}): {str(e)[:100]}, retry sau {wait_time}s...\n")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.log(f"  ❌ Lỗi 429 sau {max_retries_429} lần thử: {e}\n")
                            return None
                    else:
                        # ✅ Lỗi khác: retry 5 lần
                        retry_count_other += 1
                        self._cookie_retry_count += 1
                        
                        # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                        if self._cookie_retry_count == 6 and not self._cookie_restarted and self.cookie_index is not None and self.renew_cookie_callback:
                            self.log(f"  🔄 Cookie {self.cookie_index+1} đã retry 6 lần (create scene) → restart BrowserContext (renew cookie)\n")
                            
                            # Gọi renew cookie và restart context
                            try:
                                cookie_hash = self.client._cookie_hash if hasattr(self.client, '_cookie_hash') else None
                                
                                if cookie_hash:
                                    # ✅ Gọi _renew_cookie_and_restart_context từ LabsFlowClient
                                    new_cookies = LabsFlowClient._renew_cookie_and_restart_context(
                                        browser=LabsFlowClient._recaptcha_worker_browser if hasattr(LabsFlowClient, '_recaptcha_worker_browser') else None,
                                        cookie_hash=cookie_hash,
                                        old_cookies=self.client.cookies if hasattr(self.client, 'cookies') else {},
                                        proxy_config=getattr(self.client, 'proxy_config', None),
                                        user_agent=getattr(self.client, 'user_agent', ''),
                                        get_new_cookies_callback=self.renew_cookie_callback,
                                    )
                                    
                                    if new_cookies:
                                        self.client.cookies = new_cookies
                                        if self.client.fetch_access_token():
                                            self._cookie_restarted = True
                                            self._cookie_retry_count = 0
                                            self.log(f"  ✅ Cookie {self.cookie_index+1} đã được renew và restart thành công\n")
                                        else:
                                            self.log(f"  ⚠️ Cookie {self.cookie_index+1} renew thành công nhưng fetch token fail\n")
                                    else:
                                        self.log(f"  ⚠️ Không thể renew cookie {self.cookie_index+1}\n")
                            except Exception as renew_err:
                                self.log(f"  ⚠️ Lỗi khi renew cookie {self.cookie_index+1}: {renew_err}\n")
                            
                            # Tiếp tục retry với cookie (có thể đã được renew)
                            continue
                        
                        # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → raise exception để đánh dấu cookie die
                        if self._cookie_retry_count >= 7 and self._cookie_restarted:
                            self.log(f"  💀 Cookie {self.cookie_index+1} đã restart nhưng vẫn lỗi create scene sau lần thứ 7 → đánh dấu die\n")
                            # Raise exception để extend_worker có thể xử lý và switch cookie
                            raise Exception(f"Cookie {self.cookie_index+1} die sau 7 lần retry (create scene)")
                        
                        if retry_count_other < max_retries_other:
                            wait_time = retry_count_other * 5
                            self.log(f"  ⚠️ Lỗi khác (attempt {retry_count_other}/{max_retries_other}, cookie retry: {self._cookie_retry_count}): {str(e)[:100]}, retry sau {wait_time}s...\n")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.log(f"  ❌ Lỗi tạo scene sau {max_retries_other} lần thử: {e}\n")
                            return None
            
            return None
            
        except Exception as e:
            self.log(f"❌ Lỗi tạo scene từ text: {e}\n")
            return None
    
    def download_last_frame(self, video_url: str) -> Optional[bytes]:
        """Download frame cuối của video từ URL
        
        Args:
            video_url: URL của video cần extract frame
            
        Returns:
            Raw bytes của frame cuối (JPEG)
        """
        try:
            import subprocess
            import tempfile
            import os
            
            self.log(f"🖼️ Download frame cuối từ video URL...\n")
            
            # Create temp file for frame
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                temp_path = tmp.name
            
            try:
                # Use ffmpeg to extract last frame
                # -sseof -1: seek to 1 second before end
                cmd = [
                    'ffmpeg',
                    '-sseof', '-1',
                    '-i', video_url,
                    '-frames:v', '1',
                    '-q:v', '2',
                    '-y',
                    temp_path
                ]
                
                subprocess.run(cmd, check=True, capture_output=True)
                
                # Read frame bytes
                with open(temp_path, 'rb') as f:
                    frame_bytes = f.read()
                
                self.log(f"  ✅ Downloaded frame: {len(frame_bytes)} bytes\n")
                return frame_bytes
                
            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            
        except Exception as e:
            self.log(f"❌ Lỗi download frame: {e}\n")
            return None
    
    def upload_frame_for_extend(self, frame_bytes: bytes) -> Optional[str]:
        """Upload frame để dùng cho extend video
        
        Args:
            frame_bytes: Raw bytes của frame (JPEG)
            
        Returns:
            Media ID của frame đã upload
        """
        try:
            import base64
            
            self.log(f"📤 Upload frame cho extend ({len(frame_bytes)} bytes)...\n")
            
            # Convert to base64
            frame_b64 = base64.b64encode(frame_bytes).decode('utf-8')
            
            url = "https://aisandbox-pa.googleapis.com/v1:uploadUserImage"
            payload = {
                "imageInput": {
                    "aspectRatio": self.image_aspect_ratio,
                    "isUserUploaded": False,
                    "mimeType": "image/jpeg",
                    "rawImageBytes": frame_b64
                },
                "clientContext": {
                    "sessionId": f";{int(time.time() * 1000)}",
                    "tool": "PINHOLE"
                }
            }
            
            resp = self.client.session.post(
                url,
                headers=self.client._aisandbox_headers(),
                json=payload,
                timeout=60
            )
            
            resp.raise_for_status()
            result = resp.json()
            
            # Extract media ID from response
            media_id = result.get("mediaId")
            if media_id:
                self.log(f"  ✅ Frame uploaded: {media_id}\n")
                return media_id
            else:
                self.log(f"  ⚠️ No mediaId in response: {result}\n")
                return None
            
        except Exception as e:
            self.log(f"❌ Lỗi upload frame: {e}\n")
            return None
    
    def extend_scene(self, base_media_id: str, prompt: str, scene_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Extend video từ frame cuối (8 giây thêm)
        
        Args:
            base_media_id: Media ID của video gốc
            prompt: Prompt cho đoạn extend
            scene_id: Scene ID (optional)
            
        Returns:
            Dict với keys: operations, media_id, status
        """
        try:
            if self.stop_event and self.stop_event.is_set():
                self.log("⏹️ Stop requested, bỏ qua extend_scene\n")
                return None
            self.log(f"➕ Extend scene với prompt: '{prompt[:50]}...'\n")
            
            scene_id = scene_id or str(uuid.uuid4())
            seed = int(time.time() * 1000) % 100000
            
            url = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoExtendVideo"
            client_context = {
                "projectId": self.project_id,
                "tool": "PINHOLE",
                "userPaygateTier": "PAYGATE_TIER_TWO"
            }
            
            # ✅ Inject recaptchaToken cho extend video generation
            try:
                if hasattr(self.client, '_maybe_inject_recaptcha'):
                    self.client._maybe_inject_recaptcha(client_context)
            except Exception as e:
                self.log(f"  ⚠️ Lỗi inject recaptchaToken: {e}\n")
            
            payload = {
                "clientContext": client_context,
                "requests": [{
                    "textInput": {"prompt": prompt},
                    "videoInput": {
                        "mediaId": base_media_id,
                        "startFrameIndex": 168,  # Frame cuối của video 8s
                        "endFrameIndex": 191
                    },
                    "videoModelKey": self._get_extend_model_key(),
                    "aspectRatio": self.aspect_ratio,
                    "seed": seed,
                    "metadata": {"sceneId": scene_id}
                }]
            }
            
            # ✅ Sanitize prompt trước khi gửi
            sanitized_prompt = sanitize_prompt(prompt, self.log)
            if sanitized_prompt != prompt:
                self.log(f"  🔒 Prompt đã được sanitize để loại bỏ từ nhạy cảm\n")
                prompt = sanitized_prompt
                # Update payload với prompt đã sanitize
                payload["requests"][0]["textInput"]["prompt"] = prompt
            
            # Retry cho HIGH_TRAFFIC (3 lần) và lỗi khác (5 lần)
            max_retries_429 = 3  # Retry cho 429/HIGH_TRAFFIC
            max_retries_other = 5  # ✅ Tăng từ 3 lên 5 cho lỗi khác
            retry_count_429 = 0
            retry_count_other = 0
            
            for attempt in range(max(max_retries_429, max_retries_other)):
                if self.stop_event and self.stop_event.is_set():
                    self.log("⏹️ Stop requested, dừng extend_scene\n")
                    return None
                try:
                    resp = self.client.session.post(
                        url,
                        headers=self.client._aisandbox_headers(),
                        json=payload,
                        timeout=120
                    )
                    
                    # Check HIGH_TRAFFIC error
                    is_429_error = False
                    if resp.status_code == 500:
                        error_data = resp.json()
                        error_msg = json.dumps(error_data)
                        if "PUBLIC_ERROR_HIGH_TRAFFIC" in error_msg or "HIGH_TRAFFIC" in error_msg:
                            is_429_error = True
                            retry_count_429 += 1
                            if retry_count_429 < max_retries_429:
                                wait_time = retry_count_429 * 5
                                self.log(f"  ⚠️ VEO 3 quá tải (extend, 429), chờ {wait_time}s và thử lại ({retry_count_429}/{max_retries_429})...\n")
                                time.sleep(wait_time)
                                continue
                            else:
                                self.log(f"  ❌ VEO 3 quá tải (extend) sau {max_retries_429} lần thử\n")
                                return None
                    
                    resp.raise_for_status()
                    result = resp.json()
                    
                    operations = result.get("operations", [])
                    if operations:
                        op_name = operations[0].get("operation", {}).get("name", "")
                        self.log(f"  ✅ Extend operation đã bắt đầu: {op_name}\n")
                        return {
                            "operations": [{
                                "operation": {"name": op_name},
                                "sceneId": scene_id,
                                "status": "MEDIA_GENERATION_STATUS_PENDING"
                            }],
                            "media_id": None,
                            "status": "pending"
                        }
                    return None
                    
                except Exception as e:
                    if self.stop_event and self.stop_event.is_set():
                        self.log("⏹️ Stop requested, dừng extend_scene\n")
                        return None
                    # ✅ Phân biệt lỗi 429 và lỗi khác
                    error_str = str(e).lower()
                    is_429 = "429" in error_str or "high_traffic" in error_str or "too many" in error_str
                    
                    if is_429:
                        retry_count_429 += 1
                        if retry_count_429 < max_retries_429:
                            wait_time = retry_count_429 * 5
                            self.log(f"  ⚠️ Lỗi 429 extend (attempt {retry_count_429}/{max_retries_429}): {str(e)[:100]}, retry sau {wait_time}s...\n")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.log(f"  ❌ Lỗi 429 extend sau {max_retries_429} lần thử: {e}\n")
                            return None
                    else:
                        # ✅ Lỗi khác: retry 5 lần
                        retry_count_other += 1
                        if retry_count_other < max_retries_other:
                            wait_time = retry_count_other * 5
                            self.log(f"  ⚠️ Lỗi extend khác (attempt {retry_count_other}/{max_retries_other}): {str(e)[:100]}, retry sau {wait_time}s...\n")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.log(f"  ❌ Lỗi extend sau {max_retries_other} lần thử: {e}\n")
                            return None
            
            return None
            
        except Exception as e:
            self.log(f"❌ Lỗi extend scene: {e}\n")
            return None
    
    def poll_operation(self, operations: List[Dict], max_wait: int = 300) -> Optional[Dict[str, Any]]:
        """Poll operation cho đến khi hoàn thành
        
        Returns:
            Dict với status cuối cùng, bao gồm media_id và video_url nếu thành công
        """
        try:
            deadline = time.time() + max_wait
            last_status = None
            
            while time.time() < deadline:
                status = self.client.check_video_status(operations)
                if status:
                    last_status = status
                    
                    # Check completion
                    if isinstance(status, dict) and "operations" in status:
                        ops = status["operations"]
                        for op in ops:
                            op_status = str(op.get("status", "")).upper()
                            if "COMPLETE" in op_status or "SUCCESS" in op_status:
                                # Extract media ID and video URL
                                media_id = self._extract_media_id(op)
                                video_url = self._extract_video_url(op)
                                self.log(f"  ✅ Operation hoàn thành, media_id: {media_id}\n")
                                if video_url:
                                    self.log(f"  📹 Video URL: {video_url}\n")
                                else:
                                    self.log(f"  ⚠️ Không tìm thấy video URL trong response\n")
                                    # Try to get URL using media_id if available
                                    if media_id:
                                        self.log(f"  💡 Thử lấy URL từ client.download_video()...\n")
                                return {
                                    "status": "completed",
                                    "media_id": media_id,
                                    "video_url": video_url,
                                    "data": status
                                }
                            elif "FAIL" in op_status or "ERROR" in op_status:
                                error_msg = self._extract_error_message(op)
                                self.log(f"  ❌ Operation thất bại: {error_msg}\n")
                                is_high_traffic = False
                                try:
                                    if error_msg and isinstance(error_msg, str):
                                        lower_err = error_msg.lower()
                                        is_high_traffic = ("high_traffic" in lower_err) or ("public_error_high_traffic" in lower_err) or ("429" in lower_err)
                                except Exception:
                                    pass
                                return {
                                    "status": "high_traffic" if is_high_traffic else "error",
                                    "error": error_msg,
                                    "data": status
                                }
                
                time.sleep(10)  # Poll mỗi 10s
            
            self.log(f"  ⏰ Timeout sau {max_wait}s\n")
            return {"status": "timeout", "data": last_status}
            
        except Exception as e:
            self.log(f"❌ Lỗi poll operation: {e}\n")
            return {"status": "error", "error": str(e)}
    
    def concat_scenes(self, media_ids: List[str]) -> Optional[Dict[str, Any]]:
        """Concat nhiều scenes thành 1 video
        
        Args:
            media_ids: Danh sách media IDs cần concat
            
        Returns:
            Dict với operation name để poll concat status
        """
        try:
            self.log(f"🔗 Concat {len(media_ids)} scenes...\n")
            
            url = "https://labs.google/fx/api/trpc/videoFx.runConcatenateVideos"
            
            # Build input videos
            # Note: lengthNanos is in milliseconds (8000 = 8 seconds), not nanoseconds!
            input_videos = []
            for i, media_id in enumerate(media_ids):
                input_videos.append({
                    "mediaGenerationId": media_id,
                    "lengthNanos": 8000,  # 8000 milliseconds = 8 seconds
                    "startTimeOffset": "0.000000000s" if i == 0 else "1.000000000s",
                    "endTimeOffset": "8.000000000s"
                })
            
            payload = {
                "json": {
                    "requestInput": {
                        "inputVideos": input_videos
                    }
                }
            }
            
            self.log(f"📤 Gửi concat request với {len(input_videos)} videos...\n")
            self.log(f"📋 Payload: {json.dumps(payload, indent=2)}\n")
            
            # Use _labs_headers() from client for proper headers
            headers = self.client._labs_headers()
            
            # Use cookies from client session
            resp = self.client.session.post(
                url,
                headers=headers,
                cookies=self.client.cookies,
                json=payload,
                timeout=60
            )
            
            self.log(f"📥 Concat response status: {resp.status_code}\n")
            if resp.status_code != 200:
                self.log(f"❌ Concat failed: {resp.text}\n")
                
                # Special handling for 401 Unauthorized
                if resp.status_code == 401:
                    self.log(f"⚠️ Concat API unauthorized - cookies/session may be expired\n")
                    self.log(f"💡 Falling back to individual scene download\n")
                    # Return special status to trigger fallback
                    return {"operation_name": None, "status": "unauthorized"}
                
                return None
                
            result = resp.json()
            self.log(f"📋 Concat response: {json.dumps(result, indent=2)}\n")
            
            # Extract operation name
            # Response structure: result.data.json.result.operation.operation.name
            operation_name = None
            if isinstance(result, dict):
                try:
                    # Path 1: result.data.json.result.operation.operation.name
                    json_data = result.get("result", {}).get("data", {}).get("json", {})
                    if json_data:
                        op_result = json_data.get("result", {})
                        op_container = op_result.get("operation", {})
                        inner_op = op_container.get("operation", {})
                        operation_name = inner_op.get("name")
                        self.log(f"  🔍 Parsed operation name from path 1: {operation_name}\n")
                    
                    # Fallback: search in result directly
                    if not operation_name:
                        op = result.get("result", {}).get("data", {}).get("operation", {})
                    if isinstance(op, dict):
                        inner_op = op.get("operation", {})
                        operation_name = inner_op.get("name") or op.get("name")
                
                        # Another fallback: regex search
                        if not operation_name and "operation" in str(result):
                            import re
                            match = re.search(r'"name":\s*"([^"]+)"', str(result))
                            if match:
                                operation_name = match.group(1)
                                self.log(f"  🔍 Parsed operation name from regex: {operation_name}\n")
                except Exception as e:
                    self.log(f"  ⚠️ Error parsing operation name: {e}\n")
            
            if operation_name:
                self.log(f"  ✅ Concat operation started: {operation_name}\n")
                return {"operation_name": operation_name, "status": "pending"}
            else:
                self.log(f"  ⚠️ Concat submitted nhưng không có operation name\n")
                self.log(f"  📋 Full result: {result}\n")
                return {"operation_name": "", "status": "unknown"}
                
        except Exception as e:
            self.log(f"❌ Lỗi concat scenes: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            
            # Return special status for connection errors to trigger fallback
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ['connection', 'unauthorized', 'timeout', 'disconnected']):
                self.log(f"⚠️ Concat API không khả dụng, sẽ fallback sang download local\n")
                return {"operation_name": None, "status": "connection_error"}
            
            return None
    
    def _concat_large_project(self, media_ids: List[str], project: ExtendProject, 
                              output_dir: Path = None, txt_filename: str = None) -> Optional[Dict[str, Any]]:
        """Concat project lớn (> 20 segments): chia thành batch 20, mỗi batch dùng API concat Google, sau đó dùng FFmpeg nối lại
        
        Args:
            media_ids: Danh sách media IDs cần concat
            project: Project đang xử lý
            output_dir: Thư mục output
            txt_filename: Tên file txt gốc
            
        Returns:
            Dict với type="url" và data là đường dẫn video đã merge, hoặc None nếu thất bại
        """
        try:
            BATCH_SIZE = 20  # Google API concat tối đa 20 segments
            self.log(f"📦 Chia {len(media_ids)} segments thành batch {BATCH_SIZE}...\n")
            
            # Determine output path
            if output_dir and isinstance(output_dir, (str, Path)):
                base_output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
            else:
                base_output_dir = Path("downloaded_videos") / "extend_merged"
            
            base_output_dir.mkdir(parents=True, exist_ok=True)
            
            # Tạo thư mục con theo tên file txt
            if txt_filename:
                txt_name = Path(txt_filename).stem
                final_output_dir = base_output_dir / txt_name
                final_output_dir.mkdir(parents=True, exist_ok=True)
            else:
                final_output_dir = base_output_dir
            
            # Tạo thư mục temp cho các video đã concat
            temp_dir = final_output_dir / "temp_concat" / project.project_name
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Chia thành các batch và concat từng batch
            concat_video_paths = []
            num_batches = (len(media_ids) + BATCH_SIZE - 1) // BATCH_SIZE
            
            for batch_idx in range(num_batches):
                start_idx = batch_idx * BATCH_SIZE
                end_idx = min(start_idx + BATCH_SIZE, len(media_ids))
                batch_media_ids = media_ids[start_idx:end_idx]
                
                self.log(f"📦 Batch {batch_idx + 1}/{num_batches}: Concat {len(batch_media_ids)} segments (từ {start_idx + 1} đến {end_idx})...\n")
                
                # Concat batch này bằng Google API
                batch_concat_result = self.concat_scenes(batch_media_ids)
                
                if not batch_concat_result or batch_concat_result.get("status") in ("unauthorized", "connection_error"):
                    self.log(f"❌ Batch {batch_idx + 1} concat thất bại, chuyển sang download từng scene\n")
                    # Fallback: download từng scene trong batch này
                    batch_video_paths = self._download_batch_scenes(batch_media_ids, project, temp_dir, batch_idx)
                    if batch_video_paths:
                        # Merge batch này bằng FFmpeg
                        batch_output = temp_dir / f"batch_{batch_idx + 1:03d}.mp4"
                        if merge_videos_with_ffmpeg_reencode(batch_video_paths, batch_output, 
                                                             use_overlap=True, log_callback=self.log):
                            concat_video_paths.append(batch_output)
                        else:
                            self.log(f"❌ Merge batch {batch_idx + 1} bằng FFmpeg thất bại\n")
                            return None
                    else:
                        self.log(f"❌ Không thể download scenes của batch {batch_idx + 1}\n")
                        return None
                else:
                    # Poll concat status
                    operation_name = batch_concat_result.get("operation_name")
                    if operation_name:
                        self.log(f"⏳ Polling concat operation cho batch {batch_idx + 1}: {operation_name}\n")
                        batch_concat_result = self.poll_concat_status(operation_name)
                        
                        if batch_concat_result:
                            # Download video đã concat
                            batch_output = temp_dir / f"batch_{batch_idx + 1:03d}.mp4"
                            
                            if isinstance(batch_concat_result, dict):
                                result_type = batch_concat_result.get("type")
                                
                                if result_type == "encoded":
                                    encoded_data = batch_concat_result.get("data")
                                    if decode_and_save_video(encoded_data, batch_output, self.log):
                                        concat_video_paths.append(batch_output)
                                        self.log(f"✅ Batch {batch_idx + 1} đã concat và lưu: {batch_output}\n")
                                    else:
                                        self.log(f"❌ Không thể decode batch {batch_idx + 1}\n")
                                        return None
                                
                                elif result_type == "url":
                                    video_url = batch_concat_result.get("data")
                                    if download_video(video_url, batch_output, self.log):
                                        concat_video_paths.append(batch_output)
                                        self.log(f"✅ Batch {batch_idx + 1} đã concat và download: {batch_output}\n")
                                    else:
                                        self.log(f"❌ Không thể download batch {batch_idx + 1}\n")
                                        return None
                                else:
                                    self.log(f"❌ Batch {batch_idx + 1} có result type không hợp lệ: {result_type}\n")
                                    return None
                            elif isinstance(batch_concat_result, str):
                                if download_video(batch_concat_result, batch_output, self.log):
                                    concat_video_paths.append(batch_output)
                                    self.log(f"✅ Batch {batch_idx + 1} đã concat và download: {batch_output}\n")
                                else:
                                    self.log(f"❌ Không thể download batch {batch_idx + 1}\n")
                                    return None
                            else:
                                self.log(f"❌ Batch {batch_idx + 1} không có URL hợp lệ\n")
                                return None
                        else:
                            self.log(f"❌ Poll concat batch {batch_idx + 1} thất bại\n")
                            return None
                    else:
                        self.log(f"❌ Batch {batch_idx + 1} không có operation name\n")
                        return None
            
            # ✅ Nối các video đã concat lại
            if len(concat_video_paths) > 1:
                self.log(f"\n🔗 Nối {len(concat_video_paths)} video đã concat bằng FFmpeg...\n")
                
                project_index = self._parse_project_index(project.project_name)
                if project_index > 1:
                    output_filename = f"scene_builder_{project_index}.mp4"
                else:
                    output_filename = "scene_builder.mp4"
                final_output_path = final_output_dir / output_filename
                
                merged_ok = merge_videos_with_ffmpeg_dissolve(concat_video_paths, final_output_path, 
                                                              duration=3.0, offset=3.0, log_callback=self.log)
                if not merged_ok:
                    self.log("💡 Fallback: merge copy-mode (không transition)")
                    merged_ok = merge_videos_with_ffmpeg(concat_video_paths, final_output_path, 
                                                         use_overlap=False, log_callback=self.log)
                if merged_ok:
                    self.log(f"✅ Đã nối tất cả video: {final_output_path}\n")
                    
                    # Cleanup temp files
                    try:
                        for path in concat_video_paths:
                            if path.exists():
                                path.unlink()
                        temp_dir.rmdir()
                    except Exception as e:
                        self.log(f"  ⚠️ Cleanup warning: {e}\n")
                    
                    return {"type": "url", "data": str(final_output_path)}
                else:
                    self.log(f"❌ Merge thất bại\n")
                    return None
            elif len(concat_video_paths) == 1:
                # Chỉ có 1 batch (≤ 20 segments), không cần merge thêm
                project_index = self._parse_project_index(project.project_name)
                if project_index > 1:
                    output_filename = f"scene_builder_{project_index}.mp4"
                else:
                    output_filename = "scene_builder.mp4"
                final_output_path = final_output_dir / output_filename
                
                # Move file từ temp sang final
                try:
                    concat_video_paths[0].rename(final_output_path)
                    self.log(f"✅ Đã lưu video: {final_output_path}\n")
                    
                    # Cleanup
                    try:
                        temp_dir.rmdir()
                    except Exception:
                        pass
                    
                    return {"type": "url", "data": str(final_output_path)}
                except Exception as e:
                    self.log(f"❌ Lỗi move file: {e}\n")
                    return None
            else:
                self.log(f"❌ Không có video nào để merge\n")
                return None
                
        except Exception as e:
            self.log(f"❌ Lỗi _concat_large_project: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            return None
    
    def _download_batch_scenes(self, media_ids: List[str], project: ExtendProject, 
                               temp_dir: Path, batch_idx: int) -> List[Path]:
        """Download các scenes trong batch và trả về danh sách đường dẫn"""
        try:
            video_paths = []
            for i, media_id in enumerate(media_ids):
                # Tìm segment tương ứng với media_id này
                segment = None
                for seg in project.segments:
                    if seg.media_id == media_id:
                        segment = seg
                        break
                
                if segment and segment.video_url:
                    video_path = temp_dir / f"batch_{batch_idx + 1:03d}_scene_{i + 1:03d}.mp4"
                    if download_video(segment.video_url, video_path, self.log):
                        video_paths.append(video_path)
                    else:
                        self.log(f"  ❌ Không thể download scene {i + 1} của batch {batch_idx + 1}\n")
                else:
                    # Thử fetch URL từ media_id
                    video_url = self._fetch_video_url_from_media_id(media_id)
                    if video_url:
                        video_path = temp_dir / f"batch_{batch_idx + 1:03d}_scene_{i + 1:03d}.mp4"
                        if download_video(video_url, video_path, self.log):
                            video_paths.append(video_path)
                        else:
                            self.log(f"  ❌ Không thể download scene {i + 1} của batch {batch_idx + 1}\n")
                    else:
                        self.log(f"  ❌ Không tìm thấy URL cho media_id {media_id[:20]}...\n")
            
            return video_paths
        except Exception as e:
            self.log(f"❌ Lỗi _download_batch_scenes: {e}\n")
            return []
    
    def poll_concat_status(self, operation_name: str, max_wait: int = 600) -> Optional[str]:
        """Poll concat operation và trả về video data (encodedVideo hoặc URL)
        
        Args:
            operation_name: Operation name từ concat API
            max_wait: Thời gian chờ tối đa (mặc định 600s = 10 phút)
        
        Returns:
            Dict với encodedVideo (base64) hoặc outputUri, hoặc None nếu lỗi/timeout
        """
        try:
            self.log(f"⏳ Poll concat status cho operation: {operation_name}\n")
            
            url = "https://aisandbox-pa.googleapis.com/v1:runVideoFxCheckConcatenationStatus"
            payload = {
                "operation": {
                    "operation": {
                        "name": operation_name
                    }
                }
            }
            
            deadline = time.time() + max_wait
            poll_count = 0
            last_status = None
            logged_successful = False  # Track if we've logged SUCCESSFUL response
            
            while time.time() < deadline:
                poll_count += 1
                
                resp = self.client.session.post(
                    url,
                    headers=self.client._aisandbox_headers(),
                    json=payload,
                    timeout=30
                )
                
                if resp.status_code == 200:
                    result = resp.json()
                    
                    # Extract status and outputUri
                    status = str(result.get("status", "")).upper()
                    
                    # Try to extract video URLs from entire response
                    video_urls = _extract_file_urls(result)
                    output_uri = video_urls[0] if video_urls else ""
                    
                    # Only log when status changes
                    if status != last_status:
                        self.log(f"  🔄 Poll #{poll_count}: Status = '{status}' (len={len(status)})\n")
                        last_status = status
                        
                        # Log full response when status first changes to SUCCESSFUL
                        if "SUCCESSFUL" in status:
                            self.log(f"  📋 Full SUCCESSFUL response (poll #{poll_count}):\n")
                            self.log(f"{json.dumps(result, indent=2)[:1000]}...\n")
                            logged_successful = True
                    elif poll_count % 10 == 0:
                        # Log every 10 polls to show progress
                        elapsed = int(time.time() - (deadline - max_wait))
                        self.log(f"  ⏱️ Poll #{poll_count} ({elapsed}s elapsed): Still '{status}'...\n")
                    
                    # Check for encodedVideo (base64 video data from Google)
                    encoded_video = result.get("encodedVideo", "")
                    if encoded_video:
                        self.log(f"  ✅ Concat hoàn thành với encodedVideo (poll #{poll_count}): {len(encoded_video)} chars\n")
                        return {"type": "encoded", "data": encoded_video}
                    
                    # Check for completion with outputUri
                    if output_uri:
                        self.log(f"  ✅ Concat hoàn thành với outputUri (poll #{poll_count}): {output_uri}\n")
                        return {"type": "url", "data": output_uri}
                    
                    # Check for failure
                    if "FAILED" in status or "ERROR" in status:
                        self.log(f"  ❌ Concat thất bại: {status}\n")
                        self.log(f"  📋 Full response: {json.dumps(result, indent=2)}\n")
                        return None
                    
                    # Status is DONE/COMPLETED/SUCCESSFUL - check if we have URL
                    if "DONE" in status or "COMPLETED" in status or "SUCCESSFUL" in status:
                        if output_uri:
                            # Already extracted above via _extract_file_urls
                            self.log(f"  ✅ Found video URL: {output_uri[:100]}...\n")
                            return output_uri
                        
                        # Try to extract mediaGenerationId and fetch URL
                        media_id = (result.get("mediaGenerationId") or
                                   result.get("operation", {}).get("metadata", {}).get("video", {}).get("mediaGenerationId"))
                        
                        if media_id:
                            self.log(f"  🔍 Found mediaGenerationId: {media_id}, trying to get video URL...\n")
                            video_url = self._fetch_video_url_from_media_id(media_id)
                            if video_url:
                                return video_url
                        
                        self.log(f"  ⚠️ Status={status} but no outputUri/mediaId found (poll #{poll_count})\n")
                else:
                    self.log(f"  ⚠️ Poll #{poll_count} failed with status {resp.status_code}: {resp.text[:200]}\n")
                
                time.sleep(8)  # Poll mỗi 8s (concat mất nhiều thời gian hơn)
            
            self.log(f"  ⏰ Concat timeout sau {max_wait}s (polled {poll_count} times, last status: {last_status})\n")
            return None
            
        except Exception as e:
            self.log(f"❌ Lỗi poll concat: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            return None
    
    def _get_signed_url_from_media_id(self, media_id: str) -> Optional[str]:
        """Lấy signed URL trực tiếp từ media ID
        
        Thử gọi API để lấy signed download URL thay vì blob URL
        """
        try:
            # Option 1: Try to get video info directly
            # Some APIs might have endpoint like /v1/media/{mediaId}/download
            self.log(f"  🔗 Trying to get signed URL for media_id...\n")
            
            # Try constructing GCS path and getting signed URL
            # Format: gs://aisandbox-media/{project_id}/{media_id}/video.mp4
            # But we need the actual HTTP(S) URL
            
            # This might need to call a specific API endpoint
            # For now, return None and rely on searchProjectScenes
            return None
            
        except Exception as e:
            self.log(f"  ❌ Error getting signed URL: {e}\n")
            return None
    
    def _fetch_video_url_from_media_id(self, media_id: str) -> Optional[str]:
        """Lấy video URL từ media generation ID bằng searchProjectScenes API
        
        Args:
            media_id: Media generation ID của video
            
        Returns:
            Video URL nếu tìm thấy
        """
        try:
            self.log(f"  📡 Fetching video URL for media_id via searchProjectScenes...\n")
            
            # Build search query
            import urllib.parse
            query_params = {
                "json": {
                    "projectId": self.project_id,
                    "toolName": "PINHOLE",
                    "pageSize": 50  # Get more scenes to find our media_id
                }
            }
            
            url = f"https://labs.google/fx/api/trpc/project.searchProjectScenes?input={urllib.parse.quote(json.dumps(query_params))}"
            
            headers = self.client._labs_headers()
            resp = self.client.session.get(
                url,
                headers=headers,
                cookies=self.client.cookies,
                timeout=30
            )
            
            if resp.status_code == 200:
                result = resp.json()
                # Parse response to find media_id
                scenes = result.get("result", {}).get("data", {}).get("json", {}).get("scenes", [])
                
                self.log(f"  📊 Found {len(scenes)} scenes in project\n")
                
                for idx, scene in enumerate(scenes):
                    scene_media_id = scene.get("video", {}).get("mediaGenerationId")
                    
                    # Log first scene structure for debugging
                    if idx == 0:
                        self.log(f"  🔍 Sample scene structure: {json.dumps(scene, indent=2)[:500]}...\n")
                    
                    if scene_media_id == media_id:
                        video_data = scene.get("video", {})
                        self.log(f"  ✅ Found matching scene! Video data keys: {list(video_data.keys())}\n")
                        
                        # Try multiple paths for video URL
                        video_url = (video_data.get("uri") or 
                                    video_data.get("outputUri") or
                                    video_data.get("url") or
                                    video_data.get("downloadUrl") or
                                    video_data.get("signedUri"))
                        
                        if video_url:
                            self.log(f"  ✅ Found video URL: {video_url[:100]}...\n")
                            return video_url
                        else:
                            self.log(f"  ⚠️ Scene found but no URL in video data\n")
                            self.log(f"  📋 Video data: {json.dumps(video_data, indent=2)}\n")
                            return None
                
                self.log(f"  ⚠️ Media ID not found in searchProjectScenes (checked {len(scenes)} scenes)\n")
                if len(scenes) > 0:
                    self.log(f"  💡 Sample media IDs in project: {[s.get('video', {}).get('mediaGenerationId', 'N/A')[:30] for s in scenes[:3]]}\n")
            else:
                self.log(f"  ⚠️ searchProjectScenes returned {resp.status_code}: {resp.text[:200]}\n")
            
            return None
            
        except Exception as e:
            self.log(f"  ❌ Error fetching video URL: {e}\n")
            import traceback
            self.log(f"  🔍 Traceback: {traceback.format_exc()}\n")
            return None
    
    def _extract_media_id(self, operation: Dict) -> Optional[str]:
        """Extract media ID từ operation response"""
        try:
            # Try multiple paths
            metadata = operation.get("operation", {}).get("metadata", {})
            if isinstance(metadata, dict):
                video_data = metadata.get("video", {})
                if isinstance(video_data, dict):
                    media_id = video_data.get("mediaGenerationId")
                    if media_id:
                        return media_id
            
            # Fallback: search in operation itself
            media_id = operation.get("mediaId") or operation.get("mediaGenerationId")
            return media_id
            
        except Exception:
            return None
    
    def _extract_video_url(self, operation: Dict) -> Optional[str]:
        """Extract video URL từ operation response using recursive extraction"""
        try:
            # Use the powerful _extract_file_urls to find ANY video URL in the response
            urls = _extract_file_urls(operation)
            if urls:
                # Return first video URL found
                for url in urls:
                    if ".mp4" in url.lower() or "/video/" in url.lower():
                        return url
                # If no mp4, return first URL
                return urls[0]
            
            return None
            
        except Exception:
            return None
    
    def _extract_error_message(self, operation: Dict) -> str:
        """Extract error message từ failed operation"""
        try:
            error = operation.get("operation", {}).get("error", {})
            if isinstance(error, dict):
                message = error.get("message", "Unknown error")
                code = error.get("code", "")
                return f"{message} (Code: {code})"
            return "Unknown error"
        except Exception:
            return "Unknown error"
    
    def download_and_merge_scenes(self, project: ExtendProject, output_dir: Path) -> Optional[Path]:
        """Download và merge các scenes thành 1 video cuối cùng
        
        Args:
            project: Project chứa video URLs
            output_dir: Thư mục output
            
        Returns:
            Path to merged video nếu thành công
        """
        try:
            self.log(f"\n🎬 DOWNLOAD & MERGE: {project.project_name}\n")
            
            if not project.video_urls:
                self.log(f"  ❌ Không có video URLs để download\n")
                return None
            
            # Create temp directory for downloads
            temp_dir = output_dir / "temp" / project.project_name
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # ✅ Thư mục lưu từng scene riêng lẻ cho project này
            scenes_dir = output_dir / f"{project.project_name}_scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            
            # Download all videos
            downloaded_paths = []
            merged_input_paths = []
            for i, url in enumerate(project.video_urls):
                video_name = f"scene_{i+1:03d}.mp4"
                temp_video_path = temp_dir / video_name
                
                self.log(f"  📥 Scene {i+1}/{len(project.video_urls)}: {video_name}\n")
                download_ok = False
                for attempt in range(3):
                    if download_video(url, temp_video_path, self.log):
                        download_ok = True
                        break
                    wait_time = (attempt + 1) * 2
                    self.log(f"  ⚠️ Retry download scene {i+1} ({attempt+1}/3) sau {wait_time}s...\n")
                    time.sleep(wait_time)
                if download_ok:
                    # Move file sang thư mục scenes để user sử dụng từng file
                    final_scene_path = scenes_dir / video_name
                    try:
                        temp_video_path.replace(final_scene_path)
                    except Exception:
                        # Nếu move lỗi, giữ nguyên file temp nhưng vẫn dùng cho merge
                        final_scene_path = temp_video_path
                    downloaded_paths.append(final_scene_path)
                    merged_input_paths.append(final_scene_path)
                else:
                    self.log(f"  ❌ Failed to download scene {i+1}\n")
                    return None
            
            # ✅ Kiểm tra xem đã có scene_builder chưa (từ concat API)
            project_index = self._parse_project_index(project.project_name)
            if project_index > 1:
                scene_builder_name = f"scene_builder_{project_index}.mp4"
            else:
                scene_builder_name = "scene_builder.mp4"
            existing_scene_builder = output_dir / scene_builder_name
            
            if existing_scene_builder.exists():
                self.log(f"✅ Đã có scene_builder từ concat API: {existing_scene_builder}\n")
                self.log(f"💡 Bỏ qua merge, sử dụng scene_builder có sẵn\n")
                # Cleanup temp directory
                try:
                    if temp_dir.exists():
                        import shutil
                        shutil.rmtree(temp_dir)
                except Exception as e:
                    self.log(f"  ⚠️ Cleanup warning: {e}\n")
                return existing_scene_builder
            
            # Merge videos - tạo scene_builder trực tiếp (không tạo _merged.mp4)
            output_path = output_dir / scene_builder_name
            self.log(f"\n🔗 Merging {len(merged_input_paths)} scenes thành {scene_builder_name}...\n")
            
            # Try re-encode mode for smooth playback (no stuttering)
            self.log(f"  💡 Using re-encode mode để tránh khựng giữa các clip\n")
            if merge_videos_with_ffmpeg_reencode(merged_input_paths, output_path, 
                                                use_overlap=True, log_callback=self.log):
                self.log(f"✅ SCENE BUILDER CREATED: {output_path}\n")
                # Cleanup temp directory (giữ lại các file scenes trong scenes_dir)
                try:
                    if temp_dir.exists():
                        import shutil
                        shutil.rmtree(temp_dir)
                except Exception as e:
                    self.log(f"  ⚠️ Cleanup warning: {e}\n")
                
                return output_path
            else:
                self.log(f"❌ Merge failed\n")
                return None
                
        except Exception as e:
            self.log(f"❌ Download/merge error: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            return None
    
    def process_project(self, project: ExtendProject, 
                       output_dir: Path = None,
                       txt_filename: str = None,
                       status_callback: Callable[[int, str, str], None] = None) -> bool:
        """Xử lý 1 project hoàn chỉnh
        
        Args:
            project: Project cần xử lý
            output_dir: Thư mục output (default: downloaded_videos/extend_merged)
            txt_filename: Tên file txt gốc (để đặt tên output)
            status_callback: Callback(segment_index, status, message) để update UI
            
        Returns:
            True nếu thành công, False nếu có lỗi
        """
        try:
            self.log(f"\n{'='*60}\n")
            self.log(f"🚀 BẮT ĐẦU PROJECT: {project.project_name}\n")
            self.log(f"📊 Số đoạn: {len(project.segments)}\n")
            self.log(f"{'='*60}\n")
            
            media_ids = []
            total_segments = len(project.segments)
            
            def _mark_project_resume_done():
                project.resume_from_index = (total_segments + 1) if total_segments else 1
            
            # Xác định vị trí cần chạy tiếp
            resume_from = getattr(project, "resume_from_index", 1)
            if not isinstance(resume_from, int) or resume_from < 1:
                resume_from = 1
            
            # Đảm bảo không bỏ qua segment chưa hoàn thành (thiếu media_id)
            for seg in project.segments:
                if seg.index >= resume_from:
                    break
                if seg.status != "completed" or not seg.media_id:
                    resume_from = seg.index
                    break
            project.resume_from_index = resume_from
            last_media_id = None
            
            # Process từng segment
            for i, segment in enumerate(project.segments):
                # Bỏ qua các segment đã hoàn thành trước resume_from và có media_id hợp lệ
                if segment.index < resume_from:
                    if segment.status == "completed" and segment.media_id:
                        last_media_id = segment.media_id
                        media_ids.append(segment.media_id)
                        continue
                    else:
                        resume_from = segment.index
                        project.resume_from_index = resume_from
                
                # Nếu đã hoàn thành và có media_id, bỏ qua
                if segment.status == "completed" and segment.media_id:
                    last_media_id = segment.media_id
                    continue
                
                self.log(f"\n--- Đoạn {segment.index}/{len(project.segments)} (Global: #{segment.global_index}) ---\n")
                
                # Reset state trước khi chạy lại
                segment.status = "pending"
                segment.error_message = ""
                segment.media_id = None
                segment.video_url = None
                
                if status_callback:
                    status_callback(segment.global_index, "processing", f"Đang xử lý đoạn {segment.index}...")
                
                # Retry cho từng segment: 429/HIGH_TRAFFIC 3 lần, lỗi khác 5 lần
                max_retries_429 = 3
                max_retries_other = 5
                retry_count_429 = 0
                retry_count_other = 0
                
                while True:
                    # Segment đầu tiên hoặc chưa có media_id trước đó → tạo mới
                    if segment.index == 1 or last_media_id is None:
                        result = self.create_scene_from_text(segment.text)
                        if not result:
                            segment.status = "error"
                            segment.error_message = "Không thể tạo scene đầu tiên"
                            project.resume_from_index = segment.index
                            if status_callback:
                                status_callback(segment.global_index, "error", segment.error_message)
                            return False
                    else:
                        result = self.extend_scene(last_media_id, segment.text)
                        if not result:
                            segment.status = "error"
                            segment.error_message = "Không thể extend scene"
                            project.resume_from_index = segment.index
                            if status_callback:
                                status_callback(segment.global_index, "error", segment.error_message)
                            return False
                    
                    # Poll kết quả
                    poll_result = self.poll_operation(result["operations"])
                    if poll_result and poll_result["status"] == "completed":
                        segment.media_id = poll_result["media_id"]
                        segment.video_url = poll_result.get("video_url")
                        
                        if not segment.video_url and segment.media_id:
                            self.log(f"  🔄 Trying to fetch video URL for segment {segment.index}...\n")
                            segment.video_url = self._fetch_video_url_from_media_id(segment.media_id)
                        
                        segment.status = "completed"
                        last_media_id = segment.media_id
                        media_ids.append(segment.media_id)
                        project.resume_from_index = segment.index + 1
                        if status_callback:
                            status_callback(segment.global_index, "completed", f"✅ Đoạn {segment.index} hoàn thành")
                        break  # ra khỏi while, sang segment kế tiếp
                    
                    # Xử lý high traffic (trả về từ poll_operation)
                    if poll_result and poll_result.get("status") == "high_traffic":
                        retry_count_429 += 1
                        if retry_count_429 < max_retries_429:
                            wait_time = retry_count_429 * 5
                            self.log(f"  ⚠️ Poll gặp HIGH_TRAFFIC, retry {retry_count_429}/{max_retries_429} sau {wait_time}s...\n")
                            time.sleep(wait_time)
                            continue
                        else:
                            segment.status = "error"
                            segment.error_message = poll_result.get("error", "HIGH_TRAFFIC")
                            project.resume_from_index = segment.index
                            if status_callback:
                                status_callback(segment.global_index, "error", f"❌ {segment.error_message}")
                            return False
                    
                    # Lỗi khác
                    retry_count_other += 1
                    self._cookie_retry_count += 1
                    
                    # ✅ Sau 6 lần retry → restart BrowserContext (renew cookie)
                    if self._cookie_retry_count == 6 and not self._cookie_restarted and self.cookie_index is not None and self.renew_cookie_callback:
                        self.log(f"  🔄 Cookie {self.cookie_index+1} đã retry 6 lần (poll extend) → restart BrowserContext (renew cookie)\n")
                        
                        # Gọi renew cookie và restart context
                        try:
                            cookie_hash = self.client._cookie_hash if hasattr(self.client, '_cookie_hash') else None
                            
                            if cookie_hash:
                                # ✅ Gọi _renew_cookie_and_restart_context từ LabsFlowClient
                                new_cookies = LabsFlowClient._renew_cookie_and_restart_context(
                                    browser=LabsFlowClient._recaptcha_worker_browser if hasattr(LabsFlowClient, '_recaptcha_worker_browser') else None,
                                    cookie_hash=cookie_hash,
                                    old_cookies=self.client.cookies if hasattr(self.client, 'cookies') else {},
                                    proxy_config=getattr(self.client, 'proxy_config', None),
                                    user_agent=getattr(self.client, 'user_agent', ''),
                                    get_new_cookies_callback=self.renew_cookie_callback,
                                )
                                
                                if new_cookies:
                                    self.client.cookies = new_cookies
                                    if self.client.fetch_access_token():
                                        self._cookie_restarted = True
                                        self._cookie_retry_count = 0
                                        self.log(f"  ✅ Cookie {self.cookie_index+1} đã được renew và restart thành công\n")
                                    else:
                                        self.log(f"  ⚠️ Cookie {self.cookie_index+1} renew thành công nhưng fetch token fail\n")
                                else:
                                    self.log(f"  ⚠️ Không thể renew cookie {self.cookie_index+1}\n")
                        except Exception as renew_err:
                            self.log(f"  ⚠️ Lỗi khi renew cookie {self.cookie_index+1}: {renew_err}\n")
                        
                        # Tiếp tục retry với cookie (có thể đã được renew)
                        continue
                    
                    # ✅ Sau lần thứ 7 (sau khi đã restart) mà vẫn lỗi → raise exception để đánh dấu cookie die
                    if self._cookie_retry_count >= 7 and self._cookie_restarted:
                        self.log(f"  💀 Cookie {self.cookie_index+1} đã restart nhưng vẫn lỗi poll extend sau lần thứ 7 → đánh dấu die\n")
                        # Raise exception để extend_worker có thể xử lý và switch cookie
                        raise Exception(f"Cookie {self.cookie_index+1} die sau 7 lần retry (poll extend)")
                    
                    if retry_count_other < max_retries_other:
                        wait_time = retry_count_other * 5
                        err_msg = poll_result.get("error", "Poll timeout/error") if poll_result else "Poll timeout/error"
                        self.log(f"  ⚠️ Poll extend lỗi (attempt {retry_count_other}/{max_retries_other}, cookie retry: {self._cookie_retry_count}): {err_msg}, retry sau {wait_time}s...\n")
                        time.sleep(wait_time)
                        continue
                    
                    # Hết retry
                    segment.status = "error"
                    segment.error_message = poll_result.get("error", "Poll timeout/error") if poll_result else "Poll timeout/error"
                    project.resume_from_index = segment.index
                    if status_callback:
                        status_callback(segment.global_index, "error", f"❌ {segment.error_message}")
                    return False
            
            # ✅ Concat logic: Nếu > 20 segments, chia thành batch 20 và dùng FFmpeg để nối lại
            self.log(f"\n🔗 Bắt đầu concat {len(media_ids)} scenes...\n")
            self.log(f"📋 Media IDs: {media_ids}\n")
            
            # ✅ Nếu > 20 segments: chia thành batch 20, mỗi batch dùng API concat Google, sau đó dùng FFmpeg nối lại
            if len(media_ids) > 20:
                self.log(f"📦 Số segments ({len(media_ids)}) > 20, chia thành batch và dùng FFmpeg để nối lại\n")
                concat_result = self._concat_large_project(media_ids, project, output_dir, txt_filename)
            else:
                # ≤ 20 segments: dùng API concat Google như bình thường
                concat_result = self.concat_scenes(media_ids)
            
            # Check if concat completely failed (None)
            if concat_result is None:
                self.log(f"❌ Concat API hoàn toàn thất bại\n")
                self.log(f"💡 Chuyển sang phương án thay thế: Download từng scene riêng\n")
                operation_name = None
            # Check if concat was unauthorized or connection error (need to fallback)
            elif concat_result.get("status") in ("unauthorized", "connection_error"):
                status = concat_result.get("status")
                if status == "unauthorized":
                    self.log(f"⚠️ Concat API không khả dụng (401 Unauthorized)\n")
                else:
                    self.log(f"⚠️ Concat API không khả dụng (Connection Error)\n")
                self.log(f"💡 Chuyển sang phương án thay thế: Download từng scene riêng\n")
                # Skip concat and use individual scenes
                operation_name = None
            else:
                operation_name = concat_result.get("operation_name")
            
            # Poll concat status if we have operation_name
            if operation_name:
                self.log(f"⏳ Polling concat operation: {operation_name}\n")
                concat_result = self.poll_concat_status(operation_name)
                
                if concat_result:
                    # Determine output path - ensure it's a Path object
                    if output_dir and isinstance(output_dir, (str, Path)):
                        # Only convert if it's string or Path
                        base_output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
                    else:
                        # Default path if output_dir is None, function, or invalid type
                        base_output_dir = Path("downloaded_videos") / "extend_merged"
                        if output_dir:  # Log warning if it's not None but invalid
                            self.log(f"  ⚠️ Invalid output_dir type: {type(output_dir)}, using default\n")
                    
                    base_output_dir.mkdir(parents=True, exist_ok=True)
                    
                    # ✅ Tạo thư mục con theo tên file txt (giống text to video)
                    if txt_filename:
                        txt_name = Path(txt_filename).stem
                        final_output_dir = base_output_dir / txt_name
                        final_output_dir.mkdir(parents=True, exist_ok=True)
                        self.log(f"📁 Lưu vào subfolder: {txt_name} → {final_output_dir}\n")
                    else:
                        final_output_dir = base_output_dir
                        self.log(f"📁 Lưu vào folder chính: {final_output_dir}\n")
                    
                    # Build filename: scene_builder.mp4 (hoặc scene_builder_{project_index}.mp4 nếu có nhiều project trong cùng file)
                    project_index = self._parse_project_index(project.project_name)
                    if project_index > 1:
                        output_filename = f"scene_builder_{project_index}.mp4"
                    else:
                        output_filename = "scene_builder.mp4"
                    final_output_path = final_output_dir / output_filename
                    
                    if isinstance(concat_result, dict):
                        result_type = concat_result.get("type")
                        
                        # Handle encodedVideo (base64)
                        if result_type == "encoded":
                            self.log(f"📼 Decoding concat video từ base64...\n")
                            encoded_data = concat_result.get("data")
                            if decode_and_save_video(encoded_data, final_output_path, self.log):
                                project.concat_url = str(final_output_path)
                                project.status = "completed"
                                self.log(f"✅ PROJECT HOÀN THÀNH: {project.project_name}\n")
                                self.log(f"📁 Video saved: {final_output_path}\n")
                                _mark_project_resume_done()
                                return True
                        
                        # Handle URL
                        elif result_type == "url":
                            video_url = concat_result.get("data")
                            self.log(f"📥 Downloading concat video...\n")
                            if download_video(video_url, final_output_path, self.log):
                                project.concat_url = str(final_output_path)
                                project.status = "completed"
                                self.log(f"✅ PROJECT HOÀN THÀNH: {project.project_name}\n")
                                self.log(f"📁 Video saved: {final_output_path}\n")
                                _mark_project_resume_done()
                                return True
                    
                    # Fallback for old string return
                    elif isinstance(concat_result, str):
                        self.log(f"📥 Downloading concat video...\n")
                        if download_video(concat_result, final_output_path, self.log):
                            project.concat_url = str(final_output_path)
                            project.status = "completed"
                            self.log(f"✅ PROJECT HOÀN THÀNH: {project.project_name}\n")
                            self.log(f"📁 Video saved: {final_output_path}\n")
                    _mark_project_resume_done()
                    return True
                else:
                    self.log(f"⚠️ Concat không trả về URL, nhưng các scenes đã hoàn thành\n")
                    self.log(f"💡 Workaround: Lưu URLs của từng scene để download riêng\n")
                    
                    # Collect individual video URLs
                    individual_urls = []
                    for seg in project.segments:
                        if seg.video_url:
                            individual_urls.append(seg.video_url)
                            self.log(f"  📹 Scene {seg.index}: {seg.video_url}\n")
                    
                    if individual_urls:
                        project.video_urls = individual_urls
                        project.status = "completed_without_concat"
                        self.log(f"✅ PROJECT HOÀN THÀNH (các scene riêng lẻ): {project.project_name}\n")
                        self.log(f"📊 Số scenes: {len(individual_urls)}\n")
                        
                        # Automatically download and merge if we have URLs
                        self.log(f"🚀 Bắt đầu download và merge tự động...\n")
                        
                        # Use provided output_dir or default - ensure it's a Path object
                        if output_dir and isinstance(output_dir, (str, Path)):
                            base_output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
                        else:
                            base_output_dir = Path("downloaded_videos") / "extend_merged"
                            if output_dir:  # Log warning if it's not None but invalid
                                self.log(f"  ⚠️ Invalid output_dir type: {type(output_dir)}, using default\n")
                        
                        # ✅ Tạo thư mục con theo tên file txt (giống text to video)
                        if txt_filename:
                            txt_name = Path(txt_filename).stem
                            final_output_dir = base_output_dir / txt_name
                            final_output_dir.mkdir(parents=True, exist_ok=True)
                            self.log(f"📁 Lưu vào subfolder: {txt_name} → {final_output_dir}\n")
                        else:
                            final_output_dir = base_output_dir
                            self.log(f"📁 Lưu vào folder chính: {final_output_dir}\n")
                        
                        # Download and merge
                        merged_path = self.download_and_merge_scenes(project, final_output_dir)
                        
                        if merged_path:
                            # Rename to proper format
                            project_index = self._parse_project_index(project.project_name)
                            if project_index > 1:
                                final_filename = f"scene_builder_{project_index}.mp4"
                            else:
                                final_filename = "scene_builder.mp4"
                            final_path = final_output_dir / final_filename
                            
                            # Rename if needed
                            if merged_path != final_path:
                                try:
                                    merged_path.rename(final_path)
                                    self.log(f"  📝 Renamed to: {final_filename}\n")
                                    merged_path = final_path
                                except Exception as e:
                                    self.log(f"  ⚠️ Rename error: {e}\n")
                            
                            project.concat_url = str(merged_path)
                            self.log(f"🎉 PROJECT HOÀN TOÀN HOÀN THÀNH: {project.project_name}\n")
                            self.log(f"📁 Merged video: {merged_path}\n")
                            _mark_project_resume_done()
                            return True
                        else:
                            self.log(f"⚠️ Merge failed, nhưng đã có individual scene URLs\n")
                            _mark_project_resume_done()
                            return True  # Still return True because we got the scenes
                    else:
                        self.log(f"❌ Không có video URLs nào từ các scenes\n")
                    return False
            else:
                # No operation name - either unauthorized or concat API failed
                self.log(f"⚠️ Không có concat operation, sử dụng individual scenes\n")
                
                # Check if we already have video URLs from poll
                urls_already_fetched = sum(1 for seg in project.segments if seg.video_url)
                
                if urls_already_fetched == len(project.segments):
                    self.log(f"✅ Đã có sẵn video URLs từ poll operation ({urls_already_fetched}/{len(project.segments)})\n")
                else:
                    # Try to get video URLs for segments that don't have URLs yet
                    self.log(f"📡 Đang lấy video URLs còn thiếu từ searchProjectScenes...\n")
                    
                    for seg in project.segments:
                        if not seg.video_url and seg.media_id:
                            self.log(f"  🔄 Fetching URL for segment {seg.index}...\n")
                            seg.video_url = self._fetch_video_url_from_media_id(seg.media_id)
                
                # Collect URLs
                individual_urls = []
                for seg in project.segments:
                    if seg.video_url:
                        individual_urls.append(seg.video_url)
                        self.log(f"  ✅ Segment {seg.index}: {seg.video_url[:80]}...\n")
                
                if individual_urls and len(individual_urls) == len(project.segments):
                    project.video_urls = individual_urls
                    project.status = "completed_without_concat"
                    self.log(f"✅ PROJECT HOÀN THÀNH (không concat): {project.project_name}\n")
                    self.log(f"📊 Đã lấy {len(individual_urls)} video URLs\n")
                    
                    # Automatically download and merge
                    self.log(f"🚀 Bắt đầu download và merge tự động...\n")
                    
                    # Use provided output_dir or default - ensure it's a Path object
                    if output_dir and isinstance(output_dir, (str, Path)):
                        base_output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
                    else:
                        base_output_dir = Path("downloaded_videos") / "extend_merged"
                        if output_dir:  # Log warning if it's not None but invalid
                            self.log(f"  ⚠️ Invalid output_dir type: {type(output_dir)}, using default\n")
                    
                    # ✅ Tạo thư mục con theo tên file txt (giống text to video)
                    if txt_filename:
                        txt_name = Path(txt_filename).stem
                        final_output_dir = base_output_dir / txt_name
                        final_output_dir.mkdir(parents=True, exist_ok=True)
                        self.log(f"📁 Lưu vào subfolder: {txt_name} → {final_output_dir}\n")
                    else:
                        final_output_dir = base_output_dir
                        self.log(f"📁 Lưu vào folder chính: {final_output_dir}\n")
                    
                    merged_path = self.download_and_merge_scenes(project, final_output_dir)
                    
                    if merged_path:
                        # Rename to proper format
                        project_index = self._parse_project_index(project.project_name)
                        if project_index > 1:
                            final_filename = f"scene_builder_{project_index}.mp4"
                        else:
                            final_filename = "scene_builder.mp4"
                        final_path = final_output_dir / final_filename
                        
                        # Rename if needed
                        if merged_path != final_path:
                            try:
                                merged_path.rename(final_path)
                                self.log(f"  📝 Renamed to: {final_filename}\n")
                                merged_path = final_path
                            except Exception as e:
                                self.log(f"  ⚠️ Rename error: {e}\n")
                        
                        project.concat_url = str(merged_path)
                        self.log(f"🎉 PROJECT HOÀN TOÀN HOÀN THÀNH: {project.project_name}\n")
                        self.log(f"📁 Merged video: {merged_path}\n")
                        _mark_project_resume_done()
                        return True
                    else:
                        self.log(f"⚠️ Merge failed, nhưng đã có individual scene URLs\n")
                        _mark_project_resume_done()
                        return True  # Still success because we got the scenes
                else:
                    self.log(f"❌ Không lấy được đủ video URLs ({len(individual_urls)}/{len(project.segments)})\n")
                return False
            
        except Exception as e:
            self.log(f"❌ Lỗi process project: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            project.status = "error"
            return False
    
    def process_project_with_retry(self, project: ExtendProject, 
                                  output_dir: Path = None,
                                  txt_filename: str = None,
                                  start_from_segment: int = 0,
                                  status_callback: Callable[[int, str, str], None] = None) -> bool:
        """Xử lý project với retry từ segment cụ thể
        
        Args:
            project: Project cần xử lý
            output_dir: Thư mục output
            txt_filename: Tên file txt gốc
            start_from_segment: Index segment bắt đầu (0-based)
            status_callback: Callback để update UI
            
        Returns:
            True nếu thành công
        """
        try:
            self.log(f"\n{'='*60}\n")
            self.log(f"🔄 RETRY PROJECT: {project.project_name} (từ segment {start_from_segment + 1})\n")
            self.log(f"📊 Số đoạn: {len(project.segments)}\n")
            self.log(f"{'='*60}\n")
            
            media_ids = []
            
            # Collect media_ids from completed segments before start_from_segment
            self.log(f"🔍 Thu thập media_ids từ {start_from_segment} segments đã hoàn thành...\n")
            for i in range(start_from_segment):
                segment = project.segments[i]
                self.log(f"📊 Segment #{segment.index}: status={segment.status}, media_id={segment.media_id[:20] if segment.media_id else 'None'}...\n")
                if segment.status == "completed" and segment.media_id:
                    media_ids.append(segment.media_id)
                    self.log(f"  ✅ Segment {i+1} đã hoàn thành trước đó: {segment.media_id}\n")
            
            self.log(f"📦 Đã thu thập {len(media_ids)} media_ids để tái sử dụng\n")
            
            # Process từ segment start_from_segment trở đi
            for i in range(start_from_segment, len(project.segments)):
                segment = project.segments[i]
                self.log(f"\n--- Retry Đoạn {segment.index}/{len(project.segments)} (Global: #{segment.global_index}) ---\n")
                
                if status_callback:
                    status_callback(segment.global_index, "processing", f"Đang retry đoạn {segment.index}...")
                
                # Segment đầu tiên: tạo bằng Text-to-Video
                if i == 0:
                    result = self.create_scene_from_text(segment.text)
                    if not result:
                        segment.status = "error"
                        segment.error_message = "Không thể tạo scene đầu tiên"
                        if status_callback:
                            status_callback(segment.global_index, "error", segment.error_message)
                        return False
                    
                    # Poll để lấy media_id và video_url
                    poll_result = self.poll_operation(result["operations"])
                    if poll_result and poll_result["status"] == "completed":
                        segment.media_id = poll_result["media_id"]
                        segment.video_url = poll_result.get("video_url")
                        
                        if not segment.video_url and segment.media_id:
                            self.log(f"  🔄 Trying to fetch video URL for segment {segment.index}...\n")
                            segment.video_url = self._fetch_video_url_from_media_id(segment.media_id)
                        
                        segment.status = "completed"
                        media_ids.append(segment.media_id)
                        if status_callback:
                            status_callback(segment.global_index, "completed", f"✅ Đoạn {segment.index} hoàn thành")
                    else:
                        segment.status = "error"
                        segment.error_message = poll_result.get("error", "Poll timeout/error")
                        if status_callback:
                            status_callback(segment.global_index, "error", f"❌ {segment.error_message}")
                        return False
                
                # Các segment tiếp theo: extend từ segment trước
                else:
                    prev_media_id = project.segments[i-1].media_id
                    if not prev_media_id:
                        segment.status = "error"
                        segment.error_message = "Không có media_id từ đoạn trước"
                        if status_callback:
                            status_callback(segment.global_index, "error", segment.error_message)
                        return False
                    
                    result = self.extend_scene(prev_media_id, segment.text)
                    if not result:
                        segment.status = "error"
                        segment.error_message = "Không thể extend scene"
                        if status_callback:
                            status_callback(segment.global_index, "error", segment.error_message)
                        return False
                    
                    # Poll để lấy media_id và video_url
                    poll_result = self.poll_operation(result["operations"])
                    if poll_result and poll_result["status"] == "completed":
                        segment.media_id = poll_result["media_id"]
                        segment.video_url = poll_result.get("video_url")
                        
                        if not segment.video_url and segment.media_id:
                            self.log(f"  🔄 Trying to fetch video URL for segment {segment.index}...\n")
                            segment.video_url = self._fetch_video_url_from_media_id(segment.media_id)
                        
                        segment.status = "completed"
                        media_ids.append(segment.media_id)
                        if status_callback:
                            status_callback(segment.global_index, "completed", f"✅ Đoạn {segment.index} hoàn thành")
                    else:
                        segment.status = "error"
                        segment.error_message = poll_result.get("error", "Poll timeout/error")
                        if status_callback:
                            status_callback(segment.global_index, "error", f"❌ {segment.error_message}")
                        return False
            
            # Tiếp tục với concat logic như process_project bình thường
            return self._finish_project_processing(project, media_ids, output_dir, txt_filename)
            
        except Exception as e:
            self.log(f"❌ Lỗi retry project: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            project.status = "error"
            return False
    
    def _finish_project_processing(self, project: ExtendProject, media_ids: List[str], 
                                  output_dir: Path = None, txt_filename: str = None) -> bool:
        """Hoàn thành xử lý project (concat và save)"""
        try:
            # ✅ Concat logic: Nếu > 20 segments, chia thành batch 20 và dùng FFmpeg để nối lại
            self.log(f"\n🔗 Bắt đầu concat {len(media_ids)} scenes...\n")
            self.log(f"📋 Media IDs: {media_ids}\n")
            
            # ✅ Nếu > 20 segments: chia thành batch 20, mỗi batch dùng API concat Google, sau đó dùng FFmpeg nối lại
            if len(media_ids) > 20:
                self.log(f"📦 Số segments ({len(media_ids)}) > 20, chia thành batch và dùng FFmpeg để nối lại\n")
                concat_result = self._concat_large_project(media_ids, project, output_dir, txt_filename)
            else:
                # ≤ 20 segments: dùng API concat Google như bình thường
                concat_result = self.concat_scenes(media_ids)
            
            # Same logic as in process_project for concat handling
            if concat_result is None:
                self.log(f"❌ Concat API hoàn toàn thất bại\n")
                self.log(f"💡 Chuyển sang phương án thay thế: Download từng scene riêng\n")
                operation_name = None
            elif concat_result.get("status") in ("unauthorized", "connection_error"):
                status = concat_result.get("status")
                if status == "unauthorized":
                    self.log(f"⚠️ Concat API không khả dụng (401 Unauthorized)\n")
                else:
                    self.log(f"⚠️ Concat API không khả dụng (Connection Error)\n")
                self.log(f"💡 Chuyển sang phương án thay thế: Download từng scene riêng\n")
                operation_name = None
            else:
                operation_name = concat_result.get("operation_name")
            
            # Continue with same concat/fallback logic as process_project...
            # (Copy the concat handling logic from process_project)
            
            if operation_name:
                self.log(f"⏳ Polling concat operation: {operation_name}\n")
                concat_result = self.poll_concat_status(operation_name)
                
                if concat_result:
                    # Same output handling as process_project
                    if output_dir and isinstance(output_dir, (str, Path)):
                        base_output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
                    else:
                        base_output_dir = Path("downloaded_videos") / "extend_merged"
                        if output_dir:
                            self.log(f"  ⚠️ Invalid output_dir type: {type(output_dir)}, using default\n")
                    
                    base_output_dir.mkdir(parents=True, exist_ok=True)
                    
                    # ✅ Tạo thư mục con theo tên file txt (giống text to video)
                    if txt_filename:
                        txt_name = Path(txt_filename).stem
                        final_output_dir = base_output_dir / txt_name
                        final_output_dir.mkdir(parents=True, exist_ok=True)
                        self.log(f"📁 Lưu vào subfolder: {txt_name} → {final_output_dir}\n")
                    else:
                        final_output_dir = base_output_dir
                        self.log(f"📁 Lưu vào folder chính: {final_output_dir}\n")
                    
                    project_index = self._parse_project_index(project.project_name)
                    if project_index > 1:
                        output_filename = f"scene_builder_{project_index}.mp4"
                    else:
                        output_filename = "scene_builder.mp4"
                    final_output_path = final_output_dir / output_filename
                    
                    if isinstance(concat_result, dict):
                        result_type = concat_result.get("type")
                        
                        if result_type == "encoded":
                            self.log(f"📼 Decoding concat video từ base64...\n")
                            encoded_data = concat_result.get("data")
                            if decode_and_save_video(encoded_data, final_output_path, self.log):
                                project.concat_url = str(final_output_path)
                                project.status = "completed"
                                self.log(f"✅ RETRY PROJECT HOÀN THÀNH: {project.project_name}\n")
                                self.log(f"📁 Video saved: {final_output_path}\n")
                                return True
                        
                        elif result_type == "url":
                            video_url = concat_result.get("data")
                            self.log(f"📥 Downloading concat video...\n")
                            if download_video(video_url, final_output_path, self.log):
                                project.concat_url = str(final_output_path)
                                project.status = "completed"
                                self.log(f"✅ RETRY PROJECT HOÀN THÀNH: {project.project_name}\n")
                                self.log(f"📁 Video saved: {final_output_path}\n")
                                return True
            
            # Fallback to individual scenes if concat fails
            self.log(f"⚠️ Concat không khả dụng, dùng individual scenes\n")
            
            urls_already_fetched = sum(1 for seg in project.segments if seg.video_url)
            
            if urls_already_fetched == len(project.segments):
                self.log(f"✅ Đã có sẵn video URLs từ poll operation ({urls_already_fetched}/{len(project.segments)})\n")
            else:
                self.log(f"📡 Đang lấy video URLs còn thiếu từ searchProjectScenes...\n")
                for seg in project.segments:
                    if not seg.video_url and seg.media_id:
                        self.log(f"  🔄 Fetching URL for segment {seg.index}...\n")
                        seg.video_url = self._fetch_video_url_from_media_id(seg.media_id)
            
            # Collect URLs and merge
            individual_urls = [seg.video_url for seg in project.segments if seg.video_url]
            
            if individual_urls and len(individual_urls) == len(project.segments):
                project.video_urls = individual_urls
                project.status = "completed_without_concat"
                
                # Auto download and merge
                if output_dir and isinstance(output_dir, (str, Path)):
                    base_output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
                else:
                    base_output_dir = Path("downloaded_videos") / "extend_merged"
                
                # ✅ Tạo thư mục con theo tên file txt (giống text to video)
                if txt_filename:
                    txt_name = Path(txt_filename).stem
                    final_output_dir = base_output_dir / txt_name
                    final_output_dir.mkdir(parents=True, exist_ok=True)
                    self.log(f"📁 Lưu vào subfolder: {txt_name} → {final_output_dir}\n")
                else:
                    final_output_dir = base_output_dir
                    self.log(f"📁 Lưu vào folder chính: {final_output_dir}\n")
                
                merged_path = self.download_and_merge_scenes(project, final_output_dir)
                
                if merged_path:
                    project_index = self._parse_project_index(project.project_name)
                    if project_index > 1:
                        final_filename = f"scene_builder_{project_index}.mp4"
                    else:
                        final_filename = "scene_builder.mp4"
                    final_path = final_output_dir / final_filename
                    
                    if merged_path != final_path:
                        try:
                            merged_path.rename(final_path)
                            self.log(f"  📝 Renamed to: {final_filename}\n")
                            merged_path = final_path
                        except Exception as e:
                            self.log(f"  ⚠️ Rename error: {e}\n")
                    
                    project.concat_url = str(merged_path)
                    project.status = "completed"
                    self.log(f"✅ RETRY PROJECT HOÀN THÀNH: {project.project_name}\n")
                    self.log(f"📁 Merged video: {merged_path}\n")
                    return True
            
            return False
            
        except Exception as e:
            self.log(f"❌ Lỗi finish project processing: {e}\n")
            import traceback
            self.log(f"🔍 Traceback: {traceback.format_exc()}\n")
            return False


def parse_text_file(file_path: str) -> List[str]:
    """Đọc file txt và parse thành list các đoạn text
    
    Args:
        file_path: Đường dẫn file txt
        
    Returns:
        List các dòng text (đã strip)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        return lines
    except Exception as e:
        print(f"❌ Lỗi đọc file: {e}")
        return []


def decode_and_save_video(encoded_video_base64: str, output_path: Path, log_callback: Callable[[str], None] = None) -> bool:
    """Decode base64 encoded video và save ra file
    
    Args:
        encoded_video_base64: Base64 encoded video data
        output_path: Đường dẫn save file
        log_callback: Callback để log
    
    Returns:
        True nếu thành công
    """
    log = log_callback or print
    try:
        log(f"📼 Decoding video: {output_path.name}\n")
        
        import base64
        
        # Decode base64 to bytes
        video_bytes = base64.b64decode(encoded_video_base64)
        
        # Save to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(video_bytes)
        
        if output_path.exists() and output_path.stat().st_size > 0:
            size_mb = output_path.stat().st_size / 1024 / 1024
            log(f"  ✅ Decoded & saved: {output_path.name} ({size_mb:.2f} MB)\n")
            return True
        else:
            log(f"  ❌ Decode failed: File empty or not exists\n")
            return False
            
    except Exception as e:
        log(f"  ❌ Decode error: {e}\n")
        return False


def download_video(url: str, output_path: Path, log_callback: Callable[[str], None] = None) -> bool:
    """Download video từ URL
    
    Args:
        url: Video URL
        output_path: Đường dẫn save file
        log_callback: Callback để log
    
    Returns:
        True nếu thành công
    """
    log = log_callback or print
    try:
        log(f"⬇️ Downloading: {output_path.name}\n")
        
        import requests
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        if output_path.exists() and output_path.stat().st_size > 0:
            log(f"  ✅ Downloaded: {output_path.name} ({output_path.stat().st_size / 1024 / 1024:.2f} MB)\n")
            return True
        else:
            log(f"  ❌ Download failed: File empty or not exists\n")
            return False
            
    except Exception as e:
        log(f"  ❌ Download error: {e}\n")
        return False


def merge_videos_with_ffmpeg_reencode(video_paths: List[Path], output_path: Path,
                                     use_overlap: bool = True,
                                     log_callback: Callable[[str], None] = None) -> bool:
    """Merge videos với re-encode để fix timing issues (slower but smoother)
    
    Args:
        video_paths: List đường dẫn các video cần merge
        output_path: Đường dẫn output
        use_overlap: True để cắt 1s overlap như Google (default=True)
        log_callback: Callback để log
    
    Returns:
        True nếu merge thành công
    """
    log = log_callback or print
    
    try:
        log(f"🔗 Merging {len(video_paths)} videos with ffmpeg (re-encode mode)...\n")
        
        if not video_paths:
            log(f"  ❌ No videos to merge\n")
            return False
        
        # Build filter_complex for smooth concat
        # This method re-encodes but ensures perfect timing
        filter_parts = []
        for i, video_path in enumerate(video_paths):
            if not video_path.exists():
                log(f"  ❌ Video not found: {video_path}\n")
                return False
            
            # Apply trim if needed (skip first 1s for subsequent videos)
            if i == 0:
                # First video: full duration
                filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}];[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
            else:
                if use_overlap:
                    # Subsequent videos: trim first 1 second exactly
                    filter_parts.append(f"[{i}:v]trim=start=1.0,setpts=PTS-STARTPTS[v{i}];[{i}:a]atrim=start=1.0,asetpts=PTS-STARTPTS[a{i}]")
                else:
                    filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}];[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
        
        # Concat all streams
        video_concat = "".join([f"[v{i}]" for i in range(len(video_paths))])
        audio_concat = "".join([f"[a{i}]" for i in range(len(video_paths))])
        filter_complex = ";".join(filter_parts) + f";{video_concat}concat=n={len(video_paths)}:v=1:a=0[outv];{audio_concat}concat=n={len(video_paths)}:v=0:a=1[outa]"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build input list
        inputs = []
        for vp in video_paths:
            inputs.extend(['-i', str(vp)])
        
        cmd = [
            'ffmpeg',
            *inputs,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'libx264',          # Re-encode with H.264
            '-preset', 'medium',         # Balance speed/quality
            '-crf', '23',                # Quality (lower = better)
            '-c:a', 'aac',               # Re-encode audio
            '-b:a', '192k',              # Audio bitrate
            '-movflags', '+faststart',   # Optimize for web
            '-r', '24',                  # Force 24fps (match VEO 3)
            '-y',
            str(output_path)
        ]
        
        log(f"  📝 Running ffmpeg concat (re-encode for smooth playback)...\n")
        log(f"  💡 Videos: {[p.name for p in video_paths]}\n")
        if use_overlap:
            log(f"  ⏱️ Trimming 1s from subsequent clips\n")
        
        # Run ffmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes for re-encode
        )
        
        if result.returncode == 0:
            if output_path.exists() and output_path.stat().st_size > 0:
                size_mb = output_path.stat().st_size / 1024 / 1024
                
                # Get duration
                try:
                    probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 
                                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                                str(output_path)]
                    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
                    if probe_result.returncode == 0:
                        duration = float(probe_result.stdout.strip())
                        log(f"  ✅ Merged successfully: {output_path.name} ({duration:.2f}s, {size_mb:.2f} MB)\n")
                        return True
                except Exception:
                    pass
                
                log(f"  ✅ Merged successfully: {output_path.name} ({size_mb:.2f} MB)\n")
                return True
            else:
                log(f"  ❌ Output file empty\n")
                log(f"  📋 FFmpeg stderr: {result.stderr[:500]}\n")
                return False
        else:
            log(f"  ❌ FFmpeg failed with code {result.returncode}\n")
            log(f"  📋 Error: {result.stderr[:500]}\n")
            return False
            
    except subprocess.TimeoutExpired:
        log(f"  ❌ FFmpeg timeout (>600s)\n")
        return False
    except Exception as e:
        log(f"  ❌ Merge error: {e}\n")
        import traceback
        log(f"  🔍 Traceback: {traceback.format_exc()}\n")
        return False


def merge_videos_with_ffmpeg_dissolve(video_paths: List[Path], output_path: Path,
                                      duration: float = 3.0, offset: float = 3.0,
                                      log_callback: Callable[[str], None] = None) -> bool:
    """Merge videos với dissolve transition (xfade) bằng ffmpeg."""
    log = log_callback or print
    try:
        if not video_paths:
            log("  ❌ No videos to merge\n")
            return False
        if len(video_paths) == 1:
            import shutil
            shutil.copy2(video_paths[0], output_path)
            log(f"  ✅ Single video copied: {output_path.name}\n")
            return True
        # ffmpeg check
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=5)
        except Exception:
            log("  ❌ ffmpeg not found\n")
            return False
        inputs = []
        for p in video_paths:
            if not p.exists():
                log(f"  ❌ Video not found: {p}\n")
                return False
            inputs += ['-i', str(p)]
        # Build xfade chain: chain transitions sequentially
        filter_cmds = []
        for i in range(1, len(video_paths)):
            prev = "[v0]" if i == 1 else f"[vx{i-1}]"
            cur = f"[{i}:v]"
            out = f"[vx{i}]"
            filter_cmds.append(f"{prev}{cur}xfade=transition=dissolve:duration={duration}:offset={offset}{out}")
        filter_complex = ";".join(filter_cmds)
        final_out = f"[vx{len(video_paths)-1}]"
        cmd = [
            'ffmpeg',
            *inputs,
            '-filter_complex', filter_complex,
            '-map', final_out,
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-y',
            str(output_path)
        ]
        log(f"  📋 FFmpeg (dissolve): {' '.join(cmd)}\n")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"  ❌ FFmpeg failed: {result.stderr[:400]}\n")
            # Fallback: thử copy mode (concat demuxer) không transition
            log("  💡 Fallback: dùng copy mode (không transition)")
            try:
                return merge_videos_with_ffmpeg(video_paths, output_path, use_overlap=False, log_callback=log)
            except Exception:
                return False
        if output_path.exists() and output_path.stat().st_size > 0:
            size_mb = output_path.stat().st_size / (1024 * 1024)
            log(f"  ✅ Merged with dissolve: {output_path.name} ({size_mb:.2f} MB)\n")
            return True
        log("  ❌ Output file missing or empty\n")
        return False
    except Exception as e:
        log(f"  ❌ Merge dissolve error: {e}\n")
        import traceback
        log(f"  🔍 Traceback: {traceback.format_exc()}\n")
        return False


def merge_videos_with_ffmpeg(video_paths: List[Path], output_path: Path, 
                             use_overlap: bool = True,
                             log_callback: Callable[[str], None] = None) -> bool:
    """Merge nhiều videos bằng ffmpeg với timing chính xác như Google
    
    Args:
        video_paths: List đường dẫn các video cần merge
        output_path: Đường dẫn output
        use_overlap: True để cắt 1s overlap như Google (default=True)
        log_callback: Callback để log
    
    Returns:
        True nếu merge thành công
    
    Note:
        - Dùng copy mode (không re-encode) để nhanh và giữ chất lượng
        - Xử lý overlap 1 giây giữa các clips (clip 2+ bỏ 1s đầu)
        - Timing chính xác đến nanosecond như Google API
    """
    log = log_callback or print
    
    try:
        log(f"🔗 Merging {len(video_paths)} videos with ffmpeg...\n")
        
        if not video_paths:
            log(f"  ❌ No videos to merge\n")
            return False
        
        # Kiểm tra ffmpeg
        try:
            subprocess.run(['ffmpeg', '-version'], 
                         capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            log(f"  ❌ ffmpeg not found. Please install ffmpeg\n")
            return False
        
        # Method 1: Concat demuxer (fastest, copy mode, no re-encode)
        # Create concat file list
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', 
                                        delete=False, encoding='utf-8') as f:
            concat_file = f.name
            
            for i, video_path in enumerate(video_paths):
                if not video_path.exists():
                    log(f"  ❌ Video not found: {video_path}\n")
                    return False
                
                # Google concat logic:
                # - First video: full duration (0s to 8s)
                # - Other videos: skip first 1s (1s to 8s) to avoid overlap
                if i == 0:
                    # First video - use full
                    f.write(f"file '{video_path.absolute()}'\n")
                else:
                    # Subsequent videos - need to trim first 1s
                    if use_overlap:
                        # Write video with inpoint (skip first 1 second)
                        # Format: file 'path'
                        #         inpoint 1.0
                        f.write(f"file '{video_path.absolute()}'\n")
                        f.write(f"inpoint 1.000000000\n")  # Skip 1s with nanosecond precision
                    else:
                        f.write(f"file '{video_path.absolute()}'\n")
        
        try:
            # Build ffmpeg command
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                'ffmpeg',
                '-f', 'concat',                    # Concat demuxer
                '-safe', '0',                       # Allow absolute paths
                '-i', concat_file,                  # Input concat list
                '-c:v', 'copy',                     # Copy video stream (no re-encode)
                '-c:a', 'copy',                     # Copy audio stream (no re-encode)
                '-movflags', '+faststart',          # Optimize for web playback
                '-avoid_negative_ts', 'make_zero',  # Fix negative timestamps
                '-fflags', '+genpts+igndts',        # Generate PTS + ignore DTS
                '-max_interleave_delta', '0',       # Fix interleaving issues
                '-fps_mode', 'passthrough',         # Keep original frame timing
                '-y',                               # Overwrite output
                str(output_path)
            ]
            
            log(f"  📝 Running ffmpeg concat (copy mode)...\n")
            log(f"  💡 Videos: {[p.name for p in video_paths]}\n")
            if use_overlap:
                log(f"  ⏱️ Using 1s overlap trimming (like Google API)\n")
            
            # Run ffmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            
            if result.returncode == 0:
                if output_path.exists() and output_path.stat().st_size > 0:
                    duration_info = ""
                    
                    # Try to get duration
                    try:
                        probe_cmd = [
                            'ffprobe',
                            '-v', 'error',
                            '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1',
                            str(output_path)
                        ]
                        probe_result = subprocess.run(probe_cmd, capture_output=True, 
                                                     text=True, timeout=10)
                        if probe_result.returncode == 0:
                            duration = float(probe_result.stdout.strip())
                            duration_info = f" ({duration:.2f}s)"
                    except Exception:
                        pass
                    
                    size_mb = output_path.stat().st_size / 1024 / 1024
                    log(f"  ✅ Merged successfully: {output_path.name}{duration_info} ({size_mb:.2f} MB)\n")
                    return True
                else:
                    log(f"  ❌ Output file empty or not exists\n")
                    log(f"  📋 FFmpeg stderr: {result.stderr[:500]}\n")
                    return False
            else:
                log(f"  ❌ FFmpeg failed with code {result.returncode}\n")
                log(f"  📋 Error: {result.stderr[:500]}\n")
                return False
                
        finally:
            # Cleanup concat file
            try:
                os.unlink(concat_file)
            except Exception:
                pass
                
    except subprocess.TimeoutExpired:
        log(f"  ❌ FFmpeg timeout (>300s)\n")
        return False
    except Exception as e:
        log(f"  ❌ Merge error: {e}\n")
        import traceback
        log(f"  🔍 Traceback: {traceback.format_exc()}\n")
        return False


def create_projects_from_segments(segments: List[str], group_size: int) -> List[ExtendProject]:
    """Gom nhóm các đoạn text thành các projects
    
    Logic:
    - Chia segments thành các nhóm có group_size đoạn
    - Các dòng dư không chia hết: thêm vào Project cuối nếu tổng ≤ 60
    - Nếu Project cuối + dòng dư > 60: tạo Project mới riêng
    
    Args:
        segments: List các đoạn text
        group_size: Số đoạn mỗi project (1-60)
        
    Returns:
        List các ExtendProject
    """
    projects = []
    if not segments:
        return projects
    
    total_segments = len(segments)
    num_full_groups = total_segments // group_size
    remainder = total_segments % group_size
    
    # Tạo các project đầy đủ
    for i in range(num_full_groups):
        start_idx = i * group_size
        end_idx = start_idx + group_size
        group = segments[start_idx:end_idx]
        project_index = i + 1
        project_id = str(uuid.uuid4())
        
        # Tạo list ExtendSegment cho project này
        project_segments = []
        for j, text in enumerate(group):
            global_index = start_idx + j + 1  # Thứ tự global (1, 2, 3...)
            segment = ExtendSegment(
                index=j + 1,  # Thứ tự trong project (1, 2, 3...)
                global_index=global_index,
                text=text
            )
            project_segments.append(segment)
        
        project = ExtendProject(
            project_id=project_id,
            project_name=f"Project_{project_index}",
            segments=project_segments
        )
        projects.append(project)
    
    # ✅ Xử lý dòng dư theo quy tắc mới
    if remainder > 0:
        last_project = projects[-1] if projects else None
        last_project_size = len(last_project.segments) if last_project else 0
        
        # ✅ Quy tắc: Nếu Project cuối + dòng dư ≤ 60: thêm vào Project cuối
        # ✅ Nếu Project cuối + dòng dư > 60: tạo Project mới riêng
        if last_project and (last_project_size + remainder) <= 60:
            # Thêm dòng dư vào Project cuối
            start_idx = num_full_groups * group_size
            for j, text in enumerate(segments[start_idx:], start=last_project_size):
                global_index = start_idx + (j - last_project_size) + 1
                segment = ExtendSegment(
                    index=j + 1,  # Tiếp tục đếm trong project
                    global_index=global_index,
                    text=text
                )
                last_project.segments.append(segment)
        else:
            # Tạo Project mới cho dòng dư (vì Project cuối + dòng dư > 60)
            start_idx = num_full_groups * group_size
            group = segments[start_idx:]
            project_index = len(projects) + 1
            project_id = str(uuid.uuid4())
            
            project_segments = []
            for j, text in enumerate(group):
                global_index = start_idx + j + 1
                segment = ExtendSegment(
                    index=j + 1,
                    global_index=global_index,
                    text=text
                )
                project_segments.append(segment)
            
            project = ExtendProject(
                project_id=project_id,
                project_name=f"Project_{project_index}",
                segments=project_segments
            )
            projects.append(project)
    
    return projects


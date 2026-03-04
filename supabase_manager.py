#!/usr/bin/env python3
"""
Supabase Manager - Quản lý kết nối và API calls với Supabase
Thay thế cho MySQL database trong iting_api.py

Author: mavanhuy30
"""

import json
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import requests
import bcrypt  # Database lưu bcrypt hash

from subscription_policies import (
    get_subscription_limits,
    normalize_subscription_type,
)

class SupabaseManager:
    """Quản lý kết nối và operations với Supabase"""
    
    def __init__(self, url: str = None, anon_key: str = None):
        self.url = url or "https://vmgqbkadkxaucnzfmpmo.supabase.co"
        self.anon_key = anon_key or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZtZ3Fia2Fka3hhdWNuemZtcG1vIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE3OTcwMDQsImV4cCI6MjA3NzM3MzAwNH0.kCwSd_MEptWVonItr2VFWReLopF7BKWpK5hI8u97txc"
        self.headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.rest_url = f"{self.url}/rest/v1"
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None, params: Dict = None) -> Tuple[bool, Dict]:
        """Thực hiện HTTP request đến Supabase với timeout và retry"""
        try:
            url = f"{self.rest_url}/{endpoint}"
            
            # Giảm timeout để nhanh hơn
            timeout = 5  # 5 seconds timeout (giảm từ 10s)
            
            if method.upper() == "GET":
                response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
            elif method.upper() == "POST":
                response = requests.post(url, headers=self.headers, json=data, params=params, timeout=timeout)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=self.headers, json=data, params=params, timeout=timeout)
            elif method.upper() == "PATCH":
                response = requests.patch(url, headers=self.headers, json=data, params=params, timeout=timeout)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=self.headers, params=params, timeout=timeout)
            else:
                return False, {"error": f"Unsupported HTTP method: {method}"}
            
            if response.status_code in [200, 201, 204]:
                try:
                    return True, response.json() if response.text else {}
                except:
                    return True, {}
            else:
                try:
                    error_data = response.json()
                except:
                    error_data = {"error": response.text}
                return False, {"error": f"HTTP {response.status_code}", "details": error_data}
                
        except requests.exceptions.Timeout:
            return False, {"error": "Connection timeout - check internet connection"}
        except requests.exceptions.ConnectionError:
            return False, {"error": "Connection failed - check internet connection"}
        except Exception as e:
            return False, {"error": str(e)}
    
    # ==================== USER MANAGEMENT ====================
    
    def create_user(self, username: str, password: str, role: str = "tool") -> Tuple[bool, Dict]:
        """Tạo user mới - HASH PASSWORD BẰNG BCRYPT"""
        try:
            # Hash password bằng bcrypt (giống như database hiện tại)
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            
            user_data = {
                "username": username,
                "password": hashed_password.decode('utf-8'),  # Bcrypt hash
                "role": role
            }
            
            return self._make_request("POST", "users", user_data)
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def get_user_by_username(self, username: str) -> Tuple[bool, Dict]:
        """Lấy thông tin user theo username"""
        params = {"username": f"eq.{username}", "select": "*"}
        return self._make_request("GET", "users", params=params)
    
    def get_user_by_id(self, user_id: int) -> Tuple[bool, Dict]:
        """Lấy thông tin user theo ID"""
        params = {"id": f"eq.{user_id}"}
        return self._make_request("GET", "users", params=params)
    
    def update_user(self, user_id: int, updates: Dict) -> Tuple[bool, Dict]:
        """Cập nhật thông tin user"""
        params = {"id": f"eq.{user_id}"}
        return self._make_request("PATCH", "users", updates, params)
    
    def delete_user(self, user_id: int) -> Tuple[bool, Dict]:
        """Xóa user"""
        params = {"id": f"eq.{user_id}"}
        return self._make_request("DELETE", "users", params=params)
    
    def update_user_login_count(self, user_id: int) -> Tuple[bool, Dict]:
        """Cập nhật login_count cho user"""
        try:
            # Lấy thông tin user hiện tại
            success, user_data = self.get_user_by_id(user_id)
            if not success or not user_data:
                return False, {"error": "User not found"}
            
            user = user_data[0] if isinstance(user_data, list) and user_data else user_data
            current_count = user.get('login_count', 0)
            
            updates = {
                "login_count": current_count + 1
            }
            
            return self.update_user(user_id, updates)
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def update_user_device(self, user_id: int, device_id: str) -> Tuple[bool, Dict]:
        """Cập nhật device_id cho user"""
        try:
            updates = {
                "device_id": device_id,
                "last_device_change": datetime.now().isoformat()
            }
            return self.update_user(user_id, updates)
        except Exception as e:
            return False, {"error": str(e)}
    
    def get_user_device_info(self, user_id: int, is_key_login: bool = None) -> Tuple[bool, Optional[str]]:
        """Lấy device_info (số lượng cookie được phép) của user.
        
        Args:
            user_id: ID của user hoặc key
            is_key_login: True nếu login bằng activation key, False nếu login bằng username/password, None để tự động phát hiện
        
        Logic TÁCH BIỆT HOÀN TOÀN (không có ưu tiên):
        - Nếu is_key_login=True → CHỈ lấy từ activation_keys (KHÔNG kiểm tra users)
        - Nếu is_key_login=False → CHỈ lấy từ users (KHÔNG kiểm tra activation_keys)
        - Nếu is_key_login=None → Tự động phát hiện: kiểm tra activation_keys trước, nếu không có thì kiểm tra users
        """
        try:
            # ✅ Nếu biết rõ login method → chỉ lấy từ bảng tương ứng (TÁCH BIỆT HOÀN TOÀN)
            if is_key_login is True:
                # Login bằng key → CHỈ lấy từ activation_keys (KHÔNG kiểm tra users)
                try:
                    key_params = {
                        "id": f"eq.{user_id}",
                        "select": "device_info"
                    }
                    key_success, key_data = self._make_request("GET", "activation_keys", params=key_params)
                    
                    if key_success and key_data:
                        key = key_data[0] if isinstance(key_data, list) else key_data
                        device_info = key.get('device_info')
                        if device_info is not None:
                            print(f"✅ Lấy device_info từ activation_keys id={user_id}: {device_info}")
                            return True, str(device_info).strip()
                        else:
                            print(f"⚠️ Key id={user_id} tồn tại nhưng không có device_info")
                            return True, None
                    else:
                        print(f"⚠️ Không tìm thấy key id={user_id} trong activation_keys")
                        return True, None
                except Exception as e:
                    print(f"Error checking activation_keys table: {e}")
                    return False, None
            
            elif is_key_login is False:
                # Login bằng username/password → CHỈ lấy từ users (KHÔNG kiểm tra activation_keys)
                try:
                    success, user_data = self.get_user_by_id(user_id)
                    if success and user_data:
                        user = user_data[0] if isinstance(user_data, list) and user_data else user_data
                        device_info = user.get('device_info')
                        
                        if device_info is not None and str(device_info).strip():
                            print(f"✅ Lấy device_info từ users id={user_id}: {device_info}")
                            return True, str(device_info).strip()
                        else:
                            print(f"⚠️ User id={user_id} tồn tại nhưng không có device_info")
                            return True, None
                    else:
                        print(f"⚠️ Không tìm thấy user id={user_id} trong users")
                        return True, None
                except Exception as e:
                    print(f"Error checking users table: {e}")
                    return False, None
            
            else:
                # is_key_login=None → Tự động phát hiện (fallback cho code cũ)
                # Kiểm tra activation_keys trước
                try:
                    key_params = {
                        "id": f"eq.{user_id}",
                        "select": "device_info"
                    }
                    key_success, key_data = self._make_request("GET", "activation_keys", params=key_params)
                    
                    if key_success and key_data:
                        key = key_data[0] if isinstance(key_data, list) else key_data
                        device_info = key.get('device_info')
                        if device_info is not None:
                            print(f"✅ Lấy device_info từ activation_keys id={user_id}: {device_info}")
                            return True, str(device_info).strip()
                except Exception as e:
                    pass
                
                # Nếu không có trong activation_keys, kiểm tra users
                try:
                    success, user_data = self.get_user_by_id(user_id)
                    if success and user_data:
                        user = user_data[0] if isinstance(user_data, list) and user_data else user_data
                        device_info = user.get('device_info')
                        
                        if device_info is not None and str(device_info).strip():
                            print(f"✅ Lấy device_info từ users id={user_id}: {device_info}")
                            return True, str(device_info).strip()
                except Exception as e:
                    pass
                
                print(f"⚠️ Không tìm thấy user_id={user_id} trong cả activation_keys và users")
                return True, None
            
        except Exception as e:
            print(f"Error in get_user_device_info: {e}")
            return False, None
    
    def update_user_device_info(self, user_id: int, device_info: str) -> Tuple[bool, Dict]:
        """Cập nhật device_info (số lượng cookie được phép) cho user"""
        try:
            updates = {
                "device_info": device_info
            }
            return self.update_user(user_id, updates)
        except Exception as e:
            return False, {"error": str(e)}
    
    def get_gemini_api_keys(self, user_id: Any) -> Tuple[bool, List[str]]:
        """Lấy danh sách Gemini API Keys theo user_id"""
        try:
            if not user_id:
                return False, []
            
            identifier = str(user_id)
            params = {
                "device_id": f"eq.{identifier}",
                "select": "gemini_api_key",
                "limit": 1
            }
            success, data = self._make_request("GET", "user_gemini_keys", params=params)
            if not success:
                return False, []
            
            record = None
            if isinstance(data, list) and data:
                record = data[0]
            elif isinstance(data, dict) and data:
                record = data
            
            if record:
                raw_text = record.get("gemini_api_key", "")
                keys = [line.strip() for line in str(raw_text).splitlines() if line.strip()]
                return True, keys
            return True, []
        except Exception:
            return False, []
    
    def upsert_gemini_api_keys(self, user_id: Any, api_keys: List[str]) -> Tuple[bool, Dict]:
        """Lưu hoặc cập nhật danh sách Gemini API Keys cho user"""
        try:
            if not user_id:
                return False, {"error": "Missing user_id"}
            cleaned_keys = [k.strip() for k in api_keys if k and k.strip()]
            if not cleaned_keys:
                return False, {"error": "Missing api_keys"}
            
            now_iso = datetime.now().isoformat()
            identifier = str(user_id)
            params = {
                "device_id": f"eq.{identifier}",
                "select": "id",
                "limit": 1
            }
            success, data = self._make_request("GET", "user_gemini_keys", params=params)
            if not success:
                return False, data
            
            has_record = False
            if isinstance(data, list) and data:
                has_record = True
            elif isinstance(data, dict) and data:
                has_record = True
            
            if has_record:
                updates = {
                    "gemini_api_key": "\n".join(cleaned_keys),
                    "is_active": True,
                    "updated_at": now_iso,
                    "last_used_at": now_iso
                }
                return self._make_request(
                    "PATCH",
                    "user_gemini_keys",
                    updates,
                    params={"device_id": f"eq.{identifier}"}
                )
            else:
                insert_data = {
                    "device_id": identifier,
                    "gemini_api_key": "\n".join(cleaned_keys),
                    "is_active": True,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "last_used_at": now_iso
                }
                return self._make_request("POST", "user_gemini_keys", insert_data)
        except Exception as e:
            return False, {"error": str(e)}
    
    def _generate_device_fingerprint(self) -> str:
        """Tạo device fingerprint dựa trên thông tin máy"""
        try:
            import socket
            import platform
            import uuid as uuid_lib
            
            # Lấy thông tin máy
            hostname = socket.gethostname()
            platform_info = platform.platform()
            mac_address = ':'.join(['{:02x}'.format((uuid_lib.getnode() >> elements) & 0xff) 
                                   for elements in range(0,2*6,2)][::-1])
            
            # Tạo fingerprint
            device_info = f"{hostname}:{platform_info}:{mac_address}"
            device_fingerprint = hashlib.sha256(device_info.encode()).hexdigest()[:32]
            
            return device_fingerprint
            
        except Exception:
            # Fallback fingerprint
            return hashlib.sha256(f"fallback_{datetime.now().isoformat()}".encode()).hexdigest()[:32]
    
    def verify_password(self, password: str, stored_password: str) -> bool:
        """Kiểm tra password - DÙNG BCRYPT (database lưu hash)"""
        try:
            # Database lưu bcrypt hash
            # Check nếu password đã hash (bắt đầu với $2b$)
            if stored_password.startswith('$2b$') or stored_password.startswith('$2a$'):
                # Password đã hash, dùng bcrypt
                return bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8'))
            else:
                # Password plain text (fallback)
                return password == stored_password
        except:
            return False
    
    # ==================== SESSION MANAGEMENT ====================
    
    def create_session(self, user_id: int, device_id: str = None, force_login: bool = False) -> Tuple[bool, Dict]:
        """Tạo session mới cho user với device binding"""
        try:
            # Tạo device fingerprint nếu chưa có
            if not device_id:
                device_id = self._generate_device_fingerprint()
            
            # Kiểm tra xem user đã có session active trên thiết bị khác chưa
            existing_success, existing_sessions = self.check_existing_active_session(user_id)
            if existing_success and existing_sessions:
                existing_session = existing_sessions[0] if isinstance(existing_sessions, list) else existing_sessions
                existing_device = existing_session.get('device_fingerprint')
                
                # Nếu cùng device thì cho phép (re-login)
                if existing_device == device_id:
                    # Vô hiệu hóa session cũ trên cùng device
                    self.deactivate_user_sessions(user_id)
                else:
                    # Khác device và không force login thì từ chối
                    if not force_login:
                        return False, {
                            "error": "USER_ALREADY_LOGGED_IN",
                            "message": "Tài khoản đã đăng nhập trên thiết bị khác. Vui lòng đăng xuất thiết bị cũ trước.",
                            "existing_device": existing_device,
                            "current_device": device_id
                        }
                    else:
                        # Force login: vô hiệu hóa tất cả sessions
                        self.deactivate_user_sessions(user_id)
            
            session_token = str(uuid.uuid4())
            
            session_data = {
                "user_id": user_id,
                "session_token": session_token,
                "is_active": True,
                "device_fingerprint": device_id,
                "is_device_bound": True,
                "login_time": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            success, result = self._make_request("POST", "user_sessions", session_data)
            if success:
                # Cập nhật device_id trong bảng users
                self.update_user_device(user_id, device_id)
                # Cập nhật login_count cho user
                self.update_user_login_count(user_id)
                return True, {"session_token": session_token, "session_data": result, "device_id": device_id}
            return False, result
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def get_session(self, session_token: str) -> Tuple[bool, Dict]:
        """Lấy thông tin session"""
        params = {"session_token": f"eq.{session_token}", "is_active": "eq.true"}
        return self._make_request("GET", "user_sessions", params=params)
    
    def update_session_activity(self, session_token: str) -> Tuple[bool, Dict]:
        """Cập nhật last_activity của session"""
        params = {"session_token": f"eq.{session_token}"}
        updates = {"last_activity": datetime.now().isoformat(), "updated_at": datetime.now().isoformat()}
        return self._make_request("PATCH", "user_sessions", updates, params)
    
    def deactivate_session(self, session_token: str, logout_type: str = "manual") -> Tuple[bool, Dict]:
        """Vô hiệu hóa session với phân biệt loại logout"""
        params = {"session_token": f"eq.{session_token}"}
        
        # ✅ FIX: Deactivate session cho CẢ manual logout VÀ app_close
        # Để tránh lỗi "tài khoản đã đăng nhập thiết bị khác" khi đóng app bằng nút X hoặc tắt máy
        if logout_type == "manual" or logout_type == "app_close":
            updates = {
                "is_active": False,
                "logout_time": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            # Lấy thông tin session để biết user_id
            success, session_data = self.get_session(session_token)
            if success and session_data:
                session = session_data[0] if isinstance(session_data, list) else session_data
                user_id = session.get('user_id')
                if user_id:
                    # Cập nhật last_logout cho user
                    self.update_user(user_id, {"last_logout": datetime.now().isoformat()})
            
            return self._make_request("PATCH", "user_sessions", updates, params)
        else:
            # Các logout_type khác (nếu có): chỉ cập nhật last_activity, không deactivate
            updates = {
                "last_activity": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            return self._make_request("PATCH", "user_sessions", updates, params)
    
    def deactivate_user_sessions(self, user_id: int) -> Tuple[bool, Dict]:
        """Vô hiệu hóa tất cả sessions của user"""
        params = {"user_id": f"eq.{user_id}"}
        updates = {
            "is_active": False,
            "logout_time": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        return self._make_request("PATCH", "user_sessions", updates, params)
    
    def check_existing_active_session(self, user_id: int) -> Tuple[bool, Dict]:
        """Kiểm tra xem user có session active không"""
        params = {"user_id": f"eq.{user_id}", "is_active": "eq.true"}
        return self._make_request("GET", "user_sessions", params=params)
    
    # ==================== SUBSCRIPTION MANAGEMENT ====================
    
    def get_user_subscription(self, user_id: int) -> Tuple[bool, Dict]:
        """Lấy thông tin subscription của user"""
        try:
            params = {"user_id": f"eq.{user_id}"}
            success, result = self._make_request("GET", "user_subscriptions", params=params)
            
            # Debug log
            if not success:
                print(f"⚠️ get_user_subscription failed for user_id={user_id}: {result}")
            elif not result or (isinstance(result, list) and len(result) == 0):
                print(f"⚠️ No subscription found for user_id={user_id}")
            else:
                print(f"✅ Found subscription for user_id={user_id}: {len(result) if isinstance(result, list) else 1} record(s)")
            
            return success, result
        except Exception as e:
            print(f"❌ Error in get_user_subscription: {e}")
            return False, {"error": str(e)}
    
    def create_subscription(self, user_id: int, subscription_type: str, 
                          duration_days: int = None, max_videos_per_day: int = 5,
                          max_videos_per_month: int = 100, features_allowed: Dict = None) -> Tuple[bool, Dict]:
        """Tạo subscription mới"""
        try:
            end_date = None
            if duration_days:
                end_date = (datetime.now() + timedelta(days=duration_days)).isoformat()
            
            subscription_data = {
                "user_id": user_id,
                "subscription_type": subscription_type,
                "start_date": datetime.now().isoformat(),
                "end_date": end_date,
                "is_active": True,
                "max_videos_per_day": max_videos_per_day,
                "max_videos_per_month": max_videos_per_month,
                "features_allowed": json.dumps(features_allowed) if features_allowed else None,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            return self._make_request("POST", "user_subscriptions", subscription_data)
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def update_subscription(self, user_id: int, updates: Dict) -> Tuple[bool, Dict]:
        """Cập nhật subscription"""
        params = {"user_id": f"eq.{user_id}"}
        updates["updated_at"] = datetime.now().isoformat()
        return self._make_request("PATCH", "user_subscriptions", updates, params)
    
    def extend_subscription(self, user_id: int, extend_days: int) -> Tuple[bool, Dict]:
        """Gia hạn subscription"""
        try:
            # Lấy subscription hiện tại
            success, sub_data = self.get_user_subscription(user_id)
            if not success or not sub_data:
                return False, {"error": "Subscription not found"}
            
            current_sub = sub_data[0] if isinstance(sub_data, list) and sub_data else sub_data
            
            # Tính end_date mới
            if current_sub.get('end_date'):
                current_end = datetime.fromisoformat(current_sub['end_date'].replace('Z', ''))
                if current_end > datetime.now():
                    new_end_date = current_end + timedelta(days=extend_days)
                else:
                    new_end_date = datetime.now() + timedelta(days=extend_days)
            else:
                new_end_date = datetime.now() + timedelta(days=extend_days)
            
            updates = {
                "end_date": new_end_date.isoformat(),
                "is_active": True
            }
            
            return self.update_subscription(user_id, updates)
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def check_subscription_validity(self, user_id: int) -> Tuple[bool, Dict]:
        """Kiểm tra tính hợp lệ của subscription - check end_date"""
        try:
            success, sub_data = self.get_user_subscription(user_id)
            
            # ✅ Kiểm tra kỹ: sub_data có thể là empty list [], None, hoặc dict rỗng
            if not success:
                return False, {"error": "No subscription found", "is_expired": True}
            
            # Kiểm tra sub_data có dữ liệu không
            if not sub_data:
                return False, {"error": "No subscription found", "is_expired": True}
            
            # Nếu là list, kiểm tra có phần tử không
            if isinstance(sub_data, list):
                if len(sub_data) == 0:
                    return False, {"error": "No subscription found", "is_expired": True}
                subscription = sub_data[0]
            else:
                # Nếu là dict, dùng trực tiếp
                subscription = sub_data
            
            # Kiểm tra subscription có active không
            if not subscription.get('is_active', False):
                return False, {"error": "Subscription is inactive", "is_expired": True}
            
            # Kiểm tra end_date
            end_date_str = subscription.get('end_date')
            # ✅ Xử lý trường hợp end_date = null (vĩnh viễn)
            # Kiểm tra None, empty string, hoặc string "null"
            if not end_date_str or end_date_str == "null" or str(end_date_str).lower() == "none":
                # Không có end_date = subscription vĩnh viễn
                return True, {
                    "is_expired": False, 
                    "days_remaining": 999999, 
                    "hours_remaining": 0,
                    "subscription": subscription,
                    "is_lifetime": True  # Đánh dấu là subscription vĩnh viễn
                }
            
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))
                now = datetime.now()
                
                if end_date <= now:
                    # Đã hết hạn
                    self.update_subscription(user_id, {"is_active": False})
                    return False, {"error": "Subscription expired", "is_expired": True, "expired_date": end_date_str}
                else:
                    # Còn hạn
                    time_diff = end_date - now
                    days_remaining = time_diff.days
                    hours_remaining = time_diff.seconds // 3600
                    
                    return True, {
                        "is_expired": False, 
                        "days_remaining": days_remaining,
                        "hours_remaining": hours_remaining,
                        "end_date": end_date_str,
                        "subscription": subscription
                    }
                    
            except Exception as date_error:
                # Lỗi parse date
                return False, {"error": f"Invalid end_date format: {date_error}", "is_expired": True}
                
        except Exception as e:
            return False, {"error": str(e), "is_expired": True}
    
    def get_user_id_from_session(self, session_token: str) -> Optional[int]:
        """Lấy user_id từ session token"""
        try:
            success, session_data = self.get_session(session_token)
            if success and session_data:
                session = session_data[0] if isinstance(session_data, list) and session_data else session_data
                return session.get('user_id')
            return None
        except Exception:
            return None
    
    # ==================== API KEYS MANAGEMENT ====================
    
    def get_user_api_keys(self, user_id: int, api_provider: str) -> Tuple[bool, Dict]:
        """Lấy API keys của user theo provider"""
        params = {
            "user_id": f"eq.{user_id}",
            "api_provider": f"eq.{api_provider}",
            "is_active": "eq.true"
        }
        return self._make_request("GET", "user_api_keys", params=params)
    
    def add_api_key(self, user_id: int, api_provider: str, api_key: str, 
                   credit_limit: int = 0, notes: str = "") -> Tuple[bool, Dict]:
        """Thêm API key mới"""
        try:
            api_key_data = {
                "user_id": user_id,
                "api_provider": api_provider,
                "api_key": api_key,
                "credit_limit": credit_limit,
                "credit_remaining": credit_limit,
                "is_active": True,
                "notes": notes,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            return self._make_request("POST", "user_api_keys", api_key_data)
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def update_api_key_credit(self, api_key_id: int, credit_used: int) -> Tuple[bool, Dict]:
        """Cập nhật credit của API key"""
        params = {"id": f"eq.{api_key_id}"}
        
        # Lấy thông tin API key hiện tại
        success, api_key_data = self._make_request("GET", "user_api_keys", params=params)
        if not success or not api_key_data:
            return False, {"error": "API key not found"}
        
        current_key = api_key_data[0] if isinstance(api_key_data, list) and api_key_data else api_key_data
        current_credit = current_key.get('credit_remaining', 0)
        
        updates = {
            "credit_remaining": max(0, current_credit - credit_used),
            "last_used": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        return self._make_request("PATCH", "user_api_keys", updates, params)
    
    def deactivate_api_key(self, api_key_id: int) -> Tuple[bool, Dict]:
        """Vô hiệu hóa API key"""
        params = {"id": f"eq.{api_key_id}"}
        updates = {
            "is_active": False,
            "updated_at": datetime.now().isoformat()
        }
        return self._make_request("PATCH", "user_api_keys", updates, params)
    
    # ==================== USAGE LOGS ====================
    
    def log_video_usage(self, user_id: int, videos_count: int = 1, feature_used: str = "video_generation") -> Tuple[bool, Dict]:
        """Ghi log sử dụng video"""
        try:
            today = datetime.now().date().isoformat()
            
            # Kiểm tra xem đã có log hôm nay chưa
            params = {
                "user_id": f"eq.{user_id}",
                "usage_date": f"eq.{today}",
                "feature_used": f"eq.{feature_used}"
            }
            
            success, existing_log = self._make_request("GET", "user_usage_logs", params=params)
            
            if success and existing_log:
                # Update existing log
                current_log = existing_log[0] if isinstance(existing_log, list) else existing_log
                new_count = current_log.get('videos_generated', 0) + videos_count
                
                updates = {
                    "videos_generated": new_count,
                    "updated_at": datetime.now().isoformat()
                }
                
                log_params = {"id": f"eq.{current_log['id']}"}
                return self._make_request("PATCH", "user_usage_logs", updates, log_params)
            else:
                # Create new log
                log_data = {
                    "user_id": user_id,
                    "usage_date": today,
                    "videos_generated": videos_count,
                    "feature_used": feature_used,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                
                return self._make_request("POST", "user_usage_logs", log_data)
                
        except Exception as e:
            return False, {"error": str(e)}
    
    def get_user_usage_today(self, user_id: int) -> Tuple[bool, Dict]:
        """Lấy usage của user hôm nay"""
        today = datetime.now().date().isoformat()
        params = {
            "user_id": f"eq.{user_id}",
            "usage_date": f"eq.{today}"
        }
        return self._make_request("GET", "user_usage_logs", params=params)
    
    # ==================== AUTHENTICATION METHODS ====================
    
    def authenticate_user(self, username: str, password: str, force_login: bool = False, machine_code: str = None) -> Tuple[bool, str, Dict]:
        """Xác thực user và tạo session - BẮT BUỘC MÃ MÁY CỐ ĐỊNH"""
        try:
            # Lấy thông tin user
            success, user_data = self.get_user_by_username(username)
            
            if not success or not user_data:
                return False, "Tên đăng nhập hoặc mật khẩu không đúng", {}
            
            user = user_data[0] if isinstance(user_data, list) and user_data else user_data
            
            # Kiểm tra password
            if not self.verify_password(password, user['password']):
                return False, "Tên đăng nhập hoặc mật khẩu không đúng", {}
            
            # ==================== MACHINE CODE CHECK (MÃ MÁY CỐ ĐỊNH) ====================
            # Mã máy do client hiển thị (từ phần cứng) và user gửi cho admin để gắn vào tài khoản
            machine_code = (machine_code or "").strip() if isinstance(machine_code, str) else ""
            if not machine_code:
                return False, "Thiếu mã máy. Vui lòng nhập mã máy hiển thị trong ứng dụng.", {
                    "error_code": "MISSING_MACHINE_CODE"
                }
            
            # Lấy machine_code đã được admin gắn trong cột device_id (đây là cột dành riêng cho mã máy)
            registered_machine_code = str(user.get('device_id') or "").strip()
            
            if not registered_machine_code:
                # Tài khoản chưa được gắn mã máy trên server
                return False, (
                "Tài khoản chưa được gắn mã máy (device_id).\n"
                "Vui lòng gửi mã máy cho admin để kích hoạt trước khi đăng nhập."
                ), {
                    "error_code": "MACHINE_NOT_REGISTERED"
                }
            
            if machine_code != registered_machine_code:
                # Mã máy không khớp → không cho login
                return False, (
                    "Mã máy không khớp với tài khoản.\n"
                    "Vui lòng kiểm tra lại hoặc liên hệ admin để cập nhật."
                ), {
                    "error_code": "MACHINE_CODE_MISMATCH"
                }
            
            # Kiểm tra tính hợp lệ của subscription TRƯỚC KHI tạo session
            sub_valid, sub_info = self.check_subscription_validity(user['id'])
            
            if not sub_valid:
                # Subscription đã hết hạn hoặc không hợp lệ
                error_msg = sub_info.get('error', 'Subscription expired')
                if 'expired' in error_msg.lower():
                    return False, "Gói dịch vụ đã hết hạn. Vui lòng gia hạn để tiếp tục sử dụng.", {
                        "error_code": "SUBSCRIPTION_EXPIRED",
                        "expired_date": sub_info.get('expired_date')
                    }
                else:
                    return False, f"Gói dịch vụ không hợp lệ: {error_msg}", {
                        "error_code": "SUBSCRIPTION_INVALID"
                    }
            
            # Subscription hợp lệ, lấy thông tin
            subscription_info = {
                "subscription_type": "free",
                "is_active": True,
                "end_date": None,
                "start_date": None,
                "max_videos_per_day": 5,
                "max_videos_per_month": 100,
                "features_allowed": None,
                "days_remaining": sub_info.get('days_remaining', None),
                "vps_token_enabled": False,  # ✅ Mặc định False
            }
            
            # Cập nhật với thông tin từ database
            if sub_info.get('subscription'):
                sub = sub_info['subscription']
                subscription_info.update({
                    "subscription_type": sub.get('subscription_type', 'free'),
                    "is_active": sub.get('is_active', True),
                    "start_date": sub.get('start_date'),
                    "end_date": sub.get('end_date'),
                    "max_videos_per_day": sub.get('max_videos_per_day', 5),
                    "max_videos_per_month": sub.get('max_videos_per_month', 100),
                    "features_allowed": sub.get('features_allowed'),
                    "days_remaining": sub_info.get('days_remaining'),
                    "vps_token_enabled": sub.get('vps_token_enabled', False),  # ✅ Lấy từ DB
                })
            
            plan_key = normalize_subscription_type(subscription_info.get("subscription_type"))
            subscription_info["subscription_type"] = plan_key
            subscription_info["limits"] = get_subscription_limits(plan_key)
            
            plan_key = normalize_subscription_type(subscription_info.get("subscription_type"))
            subscription_info["subscription_type"] = plan_key
            subscription_info["limits"] = get_subscription_limits(plan_key)
            
            # Lấy usage hôm nay
            usage_success, usage_data = self.get_user_usage_today(user['id'])
            videos_today = 0
            if usage_success and usage_data:
                usage = usage_data[0] if isinstance(usage_data, list) and usage_data else usage_data
                videos_today = usage.get('videos_generated', 0)
            
            # Tạo session với device binding - sử dụng chính machine_code làm device_fingerprint
            session_success, session_result = self.create_session(user['id'], device_id=machine_code, force_login=force_login)
            if not session_success:
                error_info = session_result.get('error', 'Unknown error')
                if error_info == "USER_ALREADY_LOGGED_IN":
                    return False, session_result.get('message', 'User already logged in'), {
                        "error_code": "USER_ALREADY_LOGGED_IN",
                        "can_force_login": True,
                        "existing_device": session_result.get('existing_device'),
                        "current_device": session_result.get('current_device')
                    }
                return False, "Không thể tạo session", {}
            
            return True, "Đăng nhập thành công", {
                "user": {
                    "id": user['id'],
                    "username": user['username'],
                    "role": user.get('role', 'tool'),
                    "login_count": user.get('login_count', 0),
                    "device_id": session_result.get('device_id'),
                    "last_device_change": user.get('last_device_change')
                },
                "subscription": subscription_info,
                "usage": {
                    "videos_today": videos_today
                },
                "session_token": session_result['session_token'],
                "device_id": session_result.get('device_id')
            }
            
        except Exception as e:
            return False, f"Lỗi hệ thống: {str(e)}", {}
    
    def check_session_validity(self, session_token: str) -> Tuple[bool, Dict]:
        """Kiểm tra tính hợp lệ của session và subscription"""
        try:
            success, session_data = self.get_session(session_token)
            
            if not success or not session_data:
                return False, {"error": "Session không tồn tại hoặc đã hết hạn"}
            
            session = session_data[0] if isinstance(session_data, list) and session_data else session_data
            user_id = session['user_id']
            
            # Lấy thông tin user
            user_success, user_data = self.get_user_by_id(user_id)
            
            if not user_success or not user_data:
                return False, {"error": "User không tồn tại"}
            
            user = user_data[0] if isinstance(user_data, list) and user_data else user_data
            
            # KIỂM TRA SUBSCRIPTION VALIDITY (quan trọng!)
            sub_valid, sub_info = self.check_subscription_validity(user_id)
            
            if not sub_valid:
                # Subscription đã hết hạn - deactivate session luôn
                self.deactivate_session(session_token, "subscription_expired")
                error_msg = sub_info.get('error', 'Subscription expired')
                if 'expired' in error_msg.lower():
                    return False, {
                        "error": "Gói dịch vụ đã hết hạn",
                        "error_code": "SUBSCRIPTION_EXPIRED",
                        "expired_date": sub_info.get('expired_date')
                    }
                else:
                    return False, {
                        "error": f"Gói dịch vụ không hợp lệ: {error_msg}",
                        "error_code": "SUBSCRIPTION_INVALID"
                    }
            
            # Subscription hợp lệ, tạo subscription info
            subscription_info = {
                "subscription_type": "free",
                "is_active": True,
                "end_date": None,
                "start_date": None,
                "max_videos_per_day": 5,
                "max_videos_per_month": 100,
                "features_allowed": None,
                "days_remaining": sub_info.get('days_remaining', None),
                "vps_token_enabled": False,  # ✅ Mặc định False
            }
            
            # Cập nhật với thông tin từ database
            if sub_info.get('subscription'):
                sub = sub_info['subscription']
                subscription_info.update({
                    "subscription_type": sub.get('subscription_type', 'free'),
                    "is_active": sub.get('is_active', True),
                    "start_date": sub.get('start_date'),
                    "end_date": sub.get('end_date'),
                    "max_videos_per_day": sub.get('max_videos_per_day', 5),
                    "max_videos_per_month": sub.get('max_videos_per_month', 100),
                    "features_allowed": sub.get('features_allowed'),
                    "days_remaining": sub_info.get('days_remaining'),
                    "vps_token_enabled": sub.get('vps_token_enabled', False),  # ✅ Lấy từ DB
                })
            
            # Lấy usage hôm nay
            usage_success, usage_data = self.get_user_usage_today(user_id)
            videos_today = 0
            if usage_success and usage_data:
                usage = usage_data[0] if isinstance(usage_data, list) and usage_data else usage_data
                videos_today = usage.get('videos_generated', 0)
            
            # Cập nhật last_activity
            self.update_session_activity(session_token)
            
            result = {
                "username": user['username'],
                "user_id": user_id,  # Thêm user_id để dùng cho background monitoring
                "subscription": subscription_info,
                "usage": {
                    "videos_today": videos_today
                }
            }
            
            return True, result
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def logout_user(self, session_token: str, logout_type: str = "manual") -> Tuple[bool, str]:
        """Đăng xuất user với phân biệt loại logout"""
        try:
            success, result = self.deactivate_session(session_token, logout_type)
            if success:
                if logout_type == "manual":
                    return True, "Đăng xuất thành công"
                else:
                    return True, "Phiên làm việc đã kết thúc"
            else:
                return False, "Lỗi khi đăng xuất"
        except Exception as e:
            return False, f"Lỗi hệ thống: {str(e)}"
    
    # ==================== COOKIES MANAGEMENT (CHO USER ULTRA) ====================
    
    def get_user_cookies(self, user_id: int) -> Tuple[bool, Dict]:
        """Lấy cookies từ server cho user Ultra - hỗ trợ multi-cookie"""
        try:
            params = {"user_id": f"eq.{user_id}", "is_active": "eq.true", "order": "created_at.desc"}  # Lấy tất cả cookies active
            return self._make_request("GET", "cookies_table", params=params)
        except Exception as e:
            return False, {"error": str(e)}
    
    def update_user_cookies(self, user_id: int, cookies_json: str) -> Tuple[bool, Dict]:
        """Cập nhật cookies cho user Ultra"""
        try:
            # Always insert new record (không update existing)
            # Để admin có thể track history
            cookie_data = {
                "user_id": user_id,
                "cookies": cookies_json,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            return self._make_request("POST", "cookies_table", cookie_data)
                
        except Exception as e:
            return False, {"error": str(e)}
    
    def convert_json_cookies_to_header_string(self, cookies_json: str) -> str:
        """Convert JSON cookie format thành header string format"""
        try:
            import json
            
            if isinstance(cookies_json, str):
                cookies_list = json.loads(cookies_json)
            else:
                cookies_list = cookies_json
            
            if not isinstance(cookies_list, list):
                return ""
            
            # Convert to "name=value; name2=value2" format
            cookie_pairs = []
            for cookie in cookies_list:
                if isinstance(cookie, dict):
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    if name and value:
                        cookie_pairs.append(f"{name}={value}")
            
            return "; ".join(cookie_pairs)
            
        except Exception as e:
            print(f"Error converting cookies: {e}")
            return ""
    
    def convert_multi_cookies_to_header_strings(self, cookies_data: List[Dict]) -> List[str]:
        """Convert multiple cookie records thành list of header strings"""
        try:
            header_strings = []
            
            for cookie_record in cookies_data:
                cookies_json = cookie_record.get('cookies', '')
                if cookies_json:
                    header_string = self.convert_json_cookies_to_header_string(cookies_json)
                    if header_string:
                        header_strings.append(header_string)
            
            return header_strings
            
        except Exception as e:
            print(f"Error converting multi-cookies: {e}")
            return []
    
    # ==================== ACTIVATION KEY AUTHENTICATION ====================
    
    def get_activation_key(self, key: str) -> Tuple[bool, Dict]:
        """Lấy thông tin activation key từ database"""
        try:
            params = {"activation_key": f"eq.{key}", "select": "*"}
            return self._make_request("GET", "activation_keys", params=params)
        except Exception as e:
            return False, {"error": str(e)}
    
    def authenticate_with_key(self, activation_key: str, machine_code: str) -> Tuple[bool, str, Dict]:
        """
        Xác thực bằng activation key
        - Nếu key chưa dùng: gán machine_code và cho phép login
        - Nếu key đã dùng: check machine_code khớp không
        - Check end_date còn hạn không
        """
        try:
            if not activation_key or not machine_code:
                return False, "Vui lòng nhập đầy đủ key và mã máy", {"error_code": "MISSING_INPUT"}
            
            # Lấy thông tin key từ database
            success, key_data = self.get_activation_key(activation_key)
            
            if not success:
                return False, "Lỗi kết nối server", {"error_code": "CONNECTION_ERROR"}
            
            if not key_data or (isinstance(key_data, list) and len(key_data) == 0):
                return False, "Key không tồn tại hoặc không hợp lệ", {"error_code": "KEY_NOT_FOUND"}
            
            key_info = key_data[0] if isinstance(key_data, list) else key_data
            
            # Check key is_active
            if not key_info.get('is_active', False):
                return False, "Key đã bị vô hiệu hóa", {"error_code": "KEY_INACTIVE"}
            
            # Check end_date
            end_date_str = key_info.get('end_date')
            is_lifetime = (not end_date_str or end_date_str == "null" or str(end_date_str).lower() == "none")
            
            if not is_lifetime:
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))
                    if end_date <= datetime.now():
                        # Key đã hết hạn - deactivate
                        self._update_activation_key(key_info['id'], {"is_active": False})
                        return False, "Key đã hết hạn sử dụng", {"error_code": "KEY_EXPIRED", "expired_date": end_date_str}
                except Exception as e:
                    print(f"Error parsing end_date: {e}")
            
            # Check machine_code binding
            stored_machine_code = key_info.get('machine_code')
            
            if stored_machine_code:
                # Key đã được bind với machine_code - check khớp không
                if stored_machine_code != machine_code:
                    return False, "Key đã được sử dụng trên thiết bị khác", {"error_code": "MACHINE_MISMATCH"}
            else:
                # Key chưa bind - bind machine_code lần đầu
                bind_success = self._bind_machine_code_to_key(key_info['id'], machine_code)
                if not bind_success:
                    return False, "Không thể gán mã máy cho key", {"error_code": "BIND_FAILED"}
            
            # Check usage limit
            max_usage = key_info.get('max_usage', 1)
            usage_count = key_info.get('usage_count', 0)
            
            if max_usage > 0 and usage_count >= max_usage:
                # Nếu đã bind machine_code khớp thì vẫn cho login
                if stored_machine_code == machine_code:
                    pass  # OK - cùng máy, cho phép login
                else:
                    return False, "Key đã đạt giới hạn sử dụng", {"error_code": "USAGE_LIMIT"}
            
            # ✅ LOGIN THÀNH CÔNG - Cập nhật thông tin
            self._update_key_login(key_info['id'])
            
            # Tính days_remaining
            days_remaining = None
            if not is_lifetime and end_date_str:
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))
                    time_diff = end_date - datetime.now()
                    days_remaining = max(0, time_diff.days)
                except:
                    days_remaining = 999999
            else:
                days_remaining = 999999  # Lifetime
            
            # Normalize subscription type
            plan_key = normalize_subscription_type(key_info.get('subscription_type', 'free'))
            
            # Tạo response data giống như login bằng user/password
            response_data = {
                "user": {
                    "id": key_info['id'],  # Dùng key id làm user id
                    "username": key_info.get('key_name') or f"Key-{activation_key[:8]}",
                    "role": "key_user",
                    "login_count": key_info.get('usage_count', 0) + 1,
                    "device_id": machine_code,
                    "is_key_login": True  # Flag đặc biệt
                },
                "subscription": {
                    "subscription_type": plan_key,
                    "is_active": True,
                    "start_date": key_info.get('start_date'),
                    "end_date": end_date_str,
                    "max_videos_per_day": key_info.get('max_videos_per_day', 10),
                    "max_videos_per_month": key_info.get('max_videos_per_month', 300),
                    "features_allowed": key_info.get('features_allowed'),
                    "days_remaining": days_remaining,
                    "is_lifetime": is_lifetime,
                    "limits": get_subscription_limits(plan_key)
                },
                "usage": {
                    "videos_today": 0  # TODO: Track usage per key
                },
                "session_token": f"key_{activation_key}_{machine_code[:8]}",  # Pseudo session
                "device_id": machine_code,
                "key_info": {
                    "key_id": key_info['id'],
                    "activation_key": activation_key,
                    "key_name": key_info.get('key_name')
                }
            }
            
            return True, "Đăng nhập bằng key thành công", response_data
            
        except Exception as e:
            print(f"Error in authenticate_with_key: {e}")
            return False, f"Lỗi hệ thống: {str(e)}", {"error_code": "SYSTEM_ERROR"}
    
    def _bind_machine_code_to_key(self, key_id: int, machine_code: str) -> bool:
        """Gán machine_code cho key lần đầu sử dụng"""
        try:
            updates = {
                "machine_code": machine_code,
                "is_used": True,
                "updated_at": datetime.now().isoformat()
            }
            success, _ = self._update_activation_key(key_id, updates)
            return success
        except Exception as e:
            print(f"Error binding machine_code: {e}")
            return False
    
    def _update_key_login(self, key_id: int) -> bool:
        """Cập nhật thông tin login cho key"""
        try:
            # Lấy usage_count hiện tại
            success, key_data = self._make_request("GET", "activation_keys", params={"id": f"eq.{key_id}"})
            current_usage = 0
            if success and key_data:
                key_info = key_data[0] if isinstance(key_data, list) else key_data
                current_usage = key_info.get('usage_count', 0)
            
            updates = {
                "usage_count": current_usage + 1,
                "last_login": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            success, _ = self._update_activation_key(key_id, updates)
            return success
        except Exception as e:
            print(f"Error updating key login: {e}")
            return False
    
    def _update_activation_key(self, key_id: int, updates: Dict) -> Tuple[bool, Dict]:
        """Cập nhật activation key"""
        params = {"id": f"eq.{key_id}"}
        return self._make_request("PATCH", "activation_keys", updates, params)
    
    def check_key_validity(self, activation_key: str, machine_code: str) -> Tuple[bool, Dict]:
        """Kiểm tra tính hợp lệ của key (dùng cho background monitoring)"""
        try:
            success, key_data = self.get_activation_key(activation_key)
            
            if not success or not key_data or (isinstance(key_data, list) and len(key_data) == 0):
                return False, {"error": "Key not found", "is_expired": True}
            
            key_info = key_data[0] if isinstance(key_data, list) else key_data
            
            # Check is_active
            if not key_info.get('is_active', False):
                return False, {"error": "Key inactive", "is_expired": True}
            
            # Check machine_code
            stored_machine = key_info.get('machine_code')
            if stored_machine and stored_machine != machine_code:
                return False, {"error": "Machine mismatch", "is_expired": True}
            
            # Check end_date
            end_date_str = key_info.get('end_date')
            is_lifetime = (not end_date_str or end_date_str == "null" or str(end_date_str).lower() == "none")
            
            if is_lifetime:
                return True, {
                    "is_expired": False,
                    "days_remaining": 999999,
                    "is_lifetime": True,
                    "key_info": key_info
                }
            
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))
                now = datetime.now()
                
                if end_date <= now:
                    self._update_activation_key(key_info['id'], {"is_active": False})
                    return False, {"error": "Key expired", "is_expired": True, "expired_date": end_date_str}
                else:
                    time_diff = end_date - now
                    days_remaining = time_diff.days
                    hours_remaining = time_diff.seconds // 3600
                    
                    return True, {
                        "is_expired": False,
                        "days_remaining": days_remaining,
                        "hours_remaining": hours_remaining,
                        "end_date": end_date_str,
                        "key_info": key_info
                    }
            except Exception as e:
                return False, {"error": f"Invalid date format: {e}", "is_expired": True}
                
        except Exception as e:
            return False, {"error": str(e), "is_expired": True}


# Global instance
supabase_manager = SupabaseManager()

# Wrapper functions for backward compatibility
def authenticate_iting_user(username: str, password: str, force_login: bool = False, machine_code: str = None) -> Tuple[bool, str, Dict]:
    """Wrapper function cho ItingAPI / GUI - thêm tham số machine_code"""
    return supabase_manager.authenticate_user(username, password, force_login, machine_code)

def check_iting_session(session_token: str = None) -> Tuple[bool, Dict]:
    """Wrapper function for backward compatibility"""
    try:
        # Nếu không có session_token, thử load từ file
        if not session_token:
            try:
                from iting_api import ItingAPI
                api = ItingAPI()
                session_token = api.load_auth_token()
            except:
                pass
        
        if not session_token:
            return False, {"error": "No session token provided"}
        
        return supabase_manager.check_session_validity(session_token)
    
    except Exception as e:
        print(f"Error in check_iting_session: {e}")
        return False, {"error": f"Connection error: {str(e)}"}

# logout_iting_user được define trong iting_api.py để tránh circular import
# Không define ở đây nữa

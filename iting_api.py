#!/usr/bin/env python3
"""
Iting API Client - Xử lý authentication và session management
Tích hợp với Supabase để quản lý user, subscription, API keys

Features:
- User authentication với bcrypt
- Session management với device binding
- Subscription và usage tracking
- API key management với rotation
- Machine token generation với JWT

Author: mavanhuy30
"""

import requests
import json
import os
import time
import socket
import hashlib
import hmac
import base64
import jwt
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from supabase_manager import supabase_manager


class ItingAPI:
    def __init__(self):
        """Initialize ItingGroup API client với Supabase"""
        # Load cấu hình từ file
        self.config = self.load_api_config()

        # App info
        app_info = self.config.get("app_info", {})
        self.app_name = app_info.get("name", "ItingGroup Translator")
        self.app_version = app_info.get("version", "1.0.0")
        self.device_type = app_info.get("device_type", "desktop_app")

        # Development settings
        dev_config = self.config.get("development", {})
        self.demo_mode = dev_config.get("demo_mode", False)
        self.debug_api = dev_config.get("debug_api_calls", True)
        self.mock_responses = dev_config.get("mock_responses", True)
        self.offline_mode = False  # Will be set to True if Supabase is not available

        self.session = requests.Session()
        
        # JWT Secret key cố định trong code (thay đổi này để bảo mật)
        self.JWT_SECRET = "ItingGroup_2025_SecretKey_V1_DoNotShare"

        # Supabase manager
        self.supabase = supabase_manager
    
    def _get_machine_secret(self) -> str:
        """Tạo machine secret dựa trên hardware info - CỐ ĐỊNH CHO MỖI MÁY (chỉ Windows)"""
        try:
            # Secret key riêng
            secret_key = 'mvh30102002'
            
            # Lấy Windows Machine GUID từ Registry (cố định)
            machine_id = None
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography"
                )
                machine_id = winreg.QueryValueEx(key, "MachineGuid")[0]
                winreg.CloseKey(key)
            except:
                pass    
            
            # Fallback 1: lấy tên máy (Computer Name) nếu không lấy được machine GUID
            if not machine_id:
                try:
                    # Lấy tên máy từ environment variable
                    machine_id = os.environ.get('COMPUTERNAME', '')
                    if not machine_id:
                        # Hoặc lấy từ Registry
                        import winreg
                        key = winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\ComputerName\ComputerName"
                        )
                        machine_id = winreg.QueryValueEx(key, "ComputerName")[0]
                        winreg.CloseKey(key)
                except:
                    machine_id = None
            
            # Fallback 2: lấy CPU Processor ID nếu vẫn không có
            if not machine_id:
                try:
                    import subprocess
                    result = subprocess.run(
                        ['wmic', 'cpu', 'get', 'ProcessorId', '/value'],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if 'ProcessorId=' in line:
                                cpu_id = line.split('=')[1].strip()
                                if cpu_id and cpu_id != '':
                                    machine_id = cpu_id
                                    break
                except:
                    machine_id = None
            
            # Fallback cuối cùng
            if not machine_id:
                machine_id = "UNKNOWN"
            
            # Tạo machine fingerprint: machine_id + device_type + secret_key
            machine_info = f"{machine_id}:{self.device_type}:{secret_key}"
            
            # Hash để tạo secret
            secret = hashlib.sha256(machine_info.encode()).hexdigest()[:32]
            return secret
            
        except Exception as e:
            # Fallback secret nếu không lấy được hardware info
            return hashlib.sha256(f"fallback_secret_{self.app_name}:mvh30102002".encode()).hexdigest()[:32]
    
    def _create_machine_token(self, user_id: int, username: str, subscription: Dict = None) -> str:
        """Tạo machine token với JWT"""
        try:
            now = datetime.utcnow()
            payload = {
                'user_id': user_id,
                'username': username,
                'app_name': self.app_name,
                'app_version': self.app_version,
                'device_type': self.device_type,
                'machine_secret': self._get_machine_secret(),
                'subscription': subscription or {},
                'iat': now,
                'exp': now + timedelta(hours=24),  # Token hết hạn sau 24h
                'iss': 'ItingGroup',
                'aud': self.app_name
            }
            
            token = jwt.encode(payload, self.JWT_SECRET, algorithm='HS256')
            return token
            
        except Exception as e:
            print(f"Error creating machine token: {e}")
            return ""
    
    def _validate_machine_token(self, token: str) -> Tuple[bool, Dict]:
        """Validate machine token"""
        try:
            if not token:
                return False, {"error": "No token provided"}
            
            # Decode JWT
            payload = jwt.decode(token, self.JWT_SECRET, algorithms=['HS256'])
            
            # Kiểm tra machine secret
            current_secret = self._get_machine_secret()
            token_secret = payload.get('machine_secret', '')
            
            if current_secret != token_secret:
                return False, {"error": "Machine mismatch"}
            
            # Kiểm tra app info
            if payload.get('app_name') != self.app_name:
                return False, {"error": "App mismatch"}
            
            return True, payload
            
        except jwt.ExpiredSignatureError:
            return False, {"error": "Token expired"}
        except jwt.InvalidTokenError as e:
            return False, {"error": f"Invalid token: {str(e)}"}
        except Exception as e:
            return False, {"error": f"Token validation error: {str(e)}"}

    def load_api_config(self) -> Dict:
        """Load API configuration từ file hoặc environment"""
        config = {
            "app_info": {
                "name": "Google Labs Flow Video Generator",
                "version": "1.0.0",
                "device_type": "desktop_app"
            },
            "development": {
                "demo_mode": False,
                "debug_api_calls": True,
                "mock_responses": False
            }
        }
        
        # Thử load từ file config.json
        try:
            config_file = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                    config.update(file_config)
        except Exception as e:
            print(f"Warning: Could not load config file: {e}")
        
        return config

    def activate_with_key(self, key: str, device_id: str) -> Tuple[bool, Dict]:
        """Activate với activation key - placeholder for future implementation"""
        # TODO: Implement activation key logic with Supabase
        return False, {"error": "Activation key not implemented yet"}

    def login(self, username: str, password: str, machine_code: str, force_login: bool = False) -> Tuple[bool, Dict]:
        """Đăng nhập user với Supabase - BẮT BUỘC MÃ MÁY CỐ ĐỊNH"""
        try:
            if self.debug_api:
                print(f"🔐 Attempting login for user: {username} (force: {force_login}) with machine_code={machine_code}")
            
            # Sử dụng Supabase để authenticate (truyền cả machine_code)
            success, message, data = self.supabase.authenticate_user(username, password, force_login, machine_code)
            
            if success:
                # Tạo machine token
                user_info = data.get('user', {})
                subscription_info = data.get('subscription', {})
                
                machine_token = self._create_machine_token(
                    user_info.get('id'),
                    user_info.get('username'),
                    subscription_info
                )
                
                # Lưu session token
                session_token = data.get('session_token')
                if session_token:
                    self.save_auth_token(session_token)
                
                response_data = {
                            "success": True,
                    "message": message,
                    "user": user_info,
                    "subscription": subscription_info,
                    "usage": data.get('usage', {}),
                    "session_token": session_token,
                    "machine_token": machine_token,
                    "device_id": data.get('device_id')
                }
                
                if self.debug_api:
                    print(f"✅ Login successful for {username}")
                
                return True, response_data
            else:
                if self.debug_api:
                    print(f"❌ Login failed for {username}: {message}")
                
                # Kiểm tra error codes khác nhau
                error_code = data.get('error_code', 'LOGIN_FAILED')
                response_data = {
                    "success": False,
                    "error": message,
                    "error_code": error_code
                }
                
                # Thêm thông tin device nếu có
                if error_code == "USER_ALREADY_LOGGED_IN":
                    response_data.update({
                        "can_force_login": data.get('can_force_login', False),
                        "existing_device": data.get('existing_device'),
                        "current_device": data.get('current_device')
                    })
                
                # Thêm thông tin subscription nếu hết hạn
                if error_code in ["SUBSCRIPTION_EXPIRED", "SUBSCRIPTION_INVALID"]:
                    response_data.update({
                        "expired_date": data.get('expired_date'),
                        "subscription_error": True
                    })
                
                return False, response_data
                
        except Exception as e:
            error_msg = f"Login error: {str(e)}"
            if self.debug_api:
                print(f"❌ {error_msg}")
            
                return False, {
                    "success": False,
                "error": error_msg,
                "error_code": "SYSTEM_ERROR"
            }

    def get_user_profile(self, token: str = None) -> Tuple[bool, Dict]:
        """Lấy thông tin profile user từ session token"""
        try:
            if not token:
                token = self.load_auth_token()
            
            if not token:
                # ❌ KHÔNG CÓ TOKEN → KHÔNG CHO PHÉP VÀO
                # KHÔNG cho phép offline_mode hoặc demo_mode nữa
                return False, {"error": "No authentication token - login required"}
            
            # Kiểm tra session với Supabase
            try:
                success, data = self.supabase.check_session_validity(token)
                
                if success:
                    return True, {
                        "success": True,
                        "data": data
                    }
                else:
                    # Session invalid hoặc subscription expired hoặc lỗi kết nối
                    error_code = data.get("error_code", "SESSION_INVALID")
                    
                    # Xử lý đặc biệt cho subscription expired
                    if error_code == "SUBSCRIPTION_EXPIRED":
                        return False, {
                            "success": False,
                            "error": data.get("error", "Gói dịch vụ đã hết hạn"),
                            "error_code": "SUBSCRIPTION_EXPIRED",
                            "expired_date": data.get("expired_date")
                        }
                    else:
                        return False, {
                            "success": False,
                            "error": data.get("error", "Session invalid - login required"),
                            "error_code": error_code
                        }
            
            except Exception as supabase_error:
                # Connection error → BẮT BUỘC login lại
                # KHÔNG CHO PHÉP fallback sang offline mode
                print(f"⚠️ Supabase connection failed - login required: {supabase_error}")
                return False, {
                    "success": False,
                    "error": f"Connection failed - login required: {str(supabase_error)}",
                    "error_code": "CONNECTION_ERROR"
                }
                
        except Exception as e:
            return False, {
                "success": False,
                "error": str(e),
                "error_code": "SYSTEM_ERROR"
            }

    def save_auth_token(self, token: str):
        """Lưu authentication token với device binding - THỬ NHIỀU LOCATIONS"""
        import sys
        
        # Tạo device fingerprint
        device_fingerprint = self._get_machine_secret()
        
        # Encrypt token với device fingerprint
        encrypted_token = self._encrypt_token_with_device(token, device_fingerprint)
        
        # Lưu token đã encrypt
        token_data = {
            "encrypted_token": encrypted_token,
            "device_hash": hashlib.sha256(device_fingerprint.encode()).hexdigest()[:16],
            "created_at": datetime.now().isoformat()
        }
        
        # THỬ LƯU VÀO NHIỀU LOCATIONS (ưu tiên Home, rồi CWD, cuối cùng module)
        save_locations = [
            os.path.join(os.path.expanduser("~"), ".auth_token"),  # Home (ƯU TIÊN CHO .EXE)
            os.path.join(os.getcwd(), ".auth_token"),  # CWD
            os.path.join(os.path.dirname(sys.executable), ".auth_token"),  # .exe folder
            os.path.join(os.path.dirname(sys.argv[0]) if sys.argv else os.getcwd(), ".auth_token"),  # Script folder
            os.path.join(os.path.dirname(__file__), ".auth_token"),  # Module folder (cuối cùng)
        ]
        
        saved = False
        last_error = None
        
        for token_file in save_locations:
            try:
                # Thử lưu vào location này
                with open(token_file, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(token_data))
                
                # Set file permissions (chỉ owner có thể đọc) - chỉ trên Unix
                try:
                    os.chmod(token_file, 0o600)
                except:
                    pass  # Windows không support chmod
                
                print(f"✅ Token saved successfully: {token_file}")
                saved = True
                break  # Lưu thành công, thoát loop
                
            except Exception as e:
                last_error = e
                continue  # Thử location tiếp theo
        
        if not saved:
            print(f"⚠️ WARNING: Không thể lưu auth token ở bất kỳ location nào!")
            print(f"   Last error: {last_error}")
            print(f"   Tried locations: {save_locations}")
            raise Exception(f"Cannot save auth token: {last_error}")

    def load_auth_token(self) -> Optional[str]:
        """Load authentication token với device validation - CHECK NHIỀU LOCATIONS"""
        try:
            import sys
            
            # CHECK TẤT CẢ LOCATIONS (ƯU TIÊN HOME TRƯỚC - giống như save)
            possible_paths = [
                os.path.join(os.path.expanduser("~"), ".auth_token"),  # Home (ƯU TIÊN CHO .EXE)
                os.path.join(os.getcwd(), ".auth_token"),  # CWD
                os.path.join(os.path.dirname(sys.executable), ".auth_token"),  # .exe folder
                os.path.join(os.path.dirname(sys.argv[0]) if sys.argv else os.getcwd(), ".auth_token"),  # Script folder
                os.path.join(os.path.dirname(__file__), ".auth_token"),  # Module folder
            ]
            
            token_file = None
            content = None
            
            for path in possible_paths:
                if os.path.exists(path):
                    token_file = path
                    with open(token_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    print(f"✅ Token loaded from: {token_file}")
                    break
            
            if not token_file or not content:
                return None
            
            # Kiểm tra format cũ (plain text) vs format mới (JSON)
            try:
                token_data = json.loads(content)
                encrypted_token = token_data.get("encrypted_token")
                stored_device_hash = token_data.get("device_hash")
                
                if not encrypted_token or not stored_device_hash:
                    return None
                
                # Validate device
                current_device = self._get_machine_secret()
                current_device_hash = hashlib.sha256(current_device.encode()).hexdigest()[:16]
                
                if stored_device_hash != current_device_hash:
                    # Xóa token file không hợp lệ
                    os.remove(token_file)
                    return None
                
                # Decrypt token
                decrypted_token = self._decrypt_token_with_device(encrypted_token, current_device)
                return decrypted_token
                
            except json.JSONDecodeError:
                # Format cũ - plain text token, cần migrate
                # Xóa token cũ để bắt buộc đăng nhập lại
                os.remove(token_file)
                return None
                
        except Exception as e:
            pass
        
        return None
    
    def _encrypt_token_with_device(self, token: str, device_key: str) -> str:
        """Encrypt token với device key"""
        try:
            # Sử dụng device key làm encryption key
            key = hashlib.sha256(device_key.encode()).digest()[:32]  # 32 bytes for AES-256
            
            # Simple XOR encryption (có thể thay bằng AES nếu cần bảo mật cao hơn)
            encrypted = []
            for i, char in enumerate(token):
                key_char = key[i % len(key)]
                encrypted_char = ord(char) ^ key_char
                encrypted.append(encrypted_char)
            
            # Convert to base64
            encrypted_bytes = bytes(encrypted)
            return base64.b64encode(encrypted_bytes).decode()
            
        except Exception as e:
            print(f"Encryption error: {e}")
            return token  # Fallback to plain token
    
    def _decrypt_token_with_device(self, encrypted_token: str, device_key: str) -> str:
        """Decrypt token với device key"""
        try:
            # Sử dụng device key làm decryption key
            key = hashlib.sha256(device_key.encode()).digest()[:32]
            
            # Decode from base64
            encrypted_bytes = base64.b64decode(encrypted_token.encode())
            
            # XOR decryption
            decrypted = []
            for i, encrypted_char in enumerate(encrypted_bytes):
                key_char = key[i % len(key)]
                decrypted_char = encrypted_char ^ key_char
                decrypted.append(chr(decrypted_char))
            
            return ''.join(decrypted)
            
        except Exception as e:
            print(f"Decryption error: {e}")
            return encrypted_token  # Fallback

    def logout(self, user_id: int = None, clear_all_config: bool = False) -> Tuple[bool, Dict]:
        """Đăng xuất user"""
        try:
            # Lấy session token
            session_token = self.load_auth_token()
            
            if session_token:
                # Logout với Supabase
                success, message = self.supabase.logout_user(session_token)
                
                if success:
                    # Clear local token
                    self.clear_auth_token(clear_all_config)
                    
                    return True, {
                        "success": True,
                        "message": message
                    }
                else:
                    return False, {
                        "success": False,
                        "error": message,
                        "error_code": "LOGOUT_FAILED"
                    }
            else:
                # Không có session token, chỉ clear local
                self.clear_auth_token(clear_all_config)
                return True, {
                    "success": True,
                    "message": "Đăng xuất thành công (local only)"
                }

        except Exception as e:
            return False, {
                "success": False,
                "error": str(e),
                "error_code": "SYSTEM_ERROR"
            }

    def clear_auth_token(self, clear_all: bool = False):
        """Xóa authentication token ở TẤT CẢ LOCATIONS"""
        try:
            import sys
            
            # XÓA TẤT CẢ LOCATIONS (giống như save/load - ưu tiên Home trước)
            possible_paths = [
                os.path.join(os.path.expanduser("~"), ".auth_token"),  # Home (ƯU TIÊN CHO .EXE)
                os.path.join(os.getcwd(), ".auth_token"),  # CWD
                os.path.join(os.path.dirname(sys.executable), ".auth_token"),  # .exe folder
                os.path.join(os.path.dirname(sys.argv[0]) if sys.argv else os.getcwd(), ".auth_token"),  # Script folder
                os.path.join(os.path.dirname(__file__), ".auth_token"),  # Module folder
            ]
            
            deleted_count = 0
            for token_file in possible_paths:
                try:
                    if os.path.exists(token_file):
                        os.remove(token_file)
                        print(f"🗑️ Deleted token: {token_file}")
                        deleted_count += 1
                except:
                    pass
            
            if deleted_count == 0:
                print("ℹ️ No token files found to delete")
            
            if clear_all:
                # Xóa thêm các file config khác
                config_files = [".user_config", ".session_data", "config.json"]
                for base_path in possible_paths:
                    base_dir = os.path.dirname(base_path)
                    for config_file in config_files:
                        file_path = os.path.join(base_dir, config_file)
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except:
                            pass
                        
        except:
            pass

    def demo_login_response(self, username: str) -> Tuple[bool, Dict]:
        """Demo login response for testing"""
        return True, {
                "success": True,
        "message": "Demo login thành công",
        "user": {
            "id": 999,
                    "username": username,
            "role": "demo"
        },
        "subscription": {
            "subscription_type": "demo",
            "is_active": True,
            "max_videos_per_day": 10,
            "max_videos_per_month": 100
        },
        "usage": {
            "videos_today": 0
        },
        "session_token": "demo_session_token_" + str(int(time.time())),
        "machine_token": "demo_machine_token"
        }


# Global functions for backward compatibility
def authenticate_iting_user(username: str, password: str, machine_code: str, force_login: bool = False) -> Tuple[bool, str, Dict]:
    """Authenticate user với ItingAPI - BẮT BUỘC truyền mã máy"""
    try:
        api = ItingAPI()
    
        if api.demo_mode:
            success, data = api.demo_login_response(username)
            if success:
                return True, data.get("message", "Demo login successful"), data
            else:
                return False, "Demo login failed", {}
        
        success, data = api.login(username, password, machine_code)
        
        if success:
            return True, data.get("message", "Login successful"), data
        else:
            return False, data.get("error", "Login failed"), data
            
    except Exception as e:
        return False, f"System error: {str(e)}", {}


def check_iting_session() -> Tuple[bool, Dict]:
    """Kiểm tra session hiện tại - BẮT BUỘC có token file"""
    try:
        api = ItingAPI()
        
        # BƯỚC 1: KIỂM TRA TOKEN FILE CÓ TỒN TẠI KHÔNG (QUAN TRỌNG)
        token = api.load_auth_token()
        
        if not token:
            # ❌ KHÔNG CÓ TOKEN FILE → BẮT BUỘC ĐĂNG NHẬP
            # KHÔNG CHO PHÉP offline_mode hay demo_mode
            return False, {"error": "No authentication token - login required"}
        
        # BƯỚC 2: NẾU CÓ TOKEN → VALIDATE VỚI SERVER
        # Tạm TẮT offline_mode để force check với server
        original_offline_mode = api.offline_mode
        original_demo_mode = api.demo_mode
        api.offline_mode = False
        api.demo_mode = False
        
        try:
            success, data = api.get_user_profile(token=token)
            
            if success:
                # Session valid
                return True, data.get("data", {})
            else:
                # Session invalid → BẮT BUỘC login lại
                # Clear token cũ
                api.clear_auth_token(clear_all=True)
                return False, {"error": "Session invalid - login required"}
        
        finally:
            # Khôi phục settings
            api.offline_mode = original_offline_mode
            api.demo_mode = original_demo_mode
        
    except Exception as e:
        return False, {"error": str(e)}


def logout_iting_user(session_token: str = None, logout_type: str = "manual") -> Tuple[bool, str]:
    """Đăng xuất user hiện tại - nhận session_token và logout_type"""
    try:
        api = ItingAPI()
        
        # Nếu không có session_token, thử load từ file
        if not session_token:
            session_token = api.load_auth_token()
        
        if session_token:
            # Logout qua supabase
            success, message = api.supabase.logout_user(session_token, logout_type)
            
            if success:
                # Clear local token
                api.clear_auth_token(clear_all=True)
                return True, message
            else:
                return False, message
        else:
            # Không có token, chỉ clear local
            api.clear_auth_token(clear_all=True)
            return True, "Đăng xuất thành công (local only)"

    except Exception as e:
        return False, f"System error: {str(e)}"

    
def force_login(self, username: str, password: str) -> Tuple[bool, str, Dict]:
    """Force login - đăng xuất sessions cũ và đăng nhập mới"""
    try:
        # Đăng xuất trước
        logout_iting_user()
        
        # Đăng nhập lại
        return authenticate_iting_user(username, password, force_login=True)
            
    except Exception as e:
        return False, f"Force login error: {str(e)}", {}
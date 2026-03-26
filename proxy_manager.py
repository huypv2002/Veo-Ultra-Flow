"""
Proxy Manager - Quản lý proxy đa loại cho LabsFlowClient.

Hỗ trợ 5 loại proxy:
1. none       - Không dùng proxy (IP gốc)
2. static     - Proxy Tĩnh (HTTP/SOCKS5 cố định)
3. rotating   - Proxy Xoay (tự động đổi IP mỗi request)
4. warp       - WARP (Cloudflare 1.1.1.1) qua warp-svc local
5. tor        - Tor Network qua SOCKS5 local (127.0.0.1:9050)
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote


# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

PROXY_TYPES = ("none", "static", "rotating", "warp", "tor")

WARP_SOCKS5 = "socks5://127.0.0.1:40000"   # warp-cli proxy mode default
TOR_SOCKS5 = "socks5://127.0.0.1:9050"      # Tor default SOCKS5

SETTINGS_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / "proxy_settings.json"


# ═══════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProxyEntry:
    """Một proxy trong pool."""
    server: str = ""
    username: str = ""
    password: str = ""
    status: str = "untested"   # untested, working, failed, testing
    last_used: str = ""
    proxy_type: str = "static"  # static, rotating

    def to_requests_proxy(self) -> Dict[str, str]:
        """Convert sang format cho requests.Session.proxies"""
        url = self._build_url()
        return {"http": url, "https": url}

    def to_playwright_proxy(self) -> Dict[str, str]:
        """Convert sang format cho Playwright / LabsFlowClient proxy pool."""
        return {
            "server": self.server,
            "username": self.username,
            "password": self.password,
        }

    def to_chrome_arg(self) -> str:
        """Convert sang --proxy-server arg cho Chrome CLI."""
        # Chrome chỉ nhận server (không auth), auth qua CDP
        return self.server

    def _build_url(self) -> str:
        """Build proxy URL với auth."""
        scheme_host = self.server
        if self.username and self.password:
            # Tách scheme
            if "://" in scheme_host:
                scheme, rest = scheme_host.split("://", 1)
            else:
                scheme, rest = "http", scheme_host
            return f"{scheme}://{quote(self.username)}:{quote(self.password)}@{rest}"
        return scheme_host if "://" in scheme_host else f"http://{scheme_host}"


@dataclass
class ProxyConfig:
    """Cấu hình proxy cho 1 account."""
    proxy_type: str = "none"          # none, static, rotating, warp, tor
    static_server: str = ""           # http://host:port hoặc socks5://host:port
    static_username: str = ""
    static_password: str = ""
    rotating_server: str = ""         # http://host:port (gateway xoay)
    rotating_username: str = ""
    rotating_password: str = ""
    warp_port: int = 40000            # WARP local SOCKS5 port
    tor_port: int = 9050              # Tor local SOCKS5 port

    def get_active_proxy(self) -> Optional[ProxyEntry]:
        """Trả về ProxyEntry đang active dựa trên proxy_type."""
        if self.proxy_type == "none":
            return None
        elif self.proxy_type == "static":
            if not self.static_server:
                return None
            return ProxyEntry(
                server=self.static_server,
                username=self.static_username,
                password=self.static_password,
                proxy_type="static",
            )
        elif self.proxy_type == "rotating":
            if not self.rotating_server:
                return None
            return ProxyEntry(
                server=self.rotating_server,
                username=self.rotating_username,
                password=self.rotating_password,
                proxy_type="rotating",
            )
        elif self.proxy_type == "warp":
            return ProxyEntry(
                server=f"socks5://127.0.0.1:{self.warp_port}",
                proxy_type="static",
            )
        elif self.proxy_type == "tor":
            return ProxyEntry(
                server=f"socks5://127.0.0.1:{self.tor_port}",
                proxy_type="static",
            )
        return None

    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        """Trả về dict proxies cho requests.Session."""
        entry = self.get_active_proxy()
        if entry:
            return entry.to_requests_proxy()
        return None

    def get_chrome_proxy_arg(self) -> Optional[str]:
        """Trả về --proxy-server value cho Chrome launch."""
        entry = self.get_active_proxy()
        if entry:
            return entry.to_chrome_arg()
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProxyConfig":
        if not d:
            return cls()
        return cls(
            proxy_type=d.get("proxy_type", "none"),
            static_server=d.get("static_server", d.get("server", "")),
            static_username=d.get("static_username", d.get("username", "")),
            static_password=d.get("static_password", d.get("password", "")),
            rotating_server=d.get("rotating_server", ""),
            rotating_username=d.get("rotating_username", ""),
            rotating_password=d.get("rotating_password", ""),
            warp_port=d.get("warp_port", 40000),
            tor_port=d.get("tor_port", 9050),
        )


# ═══════════════════════════════════════════════════════════════
# ProxyManager Singleton
# ═══════════════════════════════════════════════════════════════

class ProxyManager:
    """Singleton quản lý proxy pool toàn cục."""

    _instance: Optional["ProxyManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProxyManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._proxies: List[ProxyEntry] = []
        self._enabled: bool = False
        self._lock = threading.Lock()
        self._load_settings()

    # ─── Enable / Disable ─────────────────────────────────────

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._save_settings()

    # ─── CRUD ─────────────────────────────────────────────────

    def get_all_proxies(self) -> List[ProxyEntry]:
        with self._lock:
            return list(self._proxies)

    def add_proxy(self, entry: ProxyEntry) -> bool:
        """Thêm 1 proxy, trả về False nếu trùng server."""
        with self._lock:
            for p in self._proxies:
                if p.server == entry.server and p.username == entry.username:
                    return False
            self._proxies.append(entry)
        self._save_settings()
        return True

    def add_proxies_from_text(self, text: str) -> Tuple[int, int]:
        """Parse text nhiều dòng, trả về (added, failed)."""
        added = 0
        failed = 0
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            entry = self._parse_proxy_line(line)
            if entry and self.add_proxy(entry):
                added += 1
            else:
                failed += 1
        return added, failed

    def remove_proxy(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self._proxies):
                self._proxies.pop(index)
                self._save_settings()
                return True
        return False

    def clear_all(self):
        with self._lock:
            self._proxies.clear()
        self._save_settings()

    # ─── Status ───────────────────────────────────────────────

    def mark_proxy_working(self, proxy: ProxyEntry):
        proxy.status = "working"
        proxy.last_used = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._save_settings()

    def mark_proxy_failed(self, proxy: ProxyEntry):
        proxy.status = "failed"
        self._save_settings()

    # ─── Parse ────────────────────────────────────────────────

    @staticmethod
    def _parse_proxy_line(line: str) -> Optional[ProxyEntry]:
        """Parse 1 dòng proxy text → ProxyEntry."""
        line = line.strip()
        if not line:
            return None

        # Format: http(s)://user:pass@host:port hoặc socks5://...
        if line.startswith(("http://", "https://", "socks5://", "socks4://")):
            try:
                from urllib.parse import urlparse
                parsed = urlparse(line)
                host = parsed.hostname or ""
                port = parsed.port or 80
                scheme = parsed.scheme or "http"
                if not host:
                    return None
                return ProxyEntry(
                    server=f"{scheme}://{host}:{port}",
                    username=parsed.username or "",
                    password=parsed.password or "",
                )
            except Exception:
                return None

        # Format: user:pass@host:port
        if "@" in line:
            auth, hostport = line.rsplit("@", 1)
            parts_auth = auth.split(":", 1)
            username = parts_auth[0] if len(parts_auth) > 0 else ""
            password = parts_auth[1] if len(parts_auth) > 1 else ""
            return ProxyEntry(
                server=f"http://{hostport}" if "://" not in hostport else hostport,
                username=username,
                password=password,
            )

        # Format: host:port:user:pass
        parts = line.split(":")
        if len(parts) >= 4:
            host, port, user = parts[0], parts[1], parts[2]
            pwd = ":".join(parts[3:])
            return ProxyEntry(server=f"http://{host}:{port}", username=user, password=pwd)
        elif len(parts) == 2:
            return ProxyEntry(server=f"http://{parts[0]}:{parts[1]}")

        return None

    # ─── Persistence ──────────────────────────────────────────

    def _save_settings(self):
        try:
            data = {
                "enabled": self._enabled,
                "proxies": [asdict(p) for p in self._proxies],
            }
            SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"  ⚠️ [ProxyManager] Lỗi lưu settings: {e}")

    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                self._enabled = data.get("enabled", False)
                self._proxies = []
                for p in data.get("proxies", []):
                    self._proxies.append(ProxyEntry(**{
                        k: v for k, v in p.items()
                        if k in ProxyEntry.__dataclass_fields__
                    }))
        except Exception as e:
            print(f"  ⚠️ [ProxyManager] Lỗi load settings: {e}")


# ═══════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════

def check_warp_available(port: int = 40000, timeout: float = 5.0) -> bool:
    """Kiểm tra WARP SOCKS5 proxy có hoạt động không."""
    try:
        import requests
        proxies = {"http": f"socks5://127.0.0.1:{port}", "https": f"socks5://127.0.0.1:{port}"}
        resp = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def check_tor_available(port: int = 9050, timeout: float = 5.0) -> bool:
    """Kiểm tra Tor SOCKS5 proxy có hoạt động không."""
    try:
        import requests
        proxies = {"http": f"socks5://127.0.0.1:{port}", "https": f"socks5://127.0.0.1:{port}"}
        resp = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def test_proxy_connection(proxy_entry: ProxyEntry, timeout: float = 10.0) -> Tuple[bool, str]:
    """Test proxy connection, trả về (success, ip_or_error)."""
    try:
        import requests
        proxies = proxy_entry.to_requests_proxy()
        resp = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=timeout)
        if resp.status_code == 200:
            ip = resp.json().get("origin", "unknown")
            return True, ip
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)[:80]


def apply_proxy_to_session(session, proxy_config: ProxyConfig) -> bool:
    """Áp dụng ProxyConfig vào requests.Session. Trả về True nếu có proxy."""
    if not proxy_config or proxy_config.proxy_type == "none":
        session.proxies = {}
        return False
    proxies = proxy_config.get_requests_proxies()
    if proxies:
        session.proxies = proxies
        return True
    session.proxies = {}
    return False

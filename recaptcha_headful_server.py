#!/usr/bin/env python3
"""
Headful reCAPTCHA Enterprise Token Solver Server
=================================================
HSW-style HTTP service (giống ElevenLabs-re) để lấy recaptchaToken Enterprise
cho Google Labs, dùng headful browser thật (không headless).

Chạy:
    python recaptcha_headful_server.py --port 8899 --slots 2

Endpoints:
    POST /solve         Lấy token (nhận cookies + action → trả token)
    GET  /health        Health check
    GET  /stats         Thống kê
    POST /recycle       Force recycle tất cả browser slots
    POST /recycle/{id}  Recycle 1 slot cụ thể

Cũng có thể import BrowserSlot trực tiếp để dùng standalone:
    from recaptcha_headful_server import BrowserSlot
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import signal
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── CloakBrowser (stealth Chromium) — fallback Playwright ────────────────────
_USE_CLOAK = False
try:
    from cloakbrowser import launch as cloak_launch
    _USE_CLOAK = True
except ImportError:
    cloak_launch = None  # type: ignore

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
except ImportError:
    sync_playwright = None  # type: ignore
    Browser = BrowserContext = Page = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════
SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
TARGET_URL = "https://labs.google/fx/tools/flow"

# UA pool (giống flow2api browser_captcha.py)
UA_LIST = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
]

RESOLUTIONS = [
    (1920, 1080), (2560, 1440), (1366, 768), (1536, 864),
    (1600, 900), (1280, 720), (1440, 900), (1680, 1050),
]


def _find_chrome_binary() -> Optional[str]:
    """Tìm Chrome thật trên máy."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    elif system == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser", "/usr/bin/chromium",
        ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    for name in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"]:
        found = shutil.which(name)
        if found:
            return found
    return None


def _hidden_window_args() -> List[str]:
    """Chrome headful nhưng ẩn ngoài màn hình."""
    if platform.system() == "Windows":
        return ["--window-position=-32000,-32000", "--window-size=400,300"]
    return ["--window-position=-3000,-3000", "--window-size=400,300"]


# ═══════════════════════════════════════════════════════════════════════════════
# BrowserSlot - Quản lý 1 headful Chrome instance
# ═══════════════════════════════════════════════════════════════════════════════
class BrowserSlot:
    """Một slot Chrome headful để solve reCAPTCHA Enterprise."""

    MAX_SOLVES_BEFORE_RECYCLE = 50
    MAX_AGE_SECONDS = 1800  # 30 phút

    def __init__(self, slot_id: int, visible: bool = False):
        self.slot_id = slot_id
        self.visible = visible
        self._lock = threading.Lock()
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._current_cookie_hash: Optional[str] = None
        self._solve_count = 0
        self._error_count = 0
        self._created_at = 0.0
        self._last_solve_at = 0.0
        self._user_agent = random.choice(UA_LIST)
        self._viewport = random.choice(RESOLUTIONS)
        self._alive = False

    @property
    def is_alive(self) -> bool:
        return self._alive and self._browser is not None

    @property
    def needs_recycle(self) -> bool:
        if not self._alive:
            return True
        if self._solve_count >= self.MAX_SOLVES_BEFORE_RECYCLE:
            return True
        if self._created_at > 0 and (time.time() - self._created_at) > self.MAX_AGE_SECONDS:
            return True
        return False

    def start(self):
        """Khởi động browser: CloakBrowser (stealth) hoặc fallback Playwright."""
        with self._lock:
            if self._alive:
                return
            self._user_agent = random.choice(UA_LIST)
            self._viewport = random.choice(RESOLUTIONS)

            window_args = []
            if self.visible:
                window_args = ["--window-position=100,100", f"--window-size={self._viewport[0]},{self._viewport[1]}"]
            else:
                window_args = _hidden_window_args()

            try:
                if _USE_CLOAK and cloak_launch is not None:
                    # ── CloakBrowser: stealth Chromium, fingerprint spoofing ──
                    self._browser = cloak_launch(
                        headless=False,
                        args=window_args if window_args else None,
                    )
                    self._playwright = None  # Không dùng playwright manager
                    print(f"  🚀 [Slot-{self.slot_id}] CloakBrowser (stealth Chromium)")
                else:
                    # ── Fallback: Playwright ──
                    self._playwright = sync_playwright().start()
                    chrome_path = _find_chrome_binary()
                    launch_args = [
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-extensions",
                        "--disable-sync",
                        "--disable-translate",
                        "--disable-background-networking",
                        "--disable-infobars",
                        "--hide-crash-restore-bubble",
                        "--disable-popup-blocking",
                        "--metrics-recording-only",
                    ] + window_args

                    if chrome_path:
                        self._browser = self._playwright.chromium.launch(
                            headless=False,
                            executable_path=chrome_path,
                            args=launch_args,
                        )
                        print(f"  🚀 [Slot-{self.slot_id}] Chrome thật ({chrome_path.split('/')[-1]})")
                    else:
                        self._browser = self._playwright.chromium.launch(
                            headless=False,
                            args=launch_args,
                        )
                        print(f"  🚀 [Slot-{self.slot_id}] Chromium Playwright")
            except Exception as e:
                print(f"  ❌ [Slot-{self.slot_id}] Không thể khởi động browser: {e}")
                self._cleanup()
                raise

            self._alive = True
            self._created_at = time.time()
            self._solve_count = 0
            self._error_count = 0
            self._current_cookie_hash = None
            engine = "CloakBrowser" if (_USE_CLOAK and cloak_launch) else "Playwright"
            vis_str = "VISIBLE (100,100)" if self.visible else "HIDDEN (off-screen)"
            print(f"  ✅ [Slot-{self.slot_id}] {engine} started ({vis_str}, UA={self._user_agent[:40]}...)")

    def stop(self):
        """Đóng Chrome."""
        with self._lock:
            self._cleanup()

    def _cleanup(self):
        self._alive = False
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._current_cookie_hash = None

    def recycle(self):
        """Đóng và khởi động lại."""
        print(f"  🔄 [Slot-{self.slot_id}] Recycling (solves={self._solve_count}, errors={self._error_count})...")
        self.stop()
        time.sleep(0.5)
        self.start()

    def _cookie_hash(self, cookies: Dict[str, str]) -> str:
        import hashlib
        raw = json.dumps(sorted(cookies.items()), sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def _ensure_context(self, cookies: Dict[str, str], user_agent: Optional[str] = None):
        """Tạo hoặc tái sử dụng BrowserContext với cookies."""
        c_hash = self._cookie_hash(cookies)
        ua = user_agent or self._user_agent

        # Nếu cookie giống lần trước → tái sử dụng context
        if self._context and self._current_cookie_hash == c_hash:
            return

        # Đóng context cũ
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None

        # Tạo context mới
        w, h = self._viewport
        self._context = self._browser.new_context(
            viewport={"width": w, "height": h},
            user_agent=ua,
            ignore_https_errors=True,
            locale="en-US",
        )

        # Inject cookies
        cookie_items = []
        for name, value in cookies.items():
            if not name or value is None:
                continue
            item = {
                "name": name,
                "value": str(value),
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
            }
            if name.startswith("__Host-"):
                item["url"] = "https://labs.google/"
            else:
                item["domain"] = "labs.google"
                item["path"] = "/"
            cookie_items.append(item)
        if cookie_items:
            self._context.add_cookies(cookie_items)
        self._current_cookie_hash = c_hash
        print(f"  🍪 [Slot-{self.slot_id}] Context mới: {len(cookie_items)} cookies injected (hash={c_hash[:8]})")

    def solve(
        self,
        cookies: Dict[str, str],
        action: str = "VIDEO_GENERATION",
        user_agent: Optional[str] = None,
        timeout_s: int = 60,
    ) -> Dict[str, Any]:
        """Solve reCAPTCHA Enterprise và trả token."""
        start_time = time.time()
        with self._lock:
            if not self._alive:
                raise RuntimeError(f"Slot-{self.slot_id} chưa khởi động")

            try:
                self._ensure_context(cookies, user_agent)

                # Navigate hoặc reload
                if self._page is None:
                    self._page = self._context.new_page()

                    # ✅ Warm-up: navigate google.com trước để build trust score
                    print(f"  🔥 [Slot-{self.slot_id}] Warm-up: google.com → labs.google")
                    try:
                        self._page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=15000)
                        time.sleep(0.5)
                    except Exception:
                        pass

                    print(f"  🌐 [Slot-{self.slot_id}] Navigate → {TARGET_URL}")
                    self._page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                    # ✅ Đợi thêm để page fully settle (JS scripts, reCAPTCHA init)
                    time.sleep(2)
                else:
                    # Reload để lấy token mới
                    try:
                        self._page.reload(wait_until="domcontentloaded", timeout=30000)
                        time.sleep(1)
                    except Exception:
                        # Nếu reload fail → navigate lại
                        try:
                            self._page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass

                # Check redirect to login
                current_url = self._page.url or ""
                if "accounts.google" in current_url or "signin" in current_url.lower():
                    raise RuntimeError("Redirected to login - cookie không hợp lệ hoặc expired")

                # Đợi grecaptcha load
                print(f"  ⏳ [Slot-{self.slot_id}] Đợi grecaptcha load...")
                gre_ready = None
                wait_start = time.time()
                while time.time() - wait_start < timeout_s:
                    try:
                        gre_ready = self._page.evaluate("""
                            () => {
                                if (typeof window.grecaptcha !== 'undefined') {
                                    if (window.grecaptcha.enterprise &&
                                        typeof window.grecaptcha.enterprise.execute === 'function') {
                                        return 'enterprise';
                                    }
                                    if (typeof window.grecaptcha.execute === 'function') {
                                        return 'classic';
                                    }
                                }
                                return null;
                            }
                        """)
                        if gre_ready:
                            break
                    except Exception:
                        pass
                    time.sleep(0.3)

                if not gre_ready:
                    raise RuntimeError(f"grecaptcha không load được sau {timeout_s}s")

                print(f"  🔑 [Slot-{self.slot_id}] Execute reCAPTCHA (mode={gre_ready}, action={action})...")

                # Execute reCAPTCHA
                result = self._page.evaluate(
                    """
                    async ([siteKey, action]) => {
                        try {
                            if (typeof grecaptcha === 'undefined' || !grecaptcha.enterprise) {
                                return {error: 'grecaptcha chưa load'};
                            }
                            const token = await grecaptcha.enterprise.execute(siteKey, {action: action});
                            if (token && token.length > 0) {
                                return {token: token};
                            }
                            return {error: 'Token rỗng'};
                        } catch (e) {
                            return {error: e.toString()};
                        }
                    }
                    """,
                    [SITE_KEY, action],
                )

                elapsed_ms = int((time.time() - start_time) * 1000)

                if isinstance(result, dict) and result.get("token"):
                    token = result["token"]
                    self._solve_count += 1
                    self._last_solve_at = time.time()
                    print(f"  ✅ [Slot-{self.slot_id}] Token OK (len={len(token)}, {elapsed_ms}ms)")
                    return {
                        "token": token,
                        "solve_time_ms": elapsed_ms,
                        "source": f"slot_{self.slot_id}",
                        "solve_count": self._solve_count,
                    }
                else:
                    error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
                    raise RuntimeError(f"reCAPTCHA error: {error_msg}")

            except Exception as e:
                self._error_count += 1
                elapsed_ms = int((time.time() - start_time) * 1000)
                error_str = str(e)
                print(f"  ❌ [Slot-{self.slot_id}] Solve failed ({elapsed_ms}ms): {error_str[:100]}")

                # Reset page on error
                if self._page:
                    try:
                        self._page.close()
                    except Exception:
                        pass
                    self._page = None
                if self._context:
                    try:
                        self._context.close()
                    except Exception:
                        pass
                    self._context = None
                self._current_cookie_hash = None

                raise RuntimeError(error_str)

    def stats(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "alive": self._alive,
            "solve_count": self._solve_count,
            "error_count": self._error_count,
            "age_seconds": int(time.time() - self._created_at) if self._created_at else 0,
            "needs_recycle": self.needs_recycle,
            "current_cookie": self._current_cookie_hash[:8] if self._current_cookie_hash else None,
            "visible": self.visible,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# HeadfulTokenPool - Pool of BrowserSlots
# ═══════════════════════════════════════════════════════════════════════════════
class HeadfulTokenPool:
    """Pool quản lý nhiều BrowserSlot."""

    def __init__(self, num_slots: int = 2, visible: bool = False):
        self.num_slots = num_slots
        self.visible = visible
        self._slots: List[BrowserSlot] = []
        self._robin_index = 0
        self._global_lock = threading.Lock()
        self._total_solves = 0
        self._total_errors = 0
        self._started_at = time.time()

    def start_all(self):
        """Khởi động tất cả slots."""
        print(f"🚀 Khởi động pool: {self.num_slots} slot(s), visible={self.visible}")
        for i in range(self.num_slots):
            slot = BrowserSlot(slot_id=i, visible=self.visible)
            try:
                slot.start()
                self._slots.append(slot)
            except Exception as e:
                print(f"  ⚠️ Slot-{i} start failed: {e}")

        if not self._slots:
            raise RuntimeError("Không thể khởi động bất kỳ browser slot nào")
        print(f"✅ Pool sẵn sàng: {len(self._slots)}/{self.num_slots} slots")

    def stop_all(self):
        """Đóng tất cả slots."""
        print("🛑 Đóng tất cả browser slots...")
        for slot in self._slots:
            try:
                slot.stop()
            except Exception:
                pass
        self._slots.clear()

    def _pick_slot(self) -> BrowserSlot:
        """Round-robin chọn slot."""
        with self._global_lock:
            if not self._slots:
                raise RuntimeError("Không có browser slot nào đang chạy")

            # Auto-recycle nếu cần
            for slot in self._slots:
                if slot.needs_recycle:
                    try:
                        slot.recycle()
                    except Exception as e:
                        print(f"  ⚠️ Recycle Slot-{slot.slot_id} failed: {e}")

            # Round-robin
            idx = self._robin_index % len(self._slots)
            self._robin_index += 1
            return self._slots[idx]

    def solve(
        self,
        cookies: Dict[str, str],
        action: str = "VIDEO_GENERATION",
        user_agent: Optional[str] = None,
        timeout_s: int = 60,
    ) -> Dict[str, Any]:
        """Solve reCAPTCHA với slot available."""
        slot = self._pick_slot()
        try:
            result = slot.solve(cookies=cookies, action=action, user_agent=user_agent, timeout_s=timeout_s)
            self._total_solves += 1
            return result
        except Exception as e:
            self._total_errors += 1
            # Retry 1 lần với slot khác (nếu có)
            if len(self._slots) > 1:
                other_slot = self._pick_slot()
                if other_slot.slot_id != slot.slot_id:
                    try:
                        result = other_slot.solve(cookies=cookies, action=action, user_agent=user_agent, timeout_s=timeout_s)
                        self._total_solves += 1
                        return result
                    except Exception:
                        pass
            raise

    def recycle_all(self):
        """Force recycle tất cả slots."""
        for slot in self._slots:
            try:
                slot.recycle()
            except Exception as e:
                print(f"  ⚠️ Recycle Slot-{slot.slot_id} failed: {e}")

    def stats(self) -> Dict[str, Any]:
        return {
            "uptime_seconds": int(time.time() - self._started_at),
            "total_solves": self._total_solves,
            "total_errors": self._total_errors,
            "slots": [s.stats() for s in self._slots],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI App — Created lazily inside main() to avoid import-time crashes
# ═══════════════════════════════════════════════════════════════════════════════

def _create_app(pool_ref: List[Optional[HeadfulTokenPool]]):
    """Create FastAPI app with routes. pool_ref is a mutable list [pool] for late binding."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel

    app = FastAPI(title="Headful reCAPTCHA Enterprise Solver", version="1.0.0")

    class SolveRequest(BaseModel):
        cookies: Dict[str, str]
        action: str = "VIDEO_GENERATION"
        user_agent: Optional[str] = None
        timeout: int = 60

    @app.post("/solve")
    def solve_captcha(req: SolveRequest):
        pool = pool_ref[0]
        if pool is None:
            raise HTTPException(status_code=503, detail="Pool chưa khởi tạo")
        try:
            result = pool.solve(
                cookies=req.cookies,
                action=req.action,
                user_agent=req.user_agent,
                timeout_s=req.timeout,
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/health")
    def health_check():
        pool = pool_ref[0]
        if pool is None:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        stats = pool.stats()
        return {
            "status": "ok",
            "uptime_seconds": stats["uptime_seconds"],
            "active_slots": len([s for s in stats["slots"] if s["alive"]]),
            "total_solves": stats["total_solves"],
        }

    @app.get("/stats")
    def get_stats():
        pool = pool_ref[0]
        if pool is None:
            raise HTTPException(status_code=503, detail="Pool chưa khởi tạo")
        return pool.stats()

    @app.post("/recycle")
    def recycle_all_slots():
        pool = pool_ref[0]
        if pool is None:
            raise HTTPException(status_code=503, detail="Pool chưa khởi tạo")
        pool.recycle_all()
        return {"ok": True, "message": "Tất cả slots đã được recycle"}

    return app


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Headful reCAPTCHA Enterprise Token Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8899, help="Bind port")
    parser.add_argument("--slots", type=int, default=1, help="Số browser slots")
    parser.add_argument("--visible", action="store_true", help="Hiển thị browser (debug)")
    args = parser.parse_args()

    # Env override
    visible = args.visible or os.environ.get("HEADFUL_VISIBLE", "").strip().lower() in ("1", "true", "yes")

    print("=" * 60)
    print("  Headful reCAPTCHA Enterprise Token Server")
    print("=" * 60)
    print(f"  Host:    {args.host}:{args.port}")
    print(f"  Slots:   {args.slots}")
    print(f"  Visible: {visible}")
    print(f"  Chrome:  {_find_chrome_binary() or 'Playwright Chromium'}")
    print("=" * 60)

    # Khởi tạo pool
    pool = HeadfulTokenPool(num_slots=args.slots, visible=visible)
    pool.start_all()

    # Tạo FastAPI app
    pool_ref: List[Optional[HeadfulTokenPool]] = [pool]
    app = _create_app(pool_ref)

    # Graceful shutdown
    def shutdown_handler(sig, frame):
        print("\n🛑 Shutting down...")
        if pool_ref[0]:
            pool_ref[0].stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()


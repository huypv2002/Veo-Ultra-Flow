#!/usr/bin/env python3
"""
Extension Bridge Server - WebSocket + HTTP hybrid server.

Nhận job từ LabsFlowClient (Python) qua HTTP hoặc WebSocket,
broadcast đến Chrome Extension đang kết nối, extension execute
reCAPTCHA Enterprise trong browser thật và trả token về.

Architecture:
  ┌─────────────────┐    HTTP POST /request-token      ┌───────────────────┐
  │  LabsFlowClient │ ─────────────────────────────►  │                   │
  │  (Python tool)  │    HTTP GET  /get-captcha   ◄─── │  Bridge Server    │
  └─────────────────┘                                  │  (this file)      │
                                                       │                   │
  ┌─────────────────┐    WebSocket /ws            ◄──► │                   │
  │ Chrome Extension│ ─── receive job ──────────────►  │                   │
  │ (browser thật)  │ ─── send token ─────────────►   │                   │
  └─────────────────┘                                  └───────────────────┘

Endpoints:
  WebSocket  /ws                 Extension kết nối vào đây (nhận job, gửi token)
  POST /request-token            Tool yêu cầu lấy token (nhận cookie_hash + request_id)
  GET  /get-captcha              Tool poll lấy token (nhận cookie_hash + request_id)
  POST /set-captcha              Extension gửi token về (HTTP fallback)
  GET  /check-trigger            Extension poll check có job không (HTTP fallback)
  GET  /health                   Health check + thống kê

Run:
  pip install flask flask-sock
  python captcha_bridge_server.py --port 3000

Hoặc import và gọi:
  from captcha_bridge_server import run_bridge_server
  run_bridge_server(host="127.0.0.1", port=3000)
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from flask import Flask, jsonify, request

# ── Flask-Sock cho WebSocket ──────────────────────────────────────────────────
try:
    from flask_sock import Sock
    _HAS_FLASK_SOCK = True
except ImportError:
    _HAS_FLASK_SOCK = False
    Sock = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════
SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
TARGET_URL = "https://labs.google/fx/tools/flow"
TOKEN_TTL_SECONDS = 100  # reCAPTCHA token hết hạn sau ~120s, cache 100s để an toàn
JOB_TIMEOUT_SECONDS = 90  # Sau 90s không có extension nào nhận job → timeout

TRIGGER_FILE = Path("captcha_trigger.txt")


# ═══════════════════════════════════════════════════════════════════════════════
# State - Thread-safe job queue
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class TokenJob:
    """Một job yêu cầu lấy reCAPTCHA token."""
    request_id: str
    cookie_hash: str
    action: str = "VIDEO_GENERATION"
    created_at: float = field(default_factory=time.time)
    token: Optional[str] = None
    received_at: Optional[float] = None
    error: Optional[str] = None
    done_event: threading.Event = field(default_factory=threading.Event)

    def is_expired(self) -> bool:
        return time.time() - self.created_at > JOB_TIMEOUT_SECONDS

    def is_token_fresh(self) -> bool:
        if not self.token or not self.received_at:
            return False
        return time.time() - self.received_at < TOKEN_TTL_SECONDS


class BridgeState:
    """Thread-safe state cho bridge server."""

    def __init__(self):
        self._lock = threading.Lock()
        # Tất cả jobs đang pending hoặc vừa done: {request_id: TokenJob}
        self._jobs: Dict[str, TokenJob] = {}
        # WebSocket connections đang active (flask_sock connection objects)
        self._ws_clients: Set[Any] = set()
        self._ws_lock = threading.Lock()
        # Stats
        self.total_requested = 0
        self.total_fulfilled = 0
        self.total_errors = 0
        self.started_at = time.time()

    # ── Job management ────────────────────────────────────────────────────────

    def create_job(self, cookie_hash: str, action: str = "VIDEO_GENERATION") -> TokenJob:
        """Tạo job mới và thêm vào queue."""
        request_id = f"{cookie_hash[:8]}_{uuid.uuid4().hex[:12]}"
        job = TokenJob(request_id=request_id, cookie_hash=cookie_hash, action=action)
        with self._lock:
            self._jobs[request_id] = job
            self.total_requested += 1
        return job

    def get_job(self, request_id: str) -> Optional[TokenJob]:
        with self._lock:
            return self._jobs.get(request_id)

    def fulfill_job(self, request_id: str, token: str) -> bool:
        """Extension gửi token về. Trả True nếu thành công."""
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                # Thử tìm theo prefix (nếu extension gửi rút gọn)
                for rid, j in self._jobs.items():
                    if rid.startswith(request_id) or request_id.startswith(j.cookie_hash[:8]):
                        job = j
                        break
            if job is None:
                return False
            job.token = token
            job.received_at = time.time()
            job.done_event.set()
            self.total_fulfilled += 1
            return True

    def fail_job(self, request_id: str, error: str) -> bool:
        """Đánh dấu job lỗi."""
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                return False
            job.error = error
            job.done_event.set()
            self.total_errors += 1
            return True

    def get_pending_jobs(self) -> List[TokenJob]:
        """Lấy danh sách jobs chưa có token, chưa timeout."""
        with self._lock:
            result = []
            for job in self._jobs.values():
                if job.token is None and job.error is None and not job.is_expired():
                    result.append(job)
            return result

    def cleanup_old_jobs(self, max_age: float = 300.0):
        """Xóa jobs cũ (đã done hoặc timeout)."""
        cutoff = time.time() - max_age
        with self._lock:
            to_delete = [
                rid for rid, job in self._jobs.items()
                if job.created_at < cutoff
            ]
            for rid in to_delete:
                del self._jobs[rid]

    # ── WebSocket client management ───────────────────────────────────────────

    def add_ws_client(self, ws) -> None:
        with self._ws_lock:
            self._ws_clients.add(ws)

    def remove_ws_client(self, ws) -> None:
        with self._ws_lock:
            self._ws_clients.discard(ws)

    def ws_client_count(self) -> int:
        with self._ws_lock:
            return len(self._ws_clients)

    def broadcast_job(self, job: TokenJob) -> int:
        """Gửi job đến tất cả extension đang kết nối. Trả về số client nhận được."""
        msg = json.dumps({
            "type": "get_token",
            "req_id": job.request_id,
            "cookie_hash": job.cookie_hash,
            "action": job.action,
            "site_key": SITE_KEY,
            "target_url": TARGET_URL,
        })
        sent = 0
        dead = []
        with self._ws_lock:
            clients = list(self._ws_clients)
        for ws in clients:
            try:
                ws.send(msg)
                sent += 1
            except Exception:
                dead.append(ws)
        # Dọn dead connections
        if dead:
            with self._ws_lock:
                for ws in dead:
                    self._ws_clients.discard(ws)
        return sent

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pending = sum(
                1 for j in self._jobs.values()
                if j.token is None and j.error is None and not j.is_expired()
            )
        return {
            "uptime_seconds": int(time.time() - self.started_at),
            "ws_clients": self.ws_client_count(),
            "pending_jobs": pending,
            "total_requested": self.total_requested,
            "total_fulfilled": self.total_fulfilled,
            "total_errors": self.total_errors,
        }


# ── Singleton state ────────────────────────────────────────────────────────────
state = BridgeState()


def write_trigger_file(needs_token: bool) -> None:
    try:
        TRIGGER_FILE.write_text("1" if needs_token else "0", encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Flask App
# ═══════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
sock = Sock(app) if _HAS_FLASK_SOCK else None


# ── WebSocket endpoint (extension kết nối vào đây) ────────────────────────────
if _HAS_FLASK_SOCK and sock is not None:
    @sock.route("/ws")
    def websocket_endpoint(ws):
        """Extension kết nối WS, nhận jobs, gửi tokens về."""
        state.add_ws_client(ws)
        client_id = uuid.uuid4().hex[:8]
        print(f"🔌 [WS] Extension connected (id={client_id}, total={state.ws_client_count()})")

        # Gửi ack ngay
        try:
            ws.send(json.dumps({
                "type": "connected",
                "client_id": client_id,
                "site_key": SITE_KEY,
                "target_url": TARGET_URL,
            }))
        except Exception:
            pass

        # Gửi ngay các pending jobs (nếu đã có trước khi extension kết nối)
        pending = state.get_pending_jobs()
        if pending:
            for job in pending:
                try:
                    ws.send(json.dumps({
                        "type": "get_token",
                        "req_id": job.request_id,
                        "cookie_hash": job.cookie_hash,
                        "action": job.action,
                        "site_key": SITE_KEY,
                        "target_url": TARGET_URL,
                    }))
                except Exception:
                    break
            print(f"  📤 [WS] Sent {len(pending)} pending job(s) to new client {client_id}")

        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "ping":
                    try:
                        ws.send(json.dumps({"type": "pong"}))
                    except Exception:
                        break

                elif msg_type == "token_result":
                    # Extension trả token về
                    req_id = data.get("req_id", "")
                    token = data.get("token", "")
                    error = data.get("error", "")

                    if token and len(token) > 20:
                        ok = state.fulfill_job(req_id, token)
                        print(f"  ✅ [WS] Token received (req_id={req_id[:16]}..., len={len(token)}, ok={ok})")
                        write_trigger_file(len(state.get_pending_jobs()) > 0)
                    elif error:
                        state.fail_job(req_id, error)
                        print(f"  ❌ [WS] Extension error (req_id={req_id[:16]}...): {error[:80]}")
                    else:
                        state.fail_job(req_id, "Empty token from extension")

                elif msg_type == "register":
                    # Extension tự giới thiệu
                    label = data.get("client_label", "unknown")
                    print(f"  ℹ️ [WS] Extension registered: label={label}, client_id={client_id}")
                    try:
                        ws.send(json.dumps({"type": "register_ack", "client_id": client_id}))
                    except Exception:
                        break

        except Exception as e:
            print(f"  ⚠️ [WS] Client {client_id} disconnected: {e}")
        finally:
            state.remove_ws_client(ws)
            print(f"🔌 [WS] Extension disconnected (id={client_id}, remaining={state.ws_client_count()})")


# ── HTTP endpoints (dùng khi không có WS hoặc HTTP polling fallback) ──────────

@app.get("/health")
def health():
    s = state.stats()
    s["ws_enabled"] = _HAS_FLASK_SOCK
    return jsonify(s)


@app.get("/check-trigger")
def check_trigger():
    """HTTP polling: extension cũ check có job không."""
    pending = state.get_pending_jobs()
    any_pending = len(pending) > 0
    write_trigger_file(any_pending)

    pending_list = [
        {"request_id": j.request_id, "cookie_hash": j.cookie_hash, "action": j.action}
        for j in pending
    ]

    resp: Dict[str, Any] = {
        "needsToken": any_pending,
        "pendingRequests": pending_list,
        "pendingCount": len(pending_list),
        "ws_clients": state.ws_client_count(),
    }
    if pending_list:
        resp["cookie_hash"] = pending_list[0]["cookie_hash"]
        resp["request_id"] = pending_list[0]["request_id"]
    return jsonify(resp)


@app.post("/request-token")
def request_token():
    """
    Tool gọi để yêu cầu token.
    
    Body JSON:
      cookie_hash  str   - hash của cookie (để phân biệt)
      action       str   - reCAPTCHA action (mặc định VIDEO_GENERATION)
      request_id   str   - (optional) tự đặt ID; nếu không có sẽ tạo mới
    
    Response:
      { ok: true, request_id: "...", cookie_hash: "...", ws_clients: N }
    """
    data = request.get_json(silent=True) or {}
    cookie_hash = str(data.get("cookie_hash") or "default")
    action = str(data.get("action") or "VIDEO_GENERATION")
    custom_request_id = data.get("request_id")

    # Tạo job
    job = state.create_job(cookie_hash=cookie_hash, action=action)

    # Ghi đè request_id nếu caller tự đặt (để dễ track)
    if custom_request_id:
        with state._lock:
            del state._jobs[job.request_id]
            job.request_id = custom_request_id
            state._jobs[job.request_id] = job

    # Broadcast qua WebSocket ngay lập tức
    sent = state.broadcast_job(job)
    write_trigger_file(True)

    print(
        f"📡 [Bridge] Job created: req_id={job.request_id[:16]}..., "
        f"cookie={cookie_hash[:8]}..., action={action}, "
        f"ws_sent={sent}"
    )

    return jsonify({
        "ok": True,
        "request_id": job.request_id,
        "cookie_hash": cookie_hash,
        "action": action,
        "ws_clients": state.ws_client_count(),
        "ws_sent": sent,
    })


@app.get("/get-captcha")
def get_captcha():
    """
    Tool poll để lấy token đã được extension điền vào.
    
    Query params:
      request_id   str   - ID từ /request-token
      cookie_hash  str   - (optional fallback)
      clear        str   - "1" (default) để xóa sau khi lấy
    
    Response:
      { ok: true, token: "..." }  hoặc  { ok: true, token: null, pending: true }
    """
    request_id = request.args.get("request_id", "")
    cookie_hash = request.args.get("cookie_hash", "default")
    clear = request.args.get("clear", "1") not in ("0", "false", "False")

    job = state.get_job(request_id)

    # Fallback: tìm job theo cookie_hash nếu không có request_id
    if job is None and cookie_hash and cookie_hash != "default":
        pending = state.get_pending_jobs()
        for j in pending:
            if j.cookie_hash == cookie_hash:
                job = j
                break
        # Cũng check jobs đã done
        if job is None:
            with state._lock:
                for j in state._jobs.values():
                    if j.cookie_hash == cookie_hash and j.token:
                        job = j
                        break

    if job is None:
        return jsonify({"ok": False, "error": "Job not found", "request_id": request_id}), 404

    if job.is_expired() and job.token is None:
        return jsonify({
            "ok": False,
            "error": "Job timeout",
            "request_id": job.request_id,
            "pending": False,
        }), 408

    token = job.token
    error = job.error

    payload: Dict[str, Any] = {
        "ok": True,
        "token": token,
        "error": error,
        "request_id": job.request_id,
        "cookie_hash": job.cookie_hash,
        "pending": token is None and error is None,
        "received_at": job.received_at,
        "ws_clients": state.ws_client_count(),
    }

    if clear and token:
        # Xóa job sau khi đã lấy token
        with state._lock:
            state._jobs.pop(job.request_id, None)
        print(f"  🗑️ [Bridge] Job cleared: req_id={job.request_id[:16]}... (token len={len(token)})")

    return jsonify(payload)


@app.post("/set-captcha")
def set_captcha():
    """
    HTTP fallback: extension cũ (không WS) gửi token về.
    Extension mới nên dùng WebSocket.
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    request_id = data.get("request_id", "")
    cookie_hash = data.get("cookie_hash", "default")

    if not token or len(token) < 10:
        return jsonify({"ok": False, "error": "Invalid token"}), 400

    if request_id:
        ok = state.fulfill_job(request_id, token)
    else:
        # Fallback: điền cho job đầu tiên của cookie này
        ok = False
        pending = state.get_pending_jobs()
        for j in pending:
            if j.cookie_hash == cookie_hash:
                ok = state.fulfill_job(j.request_id, token)
                break

    if not ok:
        # Tạo job giả để lưu token (backward-compat)
        job = state.create_job(cookie_hash=cookie_hash)
        state.fulfill_job(job.request_id, token)
        ok = True

    write_trigger_file(len(state.get_pending_jobs()) > 0)
    print(f"  ✅ [HTTP] Token set via /set-captcha (len={len(token)}, cookie={cookie_hash[:8]}...)")
    return jsonify({"ok": ok, "tokenLength": len(token)})


@app.get("/stats")
def stats():
    return jsonify(state.stats())


# ── Background cleanup thread ─────────────────────────────────────────────────
def _cleanup_loop():
    while True:
        time.sleep(60)
        try:
            state.cleanup_old_jobs(max_age=300.0)
        except Exception:
            pass


_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
_cleanup_thread.start()


# ═══════════════════════════════════════════════════════════════════════════════
# Public API (import trong GUI)
# ═══════════════════════════════════════════════════════════════════════════════
def run_bridge_server(host: str = "127.0.0.1", port: int = 3000) -> None:
    """
    Chạy bridge server (blocking).
    Dùng được cả khi import trong GUI (chạy trong thread) lẫn CLI.
    """
    if _HAS_FLASK_SOCK:
        print(f"🌉 [Bridge] Starting WebSocket+HTTP bridge on {host}:{port}")
    else:
        print(f"🌉 [Bridge] Starting HTTP-only bridge on {host}:{port} (install flask-sock for WebSocket)")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def main() -> int:
    p = argparse.ArgumentParser(description="Extension Bridge Server for reCAPTCHA tokens")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=3000)
    args = p.parse_args()
    run_bridge_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

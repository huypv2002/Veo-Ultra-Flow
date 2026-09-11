#!/usr/bin/env python3
"""
Extension Bridge Server - WebSocket + HTTP hybrid server for Google Flow & Veo3 Ultra.

Handles:
  1. batchexecute RPC proxying (batch_rpc) through Chrome Extension running in flow.google.com
  2. reCAPTCHA Enterprise token solving via real user browser session
  3. Session metadata extraction (WIZ_global_data, at token, session ID, credits)
  4. Real-time WebSocket connection to Chrome Extension (ws://127.0.0.1:3003/ws)
  5. Synchronous HTTP API endpoints for Python callers (POST /batch-rpc, GET /credits, etc.)

Architecture:
  ┌────────────────────────────────────────────────────────┐
  │  Python GUI Tool (complete_flow.py / gui_app_mac.py)   │
  └──────────────────────────┬─────────────────────────────┘
                             │ bridge_batch_rpc() or HTTP POST /batch-rpc
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │  Bridge Server (captcha_bridge_server.py :3003)        │
  │  - WS Endpoint /ws                                     │
  │  - Thread-safe job queue & response events             │
  │  - Credit cache & health tracking                      │
  └──────────────────────────┬─────────────────────────────┘
                             │ WebSocket {method: "batch_rpc", rpcid, freq}
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │  Chrome Extension (in flow.google.com tab)             │
  │  - Executes grecaptcha.enterprise.execute() (MAIN world)│
  │  - Injects fetch('/_/AiSandboxAngularFrontend/...')     │
  │  - Inherits real cookies & WIZ_global_data.SNlM0e       │
  │  - Returns {id, status, data: response_text}            │
  └────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from flask import Flask, jsonify, request

log = logging.getLogger("captcha_bridge_server")

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
TARGET_URL = "https://flow.google.com/"
TOKEN_TTL_SECONDS = 100
JOB_TIMEOUT_SECONDS = 120
TRIGGER_FILE = Path("captcha_trigger.txt")


# ═══════════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class TokenJob:
    """Job lấy reCAPTCHA token (backward compatible)."""
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


@dataclass
class BatchRpcJob:
    """Job thực thi Google Flow batchexecute RPC qua Extension."""
    id: str
    rpcid: str
    freq: str
    captcha_action: Optional[str] = None
    timeout: int = 120
    created_at: float = field(default_factory=time.time)
    status: int = 0
    data: Optional[str] = None
    error: Optional[str] = None
    done_event: threading.Event = field(default_factory=threading.Event)

    def is_expired(self) -> bool:
        return time.time() - self.created_at > (self.timeout + 10)


class BridgeState:
    """Thread-safe state cho bridge server."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, TokenJob] = {}
        self._rpc_jobs: Dict[str, BatchRpcJob] = {}
        self._ws_clients: Set[Any] = set()
        self._ws_lock = threading.Lock()
        self._rr_index = 0
        self._ws_by_client_id: Dict[str, Any] = {}
        self._ws_by_email: Dict[str, Any] = {}
        self._connected_accounts: Dict[str, Dict[str, Any]] = {}

        # Session cache from extension
        self.session_flow_key: Optional[str] = None
        self.session_project_id: Optional[str] = None
        self.session_wiz: Dict[str, Any] = {}
        self.last_credits: Optional[int] = None
        self.last_tier: Optional[str] = None
        self.last_token_time: Optional[float] = None

        # Stats
        self.total_requested = 0
        self.total_fulfilled = 0
        self.total_rpc_requested = 0
        self.total_rpc_success = 0
        self.total_errors = 0
        self.started_at = time.time()

    # ── Token Jobs (Legacy / reCAPTCHA) ───────────────────────────────────────
    def create_job(self, cookie_hash: str, action: str = "VIDEO_GENERATION") -> TokenJob:
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
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
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
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                return False
            job.error = error
            job.done_event.set()
            self.total_errors += 1
            return True

    def get_pending_jobs(self) -> List[TokenJob]:
        with self._lock:
            return [
                j for j in self._jobs.values()
                if j.token is None and j.error is None and not j.is_expired()
            ]

    # ── Batch RPC Jobs ────────────────────────────────────────────────────────
    def create_rpc_job(
        self,
        rpcid: str,
        freq: str,
        captcha_action: Optional[str] = None,
        timeout: int = 120,
    ) -> BatchRpcJob:
        job_id = f"rpc_{uuid.uuid4().hex[:12]}"
        job = BatchRpcJob(
            id=job_id,
            rpcid=rpcid,
            freq=freq,
            captcha_action=captcha_action,
            timeout=timeout,
        )
        with self._lock:
            self._rpc_jobs[job_id] = job
            self.total_rpc_requested += 1
        return job

    def fulfill_rpc_job(self, job_id: str, status: int, data: Optional[str], error: Optional[str]) -> bool:
        with self._lock:
            job = self._rpc_jobs.get(job_id)
            if job is None:
                return False
            job.status = status
            job.data = data
            job.error = error
            job.done_event.set()
            if status == 200 and not error:
                self.total_rpc_success += 1
            else:
                self.total_errors += 1
            return True

    # ── WS Client Management ──────────────────────────────────────────────────
    def add_ws_client(self, ws) -> None:
        with self._ws_lock:
            self._ws_clients.add(ws)

    def remove_ws_client(self, ws) -> None:
        with self._ws_lock:
            self._ws_clients.discard(ws)
            dead_cids = []
            for k, v in list(self._ws_by_client_id.items()):
                if v == ws:
                    del self._ws_by_client_id[k]
                    dead_cids.append(k)
            for k, v in list(self._ws_by_email.items()):
                if v == ws:
                    del self._ws_by_email[k]
        with self._lock:
            for cid in dead_cids:
                self._connected_accounts.pop(cid, None)

    def ws_client_count(self) -> int:
        with self._ws_lock:
            return len(self._ws_clients)

    def send_ws_message(self, msg_dict: Dict[str, Any]) -> int:
        msg = json.dumps(msg_dict)
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
        if dead:
            with self._ws_lock:
                for ws in dead:
                    self._ws_clients.discard(ws)
        return sent

    def send_ws_message_single(
        self,
        msg_dict: Dict[str, Any],
        client_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """Send message to a specific or single connected extension client."""
        msg = json.dumps(msg_dict)
        ws = None
        target_email = email.strip().lower() if email else None

        with self._ws_lock:
            # 1. Match by client_id directly
            if client_id and client_id in self._ws_by_client_id:
                ws = self._ws_by_client_id[client_id]
            # 2. Match by email in _ws_by_email
            elif target_email:
                for em, s in self._ws_by_email.items():
                    if em.strip().lower() == target_email:
                        ws = s
                        break
                # Fallback: find client_id from _connected_accounts by email
                if not ws:
                    with self._lock:
                        for cid, acc in self._connected_accounts.items():
                            acc_email = (acc.get("email") or "").strip().lower()
                            if acc_email == target_email and cid in self._ws_by_client_id:
                                ws = self._ws_by_client_id[cid]
                                break
            # 3. Round robin if neither client_id nor email specified
            elif not client_id and not target_email and self._ws_clients:
                clients = list(self._ws_clients)
                ws = clients[self._rr_index % len(clients)]
                self._rr_index += 1

        if not ws:
            return False
        try:
            ws.send(msg)
            return True
        except Exception:
            with self._ws_lock:
                self._ws_clients.discard(ws)
            return False

    def broadcast_job(self, job: TokenJob) -> int:
        return self.send_ws_message({
            "type": "get_token",
            "req_id": job.request_id,
            "cookie_hash": job.cookie_hash,
            "action": job.action,
            "site_key": SITE_KEY,
            "target_url": TARGET_URL,
        })

    def execute_batch_rpc(
        self,
        rpcid: str,
        freq: str,
        captcha_action: Optional[str] = None,
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Execute a batchexecute RPC via Extension synchronously."""
        if self.ws_client_count() == 0:
            return {
                "ok": False,
                "status": 503,
                "error": "No Chrome Extension connected to bridge. Please load extension and open flow.google.com.",
            }

        job = self.create_rpc_job(
            rpcid=rpcid,
            freq=freq,
            captcha_action=captcha_action,
            timeout=timeout,
        )

        sent = self.send_ws_message_single({
            "id": job.id,
            "method": "batch_rpc",
            "params": {
                "rpcid": rpcid,
                "freq": freq,
                "captchaAction": captcha_action,
                "timeout": timeout,
            },
        }, client_id=client_id, email=email)

        if not sent:
            return {
                "ok": False,
                "status": 503,
                "error": "Failed to send batch_rpc to targeted connected extension.",
            }

        finished = job.done_event.wait(timeout=timeout + 5)
        with self._lock:
            self._rpc_jobs.pop(job.id, None)

        if not finished:
            return {
                "ok": False,
                "status": 504,
                "error": f"batch_rpc {rpcid} timed out after {timeout}s",
            }

        if job.error or job.status != 200:
            return {
                "ok": False,
                "status": job.status or 500,
                "error": job.error or f"RPC returned HTTP {job.status}",
                "data": job.data,
            }

        return {
            "ok": True,
            "status": 200,
            "data": job.data,
            "rpcid": rpcid,
        }

    def execute_api_fetch(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        captcha_action: Optional[str] = None,
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Execute REST / API fetch directly in Flow tab via Extension."""
        if self.ws_client_count() == 0:
            return {
                "ok": False,
                "status": 503,
                "error": "No Chrome Extension connected to bridge.",
            }

        job = self.create_rpc_job(
            rpcid="api_fetch",
            freq="",
            captcha_action=captcha_action,
            timeout=timeout,
        )

        sent = self.send_ws_message_single({
            "id": job.id,
            "method": "api_fetch",
            "params": {
                "url": url,
                "method": method,
                "headers": headers or {},
                "body": body,
                "captchaAction": captcha_action,
                "timeout": timeout,
            },
        }, client_id=client_id, email=email)

        if not sent:
            return {"ok": False, "status": 503, "error": "Failed to send to targeted extension"}

        finished = job.done_event.wait(timeout=timeout + 5)
        with self._lock:
            self._rpc_jobs.pop(job.id, None)

        if not finished:
            return {"ok": False, "status": 504, "error": f"api_fetch timed out after {timeout}s"}

        if job.error or job.status not in (200, 201):
            return {
                "ok": False,
                "status": job.status or 500,
                "error": job.error or f"API returned HTTP {job.status}",
                "data": job.data,
            }

        return {"ok": True, "status": 200, "data": job.data}

    def execute_get_cookies(
        self,
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """Get live browser cookies from Extension."""
        if self.ws_client_count() == 0:
            return {"ok": False, "status": 503, "error": "No Chrome Extension connected."}

        job = self.create_rpc_job(rpcid="get_cookies", freq="", timeout=timeout)
        sent = self.send_ws_message_single({
            "id": job.id,
            "method": "get_cookies",
        }, client_id=client_id, email=email)

        if not sent:
            return {"ok": False, "status": 503, "error": "Failed to send to targeted extension"}

        finished = job.done_event.wait(timeout=timeout + 5)
        with self._lock:
            self._rpc_jobs.pop(job.id, None)

        if not finished:
            return {"ok": False, "status": 504, "error": f"get_cookies timed out after {timeout}s"}

        if job.error:
            return {"ok": False, "status": job.status or 500, "error": job.error}

        return {"ok": True, "status": 200, "cookie": job.data}

    def execute_get_flow_state(
        self,
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """Get live Flow tab DOM state, video elements & media requests from Extension."""
        if self.ws_client_count() == 0:
            return {"ok": False, "status": 503, "error": "No Chrome Extension connected."}

        job = self.create_rpc_job(rpcid="get_flow_state", freq="", timeout=timeout)
        sent = self.send_ws_message_single({
            "id": job.id,
            "method": "get_flow_state",
        }, client_id=client_id, email=email)

        if not sent:
            return {"ok": False, "status": 503, "error": "Failed to send to targeted extension"}

        finished = job.done_event.wait(timeout=timeout + 5)
        with self._lock:
            self._rpc_jobs.pop(job.id, None)

        if not finished:
            return {"ok": False, "status": 504, "error": f"get_flow_state timed out after {timeout}s"}

        if job.error:
            return {"ok": False, "status": job.status or 500, "error": job.error}

        try:
            parsed = json.loads(job.data) if isinstance(job.data, str) else job.data
            return {"ok": True, "status": 200, "data": parsed}
        except Exception:
            return {"ok": True, "status": 200, "data": job.data}

    def execute_download_file(
        self,
        url: str,
        filename: str = "video.mp4",
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Trigger Chrome native download via Extension."""
        if self.ws_client_count() == 0:
            return {"ok": False, "status": 503, "error": "No Chrome Extension connected."}

        job = self.create_rpc_job(rpcid="download_file", freq=url, timeout=timeout)
        sent = self.send_ws_message_single({
            "id": job.id,
            "method": "download_file",
            "params": {"url": url, "filename": filename},
        }, client_id=client_id, email=email)

        if not sent:
            return {"ok": False, "status": 503, "error": "Failed to send to targeted extension"}

        finished = job.done_event.wait(timeout=timeout + 5)
        with self._lock:
            self._rpc_jobs.pop(job.id, None)

        if not finished:
            return {"ok": False, "status": 504, "error": f"download_file timed out after {timeout}s"}

        if job.error or job.status != 200:
            return {"ok": False, "status": job.status or 500, "error": job.error or f"HTTP {job.status}"}

        return {"ok": True, "status": 200, "data": job.data}

    def execute_bg_fetch(
        self,
        url: str,
        as_base64: bool = True,
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Fetch URL in Extension Background Service Worker (No page CSP, returns Base64 binary)."""
        if self.ws_client_count() == 0:
            return {"ok": False, "status": 503, "error": "No Chrome Extension connected."}

        job = self.create_rpc_job(rpcid="bg_fetch", freq=url, timeout=timeout)
        sent = self.send_ws_message_single({
            "id": job.id,
            "method": "bg_fetch",
            "params": {"url": url, "asBase64": as_base64},
        }, client_id=client_id, email=email)

        if not sent:
            return {"ok": False, "status": 503, "error": "Failed to send to targeted extension"}

        finished = job.done_event.wait(timeout=timeout + 5)
        with self._lock:
            self._rpc_jobs.pop(job.id, None)

        if not finished:
            return {"ok": False, "status": 504, "error": f"bg_fetch timed out after {timeout}s"}

        if job.error or job.status != 200:
            return {"ok": False, "status": job.status or 500, "error": job.error or f"HTTP {job.status}"}

        return {"ok": True, "status": 200, "data": job.data}

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pending_tokens = sum(
                1 for j in self._jobs.values()
                if j.token is None and j.error is None and not j.is_expired()
            )
            pending_rpcs = sum(
                1 for j in self._rpc_jobs.values()
                if not j.done_event.is_set() and not j.is_expired()
            )
        return {
            "uptime_seconds": int(time.time() - self.started_at),
            "ws_clients": self.ws_client_count(),
            "pending_tokens": pending_tokens,
            "pending_rpcs": pending_rpcs,
            "total_requested": self.total_requested,
            "total_fulfilled": self.total_fulfilled,
            "total_rpc_requested": self.total_rpc_requested,
            "total_rpc_success": self.total_rpc_success,
            "total_errors": self.total_errors,
            "has_flow_session": bool(self.session_flow_key or self.session_wiz),
            "credits": self.last_credits,
            "tier": self.last_tier,
        }


# ── Global Singleton State ───────────────────────────────────────────────────
state = BridgeState()
_server_thread: Optional[threading.Thread] = None
_server_lock = threading.Lock()


def write_trigger_file(needs_token: bool) -> None:
    try:
        TRIGGER_FILE.write_text("1" if needs_token else "0", encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Flask Application & WebSocket Endpoints
# ═══════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
sock = Sock(app) if _HAS_FLASK_SOCK else None


if _HAS_FLASK_SOCK and sock is not None:
    @sock.route("/ws")
    def websocket_endpoint(ws):
        """Chrome Extension kết nối WS: xử lý batch_rpc, token_captured, solve_captcha."""
        state.add_ws_client(ws)
        client_id = f"ext-{uuid.uuid4().hex[:6]}"
        print(f"🔌 [WS] Extension connected (id={client_id}, total={state.ws_client_count()})")

        # Ack handshake
        try:
            ws.send(json.dumps({
                "type": "connected",
                "client_id": client_id,
                "site_key": SITE_KEY,
                "target_url": TARGET_URL,
            }))
        except Exception:
            pass

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
                req_id = data.get("id") or data.get("req_id") or ""
                print(f"  📥 [WS RAW] id={req_id[:8]} type={msg_type} keys={list(data.keys())}")

                # 1. Heartbeat
                if msg_type == "ping":
                    try:
                        ws.send(json.dumps({"type": "pong"}))
                    except Exception:
                        break

                # 2. Response từ batch_rpc
                elif "status" in data and ("data" in data or "error" in data):
                    status = data.get("status", 200)
                    resp_data = data.get("data")
                    resp_error = data.get("error")
                    state.fulfill_rpc_job(req_id, status=status, data=resp_data, error=resp_error)

                # 3. Response từ get_token / solve_captcha
                elif msg_type == "token_result":
                    token = data.get("token", "")
                    error = data.get("error", "")
                    if token and len(token) > 20:
                        state.fulfill_job(req_id, token)
                        write_trigger_file(len(state.get_pending_jobs()) > 0)
                    elif error:
                        state.fail_job(req_id, error)
                    else:
                        state.fail_job(req_id, "Empty token from extension")

                # 4. Token & Session capture
                elif msg_type == "token_captured":
                    state.session_flow_key = data.get("flowKey") or state.session_flow_key
                    state.session_project_id = data.get("projectId") or state.session_project_id
                    wiz = data.get("wiz")
                    if isinstance(wiz, dict):
                        state.session_wiz.update(wiz)
                    state.last_token_time = time.time()
                    print(f"  🔑 [WS] Flow session synced from extension (proj={state.session_project_id})")

                # 5. Extension ready status
                elif msg_type in ("extension_ready", "register"):
                    label = data.get("client_label") or data.get("clientId") or client_id
                    print(f"  ✨ [WS] Extension ready: {label}")
                    try:
                        ws.send(json.dumps({"type": "register_ack", "client_id": client_id}))
                    except Exception:
                        break

                # 6. Account info (Gmail, Credits, Plan)
                elif msg_type == "account_info":
                    cid = data.get("clientId") or client_id
                    email = data.get("email") or f"Profile ({cid})"
                    credits = data.get("credits", 0)
                    tier = data.get("tier", "TIER_2")
                    raw_plan = data.get("plan") or ""
                    tier_str = str(tier).upper()
                    if "2" in tier_str or "TWO" in tier_str or "ULTRA" in raw_plan.upper():
                        plan = "Ultra (Tier 2)"
                    elif "1" in tier_str or "ONE" in tier_str or "3" in tier_str or "PRO" in raw_plan.upper():
                        plan = "Pro (Tier 1)"
                    cookie = data.get("cookie") or ""
                    raw_at = data.get("access_token") or data.get("flowKey") or ""
                    access_token = raw_at if (raw_at and raw_at.startswith("ya29.")) else (state.session_flow_key if (state.session_flow_key and state.session_flow_key.startswith("ya29.")) else "")
                    if access_token:
                        state.session_flow_key = access_token
                    state.last_credits = credits
                    state.last_tier = plan
                    with state._ws_lock:
                        state._ws_by_client_id[cid] = ws
                        state._ws_by_email[email] = ws
                    with state._lock:
                        state._connected_accounts[cid] = {
                            "client_id": cid,
                            "email": email,
                            "credits": credits,
                            "tier": tier,
                            "plan": plan,
                            "cookie": cookie,
                            "access_token": access_token,
                            "status": "🟢 Live (Extension)",
                            "source": f"🌐 Chrome Profile ({cid})",
                            "last_seen": time.time(),
                        }
                    print(f"  👤 [WS] Account info synced: {email} | {plan} | {credits} credits (has_cookie={bool(cookie)}, has_at={bool(access_token)})")

        except Exception as e:
            print(f"  ⚠️ [WS] Extension {client_id} disconnected: {e}")
        finally:
            state.remove_ws_client(ws)
            with state._lock:
                if client_id in state._connected_accounts:
                    state._connected_accounts[client_id]["status"] = "⚪ Disconnected"
            print(f"🔌 [WS] Extension disconnected (remaining={state.ws_client_count()})")


# ── HTTP Endpoints ────────────────────────────────────────────────────────────
@app.get("/accounts")
def get_accounts_endpoint():
    """Return all connected accounts with email, plan, credits."""
    accounts = []
    with state._lock:
        with state._ws_lock:
            active_cids = set(state._ws_by_client_id.keys())
        for cid, acc in state._connected_accounts.items():
            if cid not in active_cids:
                continue
            # Standardize plan name
            p = acc.get("plan", "")
            t = str(acc.get("tier", "")).upper()
            if "2" in t or "TWO" in t:
                acc["plan"] = "Ultra (Tier 2)"
            elif "1" in t or "ONE" in t or "3" in t:
                acc["plan"] = "Pro (Tier 1)"
            accounts.append(acc)
    return jsonify({
        "ok": True,
        "count": len(accounts),
        "accounts": accounts,
    })


@app.get("/health")
def health():
    """Health check & status summary."""
    s = state.stats()
    s["ws_enabled"] = _HAS_FLASK_SOCK
    return jsonify(s)


@app.post("/batch-rpc")
def batch_rpc_endpoint():
    """Execute batchexecute RPC synchronously through the connected Chrome Extension."""
    payload = request.get_json(silent=True) or {}
    rpcid = payload.get("rpcid", "")
    freq = payload.get("freq", "")
    captcha_action = payload.get("captcha_action") or payload.get("captchaAction")
    client_id = payload.get("client_id")
    email = payload.get("email")
    timeout = int(payload.get("timeout", 120))

    if not rpcid or not freq:
        return jsonify({"ok": False, "error": "Missing rpcid or freq parameter"}), 400

    result = state.execute_batch_rpc(
        rpcid=rpcid,
        freq=freq,
        captcha_action=captcha_action,
        client_id=client_id,
        email=email,
        timeout=timeout,
    )
    http_code = 200 if result.get("ok") else 502
    return jsonify(result), http_code


@app.post("/api-fetch")
def api_fetch_endpoint():
    """Execute REST API fetch inside Flow tab through the connected Chrome Extension."""
    payload = request.get_json(silent=True) or {}
    url = payload.get("url", "")
    method = payload.get("method", "POST")
    headers = payload.get("headers", {})
    body = payload.get("body")
    captcha_action = payload.get("captcha_action") or payload.get("captchaAction")
    client_id = payload.get("client_id")
    email = payload.get("email")
    timeout = int(payload.get("timeout", 120))

    if not url:
        return jsonify({"ok": False, "error": "Missing url parameter"}), 400

    result = state.execute_api_fetch(
        url=url,
        method=method,
        headers=headers,
        body=body,
        captcha_action=captcha_action,
        client_id=client_id,
        email=email,
        timeout=timeout,
    )
    http_code = 200 if result.get("ok") else 502
    return jsonify(result), http_code


@app.get("/cookies")
def get_cookies_route():
    """Get live cookies from targeted Chrome Extension profile."""
    email = request.args.get("email")
    client_id = request.args.get("client_id")
    result = state.execute_get_cookies(client_id=client_id, email=email)
    http_code = 200 if result.get("ok") else 502
    return jsonify(result), http_code


@app.get("/flow-state")
def get_flow_state_route():
    """Get live Flow tab state, video URLs, and DOM info."""
    email = request.args.get("email")
    client_id = request.args.get("client_id")
    result = state.execute_get_flow_state(client_id=client_id, email=email)
    http_code = 200 if result.get("ok") else 502
    return jsonify(result), http_code


@app.post("/reload-extension")
def reload_extension_endpoint():
    """Trigger chrome.runtime.reload() in connected extensions."""
    state.send_ws_message({"method": "reload"})
    return jsonify({"ok": True, "message": "Reload signal broadcasted to extensions"})


@app.post("/download-file")
def download_file_endpoint():
    """Trigger native Chrome file download via connected extension."""
    payload = request.get_json(silent=True) or {}
    url = payload.get("url", "")
    filename = payload.get("filename", "video.mp4")
    client_id = payload.get("client_id")
    email = payload.get("email")
    timeout = int(payload.get("timeout", 60))
    if not url:
        return jsonify({"ok": False, "error": "Missing url parameter"}), 400
    result = state.execute_download_file(url=url, filename=filename, client_id=client_id, email=email, timeout=timeout)
    http_code = 200 if result.get("ok") else 502
    return jsonify(result), http_code


@app.post("/bg-fetch")
def bg_fetch_endpoint():
    """Fetch URL inside extension background service worker with all cookies and host permissions."""
    payload = request.get_json(silent=True) or {}
    url = payload.get("url", "")
    as_base64 = payload.get("as_base64", True)
    client_id = payload.get("client_id")
    email = payload.get("email")
    timeout = int(payload.get("timeout", 120))
    if not url:
        return jsonify({"ok": False, "error": "Missing url parameter"}), 400
    result = state.execute_bg_fetch(url=url, as_base64=as_base64, client_id=client_id, email=email, timeout=timeout)
    http_code = 200 if result.get("ok") else 502
    return jsonify(result), http_code


@app.get("/credits")
def get_credits_endpoint():
    """Query live account credits using RPC nzlxg."""
    try:
        from flow_batch import credits_request, first_payload, read_credits, RPC_CREDITS
        freq = credits_request()
        result = state.execute_batch_rpc(rpcid=RPC_CREDITS, freq=freq, timeout=30)
        if not result.get("ok"):
            return jsonify({
                "ok": False,
                "error": result.get("error", "RPC call failed"),
                "total_credits": state.last_credits or 0,
            }), 502

        payload = first_payload(result.get("data", ""), RPC_CREDITS)
        credits, tier = read_credits(payload)
        state.last_credits = credits
        state.last_tier = tier
        return jsonify({
            "ok": True,
            "credits": credits,
            "total_credits": credits,
            "userPaygateTier": tier,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "total_credits": state.last_credits or 0}), 500


@app.post("/request-token")
def request_token():
    """Create token job (backward compatible)."""
    data = request.get_json(silent=True) or {}
    cookie_hash = data.get("cookie_hash", "default")
    action = data.get("action", "VIDEO_GENERATION")

    job = state.create_job(cookie_hash, action)
    ws_sent = state.broadcast_job(job)
    write_trigger_file(True)

    return jsonify({
        "status": "pending",
        "request_id": job.request_id,
        "cookie_hash": job.cookie_hash,
        "action": job.action,
        "ws_sent": ws_sent,
    })


@app.get("/get-captcha")
def get_captcha():
    """Poll token result (backward compatible)."""
    request_id = request.args.get("request_id", "")
    cookie_hash = request.args.get("cookie_hash", "")
    clear = request.args.get("clear", "1") == "1"

    job = state.get_job(request_id) if request_id else None
    if job is None and cookie_hash:
        for j in state.get_pending_jobs():
            if j.cookie_hash == cookie_hash:
                job = j
                break

    if job is None:
        return jsonify({"pending": False, "error": "Job not found or expired"}), 404

    if job.token:
        token = job.token
        if clear:
            with state._lock:
                state._jobs.pop(job.request_id, None)
        return jsonify({"pending": False, "token": token, "error": None})

    if job.error:
        err = job.error
        if clear:
            with state._lock:
                state._jobs.pop(job.request_id, None)
        return jsonify({"pending": False, "token": None, "error": err})

    return jsonify({"pending": True, "token": None, "error": None})


@app.get("/check-trigger")
def check_trigger():
    pending = state.get_pending_jobs()
    return jsonify({"needs_token": len(pending) > 0, "count": len(pending)})


# ═══════════════════════════════════════════════════════════════════════════════
# Direct Python In-Process & HTTP Helper
# ═══════════════════════════════════════════════════════════════════════════════
def bridge_batch_rpc(
    rpcid: str,
    freq: str,
    captcha_action: Optional[str] = None,
    timeout: int = 120,
    server_url: str = "http://127.0.0.1:3003",
) -> Dict[str, Any]:
    """Execute batchexecute RPC.

    If bridge server is running inside this same Python process, executes directly
    via BridgeState. Otherwise, makes an HTTP POST to server_url/batch-rpc.
    """
    # 1. In-process direct execution
    if state.ws_client_count() > 0:
        return state.execute_batch_rpc(
            rpcid=rpcid,
            freq=freq,
            captcha_action=captcha_action,
            timeout=timeout,
        )

    # 2. HTTP POST fallback to running bridge process
    url = f"{server_url.rstrip('/')}/batch-rpc"
    try:
        resp = requests.post(
            url,
            json={
                "rpcid": rpcid,
                "freq": freq,
                "captcha_action": captcha_action,
                "timeout": timeout,
            },
            timeout=timeout + 10,
        )
        data = resp.json()
        return data
    except Exception as e:
        return {
            "ok": False,
            "status": 500,
            "error": f"Bridge request failed: {e}",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Lifecycle Management
# ═══════════════════════════════════════════════════════════════════════════════
def run_bridge_server(host: str = "127.0.0.1", port: int = 3003):
    """Run Flask server in current thread."""
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def ensure_captcha_bridge_server(server_url: str = "http://127.0.0.1:3003", auto_start: bool = True) -> bool:
    """Ensure the bridge server is up and running. Start in background daemon thread if not."""
    global _server_thread
    server_url = (server_url or "http://127.0.0.1:3003").rstrip("/")

    # Check if already running
    try:
        r = requests.get(f"{server_url}/health", timeout=1.5)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    if not auto_start:
        return False

    with _server_lock:
        if _server_thread is not None and _server_thread.is_alive():
            return True

        import urllib.parse
        parsed = urllib.parse.urlparse(server_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 3003

        _server_thread = threading.Thread(
            target=run_bridge_server,
            kwargs={"host": host, "port": port},
            daemon=True,
            name="CaptchaBridgeServerThread",
        )
        _server_thread.start()
        print(f"🚀 [BridgeServer] Started in background on {host}:{port}")

    # Wait up to 5s for server to become responsive
    deadline = time.time() + 5.0
    while time.time() < deadline:
        time.sleep(0.3)
        try:
            r = requests.get(f"{server_url}/health", timeout=1.0)
            if r.status_code == 200:
                print(f"✅ [BridgeServer] Ready on {server_url}")
                return True
        except Exception:
            pass

    print(f"⚠️ [BridgeServer] Timed out waiting for {server_url}/health")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Veo3 Ultra Extension Bridge Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=3003, help="Bind port (default: 3003)")
    args = parser.parse_args()
    print(f"🚀 Starting Extension Bridge Server on {args.host}:{args.port}...")
    run_bridge_server(host=args.host, port=args.port)

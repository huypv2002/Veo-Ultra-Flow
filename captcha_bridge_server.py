#!/usr/bin/env python3
"""
Local bridge server for the Chrome extension in `ex/`.

The extension:
  - polls GET  /check-trigger  -> { needsToken: boolean }
  - sends POST /set-captcha    -> { token: "..." }

This server additionally provides:
  - POST /request-token        -> sets needsToken=true (so extension will fetch)
  - GET  /get-captcha          -> returns last token (optionally clears it)

IMPROVEMENT: Now also writes tokens to file for faster Python script access.

Run:
  pip install flask
  python captcha_bridge_server.py --host 127.0.0.1 --port 3000
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

from flask import Flask, jsonify, request


@dataclass
class State:
    needs_token: bool = False
    # ✅ Multi-cookie: Lưu token riêng cho từng cookie_hash
    # Format: {cookie_hash: {"token": str, "received_at": float, "needs_token": bool}}
    tokens_by_cookie: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# File paths for token storage (fast file-based access)
# ✅ Multi-cookie: Files will include cookie_hash in filename
TRIGGER_FILE = Path("captcha_trigger.txt")


# ✅ Đã bỏ ghi file - chỉ dùng HTTP polling


# ✅ Đã bỏ xóa file - không còn ghi file nữa


def write_trigger_file(needs_token: bool) -> None:
    """Write trigger state to file."""
    try:
        with open(TRIGGER_FILE, "w", encoding="utf-8") as f:
            f.write("1" if needs_token else "0")
    except Exception:
        pass


app = Flask(__name__)
state = State()


@app.get("/check-trigger")
def check_trigger():
    # ✅ PARALLEL: Trả về TẤT CẢ pending requests để extension xử lý song song
    pending_list = []
    
    for cookie_hash, cookie_data in state.tokens_by_cookie.items():
        pending = cookie_data.get("pending_requests", {})
        for req_id, req_data in pending.items():
            if req_data.get("token") is None:
                pending_list.append({
                    "cookie_hash": cookie_hash,
                    "request_id": req_id
                })
    
    any_pending = len(pending_list) > 0
    state.needs_token = any_pending
    write_trigger_file(any_pending)

    response_data = {
        "needsToken": any_pending,
        "pendingRequests": pending_list,  # ✅ Trả về TẤT CẢ pending requests
        "pendingCount": len(pending_list),
    }
    
    # ✅ Backward compatible: Vẫn trả về 1 request đầu tiên
    if pending_list:
        response_data["cookie_hash"] = pending_list[0]["cookie_hash"]
        response_data["request_id"] = pending_list[0]["request_id"]

    return jsonify(response_data)


@app.post("/request-token")
def request_token():
    # ✅ Multi-cookie: Nhận cookie_hash + request_id từ request
    data = request.get_json(silent=True) or {}
    cookie_hash = data.get("cookie_hash") or "default"
    request_id = data.get("request_id")  # ✅ Request ID để phân biệt các request
    
    # ✅ Khởi tạo entry cho cookie_hash này nếu chưa có
    if cookie_hash not in state.tokens_by_cookie:
        state.tokens_by_cookie[cookie_hash] = {
            "token": None,
            "received_at": None,
            "needs_token": False,
            "pending_requests": {}  # ✅ Track các request đang chờ token
        }
    
    # ✅ Khởi tạo entry cho request_id này trong pending_requests
    if "pending_requests" not in state.tokens_by_cookie[cookie_hash]:
        state.tokens_by_cookie[cookie_hash]["pending_requests"] = {}
    
    if request_id:
        state.tokens_by_cookie[cookie_hash]["pending_requests"][request_id] = {
            "token": None,
            "received_at": None,
            "requested_at": time.time()
        }
    
    # ✅ Mark that the next /check-trigger should cause the extension to fetch a token.
    state.needs_token = True  # Global flag để extension check
    state.tokens_by_cookie[cookie_hash]["needs_token"] = True
    # ✅ KHÔNG clear token cũ ngay - để các request khác có thể dùng nếu chưa có request mới
    
    write_trigger_file(True)
    
    print(f"📡 Token request received (cookie_hash: {cookie_hash}, request_id: {request_id[-8:] if request_id else 'none'}) - Extension sẽ tự động lấy token")
    return jsonify({"ok": True, "needsToken": True, "cookie_hash": cookie_hash, "request_id": request_id})


@app.post("/set-captcha")
def set_captcha():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    cookie_hash = data.get("cookie_hash") or "default"  # ✅ Multi-cookie: Nhận cookie_hash từ extension
    
    if not token or not isinstance(token, str):
        return jsonify({"ok": False, "error": "Missing token"}), 400

    # ✅ Validate token length (basic check)
    if len(token) < 10:
        return jsonify({"ok": False, "error": "Invalid token (too short)"}), 400

    # ✅ Khởi tạo entry cho cookie_hash này nếu chưa có
    if cookie_hash not in state.tokens_by_cookie:
        state.tokens_by_cookie[cookie_hash] = {
            "token": None,
            "received_at": None,
            "needs_token": False,
            "pending_requests": {}
        }

    cookie_data = state.tokens_by_cookie[cookie_hash]

    # ✅ Lưu token cho cookie (token chung – có thể dùng fallback)
    cookie_data["token"] = token
    cookie_data["received_at"] = time.time()

    # ✅ Nhận request_id từ extension (nếu có)
    request_id_from_ext = data.get("request_id")

    # ✅ Gán token cho pending_request tương ứng (nếu có)
    pending = cookie_data.get("pending_requests", {})
    if pending:
        if request_id_from_ext and request_id_from_ext in pending:
            pending[request_id_from_ext]["token"] = token
            pending[request_id_from_ext]["received_at"] = time.time()
        else:
            # Nếu không có request_id (fallback), gán cho tất cả request chưa có token
            for req_id, req_data in pending.items():
                if req_data.get("token") is None:
                    req_data["token"] = token
                    req_data["received_at"] = time.time()

    # ✅ Cập nhật needs_token cho cookie này: còn request nào chưa có token không?
    still_pending = any(
        req.get("token") is None
        for req in cookie_data.get("pending_requests", {}).values()
    )
    cookie_data["needs_token"] = still_pending

    # ✅ Cập nhật needs_token toàn cục
    state.needs_token = any(
        entry.get("needs_token", False) for entry in state.tokens_by_cookie.values()
    )
    write_trigger_file(state.needs_token)

    print(
        f"✓ Token received and saved for cookie_hash: {cookie_hash} "
        f"(length: {len(token)}), still_pending_for_cookie={still_pending}"
    )
    return jsonify({"ok": True, "tokenLength": len(token), "cookie_hash": cookie_hash})


@app.get("/get-captcha")
def get_captcha():
    clear = request.args.get("clear", "1") not in ("0", "false", "False")
    cookie_hash = request.args.get("cookie_hash") or "default"  # ✅ Multi-cookie: Nhận cookie_hash từ request
    request_id = request.args.get("request_id")  # ✅ Request ID để phân biệt các request
    
    # ✅ Đảm bảo entry tồn tại cho cookie_hash này
    if cookie_hash not in state.tokens_by_cookie:
        state.tokens_by_cookie[cookie_hash] = {
            "token": None,
            "received_at": None,
            "needs_token": False,
            "pending_requests": {}
        }
    
    cookie_data = state.tokens_by_cookie[cookie_hash]
    
    # ✅ Ưu tiên lấy token từ request_id trong pending_requests nếu có
    token = None
    received_at = None
    if request_id and "pending_requests" in cookie_data:
        req_data = cookie_data["pending_requests"].get(request_id)
        if req_data:
            token = req_data.get("token")
            received_at = req_data.get("received_at")
    
    # ✅ Fallback: Lấy token chung của cookie_hash
    if not token:
        token = cookie_data.get("token")
        received_at = cookie_data.get("received_at")
    
    needs_token = cookie_data.get("needs_token", False)
    
    payload = {
        "ok": True,
        "token": token,
        "receivedAt": received_at,
        "needsToken": needs_token,
        "cookie_hash": cookie_hash,
        "request_id": request_id,
    }
    
    # ✅ Chỉ clear token khi được yêu cầu VÀ có token
    if clear and token:
        # ✅ Nếu có request_id, chỉ clear token của request đó trong pending_requests
        if request_id and "pending_requests" in cookie_data:
            if request_id in cookie_data["pending_requests"]:
                cookie_data["pending_requests"][request_id]["token"] = None
                del cookie_data["pending_requests"][request_id]
                print(f"✓ Token cleared for request_id: {request_id[-8:] if request_id else 'none'} (cookie_hash: {cookie_hash})")
        
        # ✅ Chỉ clear token chung nếu không còn pending requests nào
        if not cookie_data.get("pending_requests") or len(cookie_data.get("pending_requests", {})) == 0:
            state.tokens_by_cookie[cookie_hash]["token"] = None
            state.tokens_by_cookie[cookie_hash]["received_at"] = None
            state.tokens_by_cookie[cookie_hash]["needs_token"] = False
        
        # ✅ Check xem còn cookie nào cần token không
        any_needs = any(entry.get("needs_token", False) for entry in state.tokens_by_cookie.values())
        state.needs_token = any_needs
        
        if not request_id:
            print(f"✓ Token cleared for cookie_hash: {cookie_hash} (length was: {len(token)})")
    
    return jsonify(payload)


def run_bridge_server(host: str = "127.0.0.1", port: int = 3000) -> None:
    """Run the captcha bridge Flask server (blocking call).

    Dùng được cả khi import trong GUI (chạy trong thread) lẫn khi chạy trực tiếp.
    """
    # ⚠️ Quan trọng: use_reloader=False để tránh Flask tạo thêm process phụ
    app.run(host=host, port=port, debug=False, use_reloader=False)


def main() -> int:
    p = argparse.ArgumentParser(description="Local token bridge for the ex/ extension")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=3000)
    args = p.parse_args()
    run_bridge_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



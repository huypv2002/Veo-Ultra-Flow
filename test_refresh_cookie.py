#!/usr/bin/env python3
"""
Test script để thử chức năng refresh cookie khi bị 403.
"""
import asyncio
import os
import sys

# Thêm thư mục hiện tại vào path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set env trước khi import LabsFlowClient
os.environ["AUTO_RECAPTCHA"] = "1"
os.environ["RECAPTCHA_MODE"] = "selenium"

from complete_flow import LabsFlowClient


async def test_refresh_cookie():
    """Test refresh cookie với cookies giả lập."""
    
    print("=" * 60)
    print("🧪 TEST: Refresh Cookie khi bị 403")
    print("=" * 60)
    
    # Tạo cookies giả lập (3 cookies cần thiết)
    test_cookies = {
        "__Host-next-auth.csrf-token": "test_csrf_token_value",
        "__Secure-next-auth.callback-url": "https://labs.google/fx",
        "__Secure-next-auth.session-token": "test_session_token_value",
    }
    
    # Khởi tạo client với cookies giả lập
    client = LabsFlowClient(
        cookies=test_cookies,
    )
    
    print(f"\n📋 Cookie hash ban đầu: {client._cookie_hash[:8]}...")
    print(f"📋 Cookies ban đầu: {list(client.cookies.keys())}")
    
    # Khởi động zendriver worker
    print("\n🚀 Đang khởi động zendriver worker...")
    LabsFlowClient._ensure_zendriver_worker()
    
    # Đợi browser sẵn sàng
    print("⏳ Đợi browser sẵn sàng...")
    wait_start = time.time()
    while LabsFlowClient._zendriver_browser is None and LabsFlowClient._zendriver_started:
        if time.time() - wait_start > 30:
            print("  ⚠️ Timeout khởi tạo browser")
            break
        await asyncio.sleep(0.2)
    
    if LabsFlowClient._zendriver_browser:
        print("  ✅ Browser đã sẵn sàng")
    else:
        print("  ❌ Browser chưa sẵn sàng")
        return
    
    # Test: Gọi refresh cookie
    print("\n--- Test: Gọi _refresh_cookie_on_403() ---")
    result = client._refresh_cookie_on_403()
    print(f"✅ Refresh kết quả: {result}")
    
    print(f"\n📋 Cookies sau refresh: {client.cookies}")
    
    print("\n" + "=" * 60)
    print("🧪 TEST COMPLETE")
    print("=" * 60)


import time

def main():
    """Entry point."""
    asyncio.run(test_refresh_cookie())


if __name__ == "__main__":
    main()

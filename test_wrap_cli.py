import requests
import subprocess
import time

TEST_URL = "https://httpbin.org/ip"
RETRIES = 2


# ==============================
# WARP CONTROL
# ==============================
def warp_connect():
    subprocess.run(["warp-cli", "connect"], stdout=subprocess.DEVNULL)


def warp_disconnect():
    subprocess.run(["warp-cli", "disconnect"], stdout=subprocess.DEVNULL)


def rotate_warp():
    print("\n🔄 Rotating WARP IP...")

    old_ip = get_ip()
    print(f"👉 IP BEFORE: {old_ip}")

    warp_disconnect()
    time.sleep(2)

    warp_connect()
    time.sleep(4)

    new_ip = get_ip()
    print(f"👉 IP AFTER : {new_ip}")

    if old_ip == new_ip:
        print("⚠️ IP KHÔNG ĐỔI")
    else:
        print("✅ IP ĐÃ ĐỔI")


# ==============================
# UTIL
# ==============================
def get_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=5).text
    except:
        return "unknown"


# ==============================
# MAIN LOGIC
# ==============================
def call_api(url):
    for attempt in range(1, RETRIES + 1):
        print(f"\n🌐 Attempt {attempt}")

        current_ip = get_ip()
        print(f"👉 Current IP: {current_ip}")

        try:
            res = requests.get(url, timeout=10)

            # ép test rotate cho bạn luôn (bạn có thể xoá dòng này sau)
            if attempt == 1:
                print("🧪 Force rotate để test")
                rotate_warp()
                continue

            if res.status_code == 403:
                print("❌ 403 detected")
                rotate_warp()
                continue

            print("✅ Success")
            return res.text

        except Exception as e:
            print("⚠️ Error:", e)
            rotate_warp()

    raise Exception("Failed")


# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    print("🚀 Test WARP IP change...\n")
    result = call_api(TEST_URL)

    print("\n📦 Response:")
    print(result)
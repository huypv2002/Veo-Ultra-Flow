import os
import platform
import subprocess
import sys
from pathlib import Path

from chrome_profile_utils import resolve_chrome_profile


def find_chrome_binary():
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
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def main():
    if len(sys.argv) < 2:
        print('Usage: python launch_real_profile_cdp.py "/Users/.../Google/Chrome/Default" [port]')
        sys.exit(1)

    profile_path = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9222
    chrome = find_chrome_binary()
    if not chrome:
        print("Khong tim thay Chrome")
        sys.exit(1)

    info = resolve_chrome_profile(profile_path)
    user_data_dir = info["user_data_dir"] or profile_path
    profile_directory = info["profile_directory"]

    args = [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
    ]
    if profile_directory:
        args.append(f"--profile-directory={profile_directory}")
    args.append("https://labs.google/fx/tools/flow")

    print("Launching external Chrome CDP:")
    for arg in [chrome, *args]:
        print(arg)

    if platform.system() == "Darwin":
        app_bundle = chrome
        chrome_path_obj = Path(chrome)
        for parent in chrome_path_obj.parents:
            if parent.suffix == ".app":
                app_bundle = str(parent)
                break
        subprocess.Popen(
            ["open", "-n", "-a", app_bundle, "--args", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen([chrome, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"\nDa mo Chrome CDP tren port {port}.")
    print("Giu cua so nay dang mo, roi chay gui_app_mac.py o terminal khac.")


if __name__ == "__main__":
    main()

import re
import os
import platform
from pathlib import Path
from typing import Dict, Optional


PROFILE_DIR_NAMES = {
    "Default",
    "Guest Profile",
    "System Profile",
}


def _looks_like_profile_dir_name(name: str) -> bool:
    return name in PROFILE_DIR_NAMES or bool(re.fullmatch(r"Profile \d+", name))


def resolve_chrome_profile(profile_path: str) -> Dict[str, Optional[str]]:
    """
    Normalize a profile path so the app can accept both:
    - a standalone user-data-dir managed by the tool
    - a real Chrome profile path like ~/Library/.../Google/Chrome/Default
    - a real Chrome user-data-dir root like ~/Library/.../Google/Chrome
    """
    path = Path(profile_path).expanduser()

    if not profile_path:
        return {
            "input_path": "",
            "user_data_dir": "",
            "profile_directory": None,
            "profile_storage_path": "",
            "is_real_chrome_profile": False,
        }

    if _looks_like_profile_dir_name(path.name) and (path.parent / "Local State").exists():
        return {
            "input_path": str(path),
            "user_data_dir": str(path.parent),
            "profile_directory": path.name,
            "profile_storage_path": str(path),
            "is_real_chrome_profile": True,
        }

    if (path / "Local State").exists():
        default_dir = path / "Default"
        if default_dir.exists():
            return {
                "input_path": str(path),
                "user_data_dir": str(path),
                "profile_directory": "Default",
                "profile_storage_path": str(default_dir),
                "is_real_chrome_profile": True,
            }
        return {
            "input_path": str(path),
            "user_data_dir": str(path),
            "profile_directory": None,
            "profile_storage_path": str(path),
            "is_real_chrome_profile": True,
        }

    return {
        "input_path": str(path),
        "user_data_dir": str(path),
        "profile_directory": None,
        "profile_storage_path": str(path),
        "is_real_chrome_profile": False,
    }


def get_cookie_db_candidates(profile_path: str):
    info = resolve_chrome_profile(profile_path)
    storage = Path(info["profile_storage_path"] or profile_path).expanduser()
    candidates = [
        storage / "Network" / "Cookies",
        storage / "Cookies",
    ]
    if info.get("profile_directory") is None:
        candidates.extend([
            storage / "Default" / "Network" / "Cookies",
            storage / "Default" / "Cookies",
        ])
    deduped = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def is_managed_profile_path(profile_path: str, managed_root: str) -> bool:
    if not profile_path or not managed_root:
        return False
    try:
        path = Path(profile_path).expanduser().resolve()
        root = Path(managed_root).expanduser().resolve()
        path.relative_to(root)
        return True
    except Exception:
        return False


def get_default_system_chrome_profile_path() -> str:
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        for candidate in [base / "Default", base / "Profile 1", base]:
            if candidate.exists():
                return str(candidate)
        return str(base / "Default")
    if system == "Windows":
        base = Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data"))
        for candidate in [base / "Default", base / "Profile 1", base]:
            if candidate.exists():
                return str(candidate)
        return str(base / "Default")
    base = Path.home() / ".config" / "google-chrome"
    for candidate in [base / "Default", base / "Profile 1", base]:
        if candidate.exists():
            return str(candidate)
    return str(base / "Default")


def get_system_chrome_user_data_dir() -> str:
    system = platform.system()
    if system == "Darwin":
        return str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome")
    if system == "Windows":
        return str(Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")))
    return str(Path.home() / ".config" / "google-chrome")


def get_tool_system_chrome_profile_path() -> str:
    """
    Return the recommended real Chrome profile path for this tool.

    We intentionally prefer a dedicated persistent Chrome user-data-dir that is
    separate from the user's main Chrome root. Using Chrome's shared root
    (Default / Profile 1 / Profile 2 under the same user-data-dir) is not
    reliable for CDP because an already-running Chrome instance can swallow the
    relaunch and never expose the requested remote debugging port.
    """
    system = platform.system()
    if system == "Darwin":
        return str(Path.home() / "GetCookieVeo3" / "chrome_tool_profile")
    elif system == "Windows":
        return str(Path(os.path.expandvars(r"%LocalAppData%\GetCookieVeo3\chrome_tool_profile")))
    return str(Path.home() / ".config" / "getcookieveo3-chrome-tool-profile")


def get_tool_account_profile_path(email: str) -> str:
    safe = re.sub(r"[^a-z0-9._-]+", "_", (email or "default").strip().lower().replace("@", "_at_"))
    system = platform.system()
    if system == "Darwin":
        return str(Path.home() / "GetCookieVeo3" / "profiles" / safe)
    if system == "Windows":
        return str(Path(os.path.expandvars(r"%LocalAppData%\GetCookieVeo3\profiles")) / safe)
    return str(Path.home() / ".config" / "getcookieveo3" / "profiles" / safe)


def is_shared_system_chrome_profile_path(profile_path: str) -> bool:
    """
    Returns True when the path points into the user's main Chrome user-data-dir
    (Default/Profile N under the shared Chrome root). These paths are not stable
    for CDP relaunch because the main Chrome instance can absorb the relaunch and
    never expose the requested remote debugging port.
    """
    if not profile_path:
        return False
    info = resolve_chrome_profile(profile_path)
    if not info.get("is_real_chrome_profile"):
        return False
    try:
        current = Path(info["user_data_dir"] or profile_path).expanduser().resolve()
        shared_root = Path(get_system_chrome_user_data_dir()).expanduser().resolve()
        return current == shared_root
    except Exception:
        return False

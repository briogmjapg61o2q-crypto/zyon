"""
ZYON Livestream Controller
Supports: YouTube, Facebook, TikTok, Twitch, Instagram
Manages OBS + stream keys via memory
"""

import os
import time
import platform
import subprocess
from pathlib import Path

_SYSTEM = platform.system()

# OBS paths per OS
_OBS_PATHS = {
    "Windows": [
        r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        r"C:\Program Files (x86)\obs-studio\bin\32bit\obs32.exe",
    ],
    "Darwin": ["/Applications/OBS.app/Contents/MacOS/OBS"],
    "Linux":  ["/usr/bin/obs", "/usr/local/bin/obs"],
}

# Platform RTMP URLs
_RTMP_URLS = {
    "youtube":   "rtmp://a.rtmp.youtube.com/live2",
    "facebook":  "rtmps://live-api-s.facebook.com:443/rtmp",
    "tiktok":    "rtmp://push.tiktok.com/live",
    "twitch":    "rtmp://live.twitch.tv/app",
    "instagram": "rtmps://live-upload.instagram.com:443/rtmp",
}

_PLATFORM_NAMES = {
    "youtube":   "YouTube",
    "facebook":  "Facebook",
    "tiktok":    "TikTok",
    "twitch":    "Twitch",
    "instagram": "Instagram",
}


def _find_obs() -> str | None:
    paths = _OBS_PATHS.get(_SYSTEM, [])
    for p in paths:
        if Path(p).exists():
            return p
    # Try system PATH
    import shutil
    return shutil.which("obs") or shutil.which("obs64")


def _launch_obs() -> str:
    obs = _find_obs()
    if not obs:
        return "OBS not found. Please install OBS Studio from obsproject.com"
    try:
        if _SYSTEM == "Windows":
            subprocess.Popen([obs], creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen([obs])
        time.sleep(3)
        return "OBS launched successfully."
    except Exception as e:
        return f"Failed to launch OBS: {e}"


def _obs_running() -> bool:
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            name = (p.info["name"] or "").lower()
            if "obs" in name:
                return True
    except Exception:
        pass
    return False


def _set_obs_stream_key(platform_key: str, stream_key: str) -> str:
    """Write stream key to OBS config file directly."""
    rtmp_url = _RTMP_URLS.get(platform_key)
    if not rtmp_url:
        return f"Unknown platform: {platform_key}"

    # OBS config paths
    if _SYSTEM == "Windows":
        config_dir = Path(os.environ.get("APPDATA", "")) / "obs-studio" / "basic" / "profiles"
    elif _SYSTEM == "Darwin":
        config_dir = Path.home() / "Library" / "Application Support" / "obs-studio" / "basic" / "profiles"
    else:
        config_dir = Path.home() / ".config" / "obs-studio" / "basic" / "profiles"

    if not config_dir.exists():
        return "OBS config not found. Please run OBS at least once first."

    # Find first profile
    profiles = list(config_dir.iterdir())
    if not profiles:
        return "No OBS profile found. Open OBS and create a profile first."

    service_ini = profiles[0] / "service.json"

    import json
    service_data = {
        "type": "rtmp_custom",
        "settings": {
            "server": rtmp_url,
            "key": stream_key,
        }
    }
    try:
        service_ini.write_text(json.dumps(service_data, indent=2))
        return f"Stream key set for {_PLATFORM_NAMES.get(platform_key, platform_key)}."
    except Exception as e:
        return f"Failed to write OBS config: {e}"


def livestream(
    action: str = "setup",
    platform: str = "youtube",
    stream_key: str = "",
) -> str:
    """
    Main livestream controller.

    action:
      - setup     : Save stream key + launch OBS
      - start     : Launch OBS (use saved key)
      - stop      : Close OBS
      - status    : Check if OBS is running
      - set_key   : Save/update stream key for a platform

    platform: youtube | facebook | tiktok | twitch | instagram
    stream_key: the stream key string (only needed for setup/set_key)
    """
    action   = (action or "setup").lower().strip()
    platform = (platform or "youtube").lower().strip()

    # normalize platform aliases
    aliases = {
        "yt": "youtube", "fb": "facebook", "tt": "tiktok",
        "tw": "twitch", "ig": "instagram", "insta": "instagram",
    }
    platform = aliases.get(platform, platform)

    if platform not in _RTMP_URLS:
        supported = ", ".join(_PLATFORM_NAMES.values())
        return f"Unsupported platform '{platform}'. Supported: {supported}"

    platform_name = _PLATFORM_NAMES[platform]

    # ── STATUS ──────────────────────────────────────────────────────────────
    if action == "status":
        running = _obs_running()
        return f"OBS is {'running ✅' if running else 'not running ❌'}."

    # ── SET KEY ─────────────────────────────────────────────────────────────
    if action == "set_key":
        if not stream_key:
            return f"Please provide the stream key for {platform_name}."
        result = _set_obs_stream_key(platform, stream_key)
        return result

    # ── SETUP (save key + launch) ────────────────────────────────────────────
    if action == "setup":
        results = []
        if stream_key:
            key_result = _set_obs_stream_key(platform, stream_key)
            results.append(key_result)
        if not _obs_running():
            launch_result = _launch_obs()
            results.append(launch_result)
        else:
            results.append("OBS is already running.")
        return " | ".join(results) if results else f"Livestream setup complete for {platform_name}."

    # ── START ────────────────────────────────────────────────────────────────
    if action == "start":
        if _obs_running():
            return f"OBS is already running. Ready to stream on {platform_name}!"
        result = _launch_obs()
        return f"{result} Ready for {platform_name} stream."

    # ── STOP ─────────────────────────────────────────────────────────────────
    if action == "stop":
        try:
            import psutil
            killed = False
            for p in psutil.process_iter(["name", "pid"]):
                if "obs" in (p.info["name"] or "").lower():
                    p.terminate()
                    killed = True
            return "OBS closed." if killed else "OBS was not running."
        except Exception as e:
            return f"Failed to stop OBS: {e}"

    return f"Unknown action '{action}'. Use: setup, start, stop, status, set_key."

# config/__init__.py
import json, os
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "api_keys.json"

def get_config() -> dict:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {_CONFIG_PATH}\n"
            "Please create config/api_keys.json with your Gemini API key."
        )
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in api_keys.json: {e}") from e
    key = data.get("gemini_api_key", "")
    if not key or key.strip() == "" or key == "YOUR_API_KEY_HERE":
        raise ValueError(
            "gemini_api_key is missing or not set in config/api_keys.json.\n"
            "Get your free key at: https://aistudio.google.com/apikey"
        )
    return data

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    return get_config().get("os_system", "windows").lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
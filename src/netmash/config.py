"""
Configuration and platform directory resolution for NetMash.
Provides cross-platform data/config paths and central defaults.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Protocol and Network Constants
DEFAULT_HOST_PORT = 8765
DEFAULT_DISCOVERY_PORT = 8766
DEFAULT_MULTICAST_GROUP = "239.255.77.88"
DISCOVERY_SERVICE_NAME = "netmash"
PROTOCOL_VERSION = "1.0"

# Application Limits
MAX_MESSAGE_LENGTH = 4096
MAX_USERNAME_LENGTH = 32
MIN_USERNAME_LENGTH = 2
MAX_GROUP_NAME_LENGTH = 32
MIN_GROUP_NAME_LENGTH = 2
PIN_LENGTH = 4

# Rate Limiting & Heartbeat
RATE_LIMIT_MESSAGES_PER_SEC = 5
RATE_LIMIT_BURST = 10
HEARTBEAT_INTERVAL_SECONDS = 15
HEARTBEAT_TIMEOUT_SECONDS = 45
PIN_LOCKOUT_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 30


def get_app_dir() -> Path:
    """
    Returns the platform-specific data directory for NetMash.
    - Windows: %APPDATA%/NetMash or ~/.netmash
    - Unix/macOS/WSL/Termux: ~/.config/netmash or ~/.netmash
    Creates the directory if it does not exist.
    """
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base_dir = Path(app_data) / "NetMash"
        else:
            base_dir = Path.home() / ".netmash"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            base_dir = Path(xdg_config) / "netmash"
        else:
            base_dir = Path.home() / ".config" / "netmash"

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_config_file_path() -> Path:
    """Returns path to config.json."""
    return get_app_dir() / "config.json"


def get_db_file_path() -> Path:
    """Returns path to netmash.db."""
    return get_app_dir() / "netmash.db"


def load_config() -> Dict[str, Any]:
    """Loads configuration from JSON file or returns defaults."""
    config_path = get_config_file_path()
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(config_data: Dict[str, Any]) -> None:
    """Saves configuration dictionary to JSON file."""
    config_path = get_config_file_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
    except Exception:
        pass

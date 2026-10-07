"""
Network detection and helper utilities for NetMash.
Provides cross-platform local IP resolution, interface inspection, and port checks.
"""

from __future__ import annotations

import platform
import socket
from typing import Dict, Tuple


def get_system_hostname() -> str:
    """Returns the host machine's network name."""
    try:
        return platform.node() or socket.gethostname() or "node"
    except Exception:
        return "node"


def get_local_ip() -> str:
    """
    Returns the primary local network IPv4 address for this node.
    Does not transmit real network packets over the internet; creates a dummy UDP socket
    to find the routing table's local interface IP. Fallback to 127.0.0.1.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # 10.255.255.255 is an RFC1918 broadcast address (does not send packets outside)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    try:
        # Secondary attempt via hostname resolution
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"


def get_platform_info() -> Dict[str, str]:
    """Returns human-readable OS and platform summary."""
    system = platform.system()
    if system == "Darwin":
        os_name = "macOS"
    elif system == "Windows":
        os_name = f"Windows {platform.release()}"
    elif "ANDROID_ROOT" in platform.os.environ or "TERMUX_VERSION" in platform.os.environ:
        os_name = "Termux / Android"
    elif "microsoft" in platform.uname().release.lower():
        os_name = "WSL (Linux)"
    elif system == "Linux":
        os_name = "Linux"
    else:
        os_name = system or "Unknown OS"

    return {
        "os": os_name,
        "hostname": get_system_hostname(),
        "local_ip": get_local_ip(),
        "python_version": platform.python_version(),
    }


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Checks if a TCP port can be bound."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except Exception:
        return False

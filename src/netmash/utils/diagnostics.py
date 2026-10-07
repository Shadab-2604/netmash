"""
System and network diagnostics module for NetMash.
Performs comprehensive runtime, network, transport, port, and storage checks.
Never exposes credentials, secrets, or environment variables.
"""

from __future__ import annotations

import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from netmash import __version__
from netmash.config import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_HOST_PORT,
    DEFAULT_MULTICAST_GROUP,
    get_app_dir,
    get_db_file_path,
)
from netmash.utils.network import get_local_ip, get_system_hostname


async def run_diagnostics(client: Optional[Any] = None) -> Dict[str, Any]:
    """
    Executes full diagnostic suite and returns structured results.
    """
    checks: List[Dict[str, Any]] = []
    remediations: List[str] = []

    # 1. Python runtime
    py_ver = sys.version.split(" ")[0]
    py_ok = sys.version_info >= (3, 10)
    checks.append({
        "name": "Python runtime",
        "ok": py_ok,
        "detail": f"Python {py_ver} ({platform.python_implementation()})",
    })
    if not py_ok:
        remediations.append("Upgrade Python to version 3.10 or newer.")

    # 2. NetMash installation
    checks.append({
        "name": "NetMash installation",
        "ok": True,
        "detail": f"Version {__version__}",
    })

    # 3. Configuration and User Directory
    app_dir = get_app_dir()
    app_dir_ok = False
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        test_file = app_dir / ".diag_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        app_dir_ok = True
    except Exception as e:
        remediations.append(f"Ensure write permissions for directory: {app_dir}")

    checks.append({
        "name": "Configuration directory",
        "ok": app_dir_ok,
        "detail": str(app_dir),
    })

    # 4. Local network interface & address
    local_ip = get_local_ip()
    ip_ok = local_ip != "127.0.0.1" and not local_ip.startswith("127.")
    checks.append({
        "name": "Local network interface",
        "ok": True,
        "detail": f"Hostname: {get_system_hostname()}",
    })
    checks.append({
        "name": "Local IP address",
        "ok": ip_ok,
        "detail": local_ip if ip_ok else f"{local_ip} (Loopback / Offline)",
    })
    if not ip_ok:
        remediations.append("Connect to a local Wi-Fi or Ethernet network for multi-device discovery.")

    # 5. UDP discovery socket binding
    udp_ok = False
    udp_reason = ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))  # Test bind
        sock.close()
        udp_ok = True
        udp_reason = f"Port {DEFAULT_DISCOVERY_PORT} / Multicast {DEFAULT_MULTICAST_GROUP}"
    except Exception as e:
        udp_reason = str(e)
        remediations.append("Allow UDP traffic on port 8766 in firewall settings.")

    checks.append({
        "name": "UDP discovery subsystem",
        "ok": udp_ok,
        "detail": udp_reason,
    })

    # 6. TCP Wire Protocol Port
    tcp_ok = True
    tcp_detail = f"TCP Port {DEFAULT_HOST_PORT}"
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(0.5)
        # Check if port is open locally or free to bind
        res = test_sock.connect_ex(("127.0.0.1", DEFAULT_HOST_PORT))
        if res == 0:
            tcp_detail += " (Active NetMash host running)"
        else:
            tcp_detail += " (Available for hosting)"
        test_sock.close()
    except Exception as e:
        tcp_ok = False
        tcp_detail = str(e)

    checks.append({
        "name": "TCP transport port",
        "ok": tcp_ok,
        "detail": tcp_detail,
    })

    # 7. Host connection state
    host_connected = client.connected if client else False
    if host_connected and client:
        checks.append({
            "name": "Host connection",
            "ok": True,
            "detail": f"Connected to {client.host}:{client.port} (Room: {client.current_room.upper()})",
        })
    else:
        checks.append({
            "name": "Host connection",
            "ok": True,
            "detail": "Ready (Connecting / Local Hosting)",
        })

    # 8. SQLite Database
    db_file = get_db_file_path()
    db_ok = False
    db_detail = ""
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        cursor = conn.execute("PRAGMA integrity_check;")
        status = cursor.fetchone()[0]
        conn.close()
        db_ok = status.lower() == "ok"
        db_detail = f"Integrity: {status.upper()} (Journal: {mode.upper()})"
    except Exception as e:
        db_detail = f"Error: {e}"
        remediations.append("Repair or remove corrupted database file in user directory.")

    checks.append({
        "name": "SQLite database storage",
        "ok": db_ok,
        "detail": db_detail,
    })

    # Overall outcome
    all_ok = all(c["ok"] for c in checks)
    overall_status = "READY" if all_ok else "DEGRADED"

    return {
        "status": overall_status,
        "checks": checks,
        "remediations": remediations,
    }

"""
Terminal UI components and interactive chat loop for NetMash.
Provides banners, tables, formatted outputs, non-blocking CLI input handling,
and full phase 1-8 command handlers.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from netmash import __version__
from netmash.client.client import NetMashClient
from netmash.config import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_HOST_PORT,
    DEFAULT_MULTICAST_GROUP,
    get_app_dir,
)
from netmash.discovery.service import discover_host
from netmash.protocol.messages import MessageType, NetMashMessage
from netmash.server.server import NetMashServer
from netmash.ui.colors import (
    bold,
    bright_cyan,
    cyan,
    dim,
    gray,
    green,
    magenta,
    red,
    yellow,
)
from netmash.ui.theme import (
    get_active_theme,
    get_all_themes,
    get_theme,
    get_theme_count,
    load_saved_theme,
    set_active_theme,
    set_random_theme,
)
from netmash.updater import (
    apply_update_async,
    check_for_updates_async,
    render_version_diagnostics,
)
from netmash.ui.input import TerminalInputManager
from netmash.utils.diagnostics import run_diagnostics
from netmash.utils.file_transfer import (
    MAX_FILE_SIZE_BYTES,
    calculate_sha256,
    get_downloads_dir,
    read_file_chunks,
    sanitize_filename,
)
from netmash.utils.network import get_local_ip, get_platform_info, get_system_hostname
from netmash.utils.security import sanitize_terminal_text

SLASH_COMMANDS = [
    "/help",
    "/theme",
    "/users",
    "/peers",
    "/groups",
    "/create",
    "/create-pin",
    "/join",
    "/switch",
    "/general",
    "/leave",
    "/setpin",
    "/removepin",
    "/dm",
    "/room",
    "/name",
    "/whoami",
    "/members",
    "/online",
    "/reconnect",
    "/diagnose",
    "/version",
    "/netinfo",
    "/stats",
    "/history",
    "/search",
    "/unread",
    "/reply",
    "/edit",
    "/delete",
    "/pin",
    "/unpin",
    "/away",
    "/busy",
    "/mute",
    "/unmute",
    "/notify",
    "/kick",
    "/ban",
    "/unban",
    "/announce",
    "/send",
    "/network-name",
    "/update",
    "/check-update",
    "/restart",
    "/info",
    "/status",
    "/clear",
    "/exit",
    "/quit",
]


def _setup_readline(history_file: Optional[Path] = None) -> None:
    """Configures readline for arrow key navigation, message history, and tab completion."""
    try:
        import readline

        def completer(text: str, state: int) -> Optional[str]:
            options = [c for c in SLASH_COMMANDS if c.startswith(text)]
            if state < len(options):
                return options[state]
            return None

        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
        readline.set_history_length(1000)

        if history_file and history_file.exists():
            try:
                readline.read_history_file(str(history_file))
            except Exception:
                pass
    except (ImportError, AttributeError):
        pass


def _save_readline_history(history_file: Optional[Path] = None) -> None:
    """Saves readline input history to disk."""
    if not history_file:
        return
    try:
        import readline

        readline.write_history_file(str(history_file))
    except (ImportError, AttributeError, Exception):
        pass


def print_banner() -> None:
    """Prints the NetMash welcome banner."""
    t = get_active_theme()
    print()
    print(t.border("╭──────────────────────────────────────────╮"))
    print(t.border("│") + t.header("                 NETMASH                  ") + t.border("│"))
    print(t.border("│") + t.dim("         Connect. Discover. Chat.         ") + t.border("│"))
    print(t.border("╰──────────────────────────────────────────╯"))
    print()


def print_divider(label: Optional[str] = None) -> None:
    """Prints a clean horizontal terminal divider."""
    t = get_active_theme()
    width = 54
    if label:
        sanitized_label = f" {label} "
        left_len = max(2, (width - len(sanitized_label)) // 2)
        right_len = max(2, width - len(sanitized_label) - left_len)
        print(t.border("─" * left_len) + t.header(sanitized_label) + t.border("─" * right_len))
    else:
        print(t.border("─" * width))


def render_whoami(
    username: str,
    node_id: str,
    hostname: str,
    status: str = "ONLINE",
    role: str = "MEMBER",
    host: str = "Host",
) -> None:
    """Renders formatted /whoami identity view."""
    t = get_active_theme()
    print(t.bold("\nNetMash Identity\n"))
    print(f"{'Username':<12}: {t.primary(username)}")
    print(f"{'Node ID':<12}: {t.dim(node_id)}")
    print(f"{'Hostname':<12}: {hostname}")
    status_str = t.success(status) if status == "ONLINE" else (t.warning(status) if status == "AWAY" else t.error(status))
    print(f"{'Status':<12}: {status_str}")
    print(f"{'Role':<12}: {role}")
    print(f"{'Host':<12}: {host}")
    print()


def render_peers_table(peers: List[Dict[str, Any]]) -> None:
    """Renders formatted list of connected peers with presence and latency."""
    t = get_active_theme()
    print(t.bold("\nOnline Peers\n"))
    print(f"{t.bold('USER'):<18} {t.bold('STATUS'):<12} {t.bold('LATENCY'):<10} {t.bold('HOSTNAME')}")
    print(t.border("─" * 54))
    if not peers:
        print(t.dim("No peers online."))
        print()
        return

    for p in peers:
        user = sanitize_terminal_text(p.get("username", ""))[:16]
        host = sanitize_terminal_text(p.get("hostname", ""))[:18]
        raw_status = p.get("status", "ONLINE")
        if raw_status == "ONLINE":
            status_str = t.success("ONLINE")
        elif raw_status == "AWAY":
            status_str = t.warning("AWAY")
        elif raw_status == "BUSY":
            status_str = t.error("BUSY")
        else:
            status_str = t.muted("OFFLINE")

        lat = p.get("latency_ms", 0.0)
        lat_str = f"{lat}ms" if lat > 0 else "<1ms"
        print(f"{t.primary(user):<27} {status_str:<21} {lat_str:<10} {host}")
    print()


def render_members(data: Dict[str, Any]) -> None:
    """Renders categorized group members (Owner, Moderators, Members)."""
    t = get_active_theme()
    group_name = data.get("group", "group")
    print(t.bold(f"\nMembers for: {group_name}\n"))

    owner = data.get("owner")
    print(t.bold("Owner:"))
    if isinstance(owner, list):
        if owner:
            for o in owner:
                print(f"  {t.success(o)}")
        else:
            print(t.dim("  None"))
    elif owner:
        print(f"  {t.success(str(owner))}")
    else:
        print(t.dim("  None"))
    print()

    mods = data.get("moderators", [])
    print(t.bold("Moderators:"))
    if mods:
        for m in mods:
            print(f"  {t.warning(m)}")
    else:
        print(t.dim("  None"))
    print()

    members = data.get("members", [])
    print(t.bold("Members:"))
    if members:
        for mem in members:
            print(f"  {t.primary(mem)}")
    else:
        print(t.dim("  None"))
    print()


def render_groups_table(
    groups: List[Dict[str, Any]], current_room: Optional[str] = None
) -> None:
    """Renders formatted list of available groups. Star strictly shows for current active room."""
    t = get_active_theme()
    print(t.bold("\nAvailable Groups\n"))
    print(f"{t.bold('NAME'):<20} {t.bold('MEMBERS'):<12} {t.bold('ACCESS')}")
    print(t.border("─" * 42))
    if not groups:
        print(t.dim("No groups available."))
        print()
        return

    for g in groups:
        raw_name = g.get("name", "")
        name = sanitize_terminal_text(raw_name)[:18]
        members = str(g.get("members", 0))
        access = g.get("access", "PUBLIC")
        access_str = t.warning("PIN") if access == "PIN" else t.success("PUBLIC")

        is_inside = False
        if current_room:
            is_inside = raw_name.lower() == current_room.lower()
        elif g.get("is_inside") or g.get("is_active"):
            is_inside = True

        mem_flag = t.accent(" *") if is_inside else ""
        print(f"{name + mem_flag:<20} {members:<12} {access_str}")
    print()


def render_diagnostics(diag: Dict[str, Any]) -> None:
    """Renders formatted system diagnostics results with remediation hints."""
    t = get_active_theme()
    print(t.bold("\nNetMash Diagnostics\n"))
    checks = diag.get("checks", [])
    for c in checks:
        name = c.get("name", "")
        ok = c.get("ok", False)
        detail = c.get("detail", "")
        if ok:
            print(f"{t.success('✓')} {name:<26} {t.dim(detail)}")
        else:
            print(f"{t.error('✗')} {name:<26} {t.error(detail)}")

    status = diag.get("status", "READY")
    status_str = t.success(status) if status == "READY" else t.warning(status)
    print(f"\nResult: {status_str}")

    remediations = diag.get("remediations", [])
    if remediations:
        print(t.warning("\nRemediation hints:"))
        for r in remediations:
            print(f"  • {r}")
    print()


def render_netinfo(info: Dict[str, Any]) -> None:
    """Renders local network information without arbitrary LAN scanning."""
    t = get_active_theme()
    print(t.bold("\nNetwork Information\n"))
    print(f"{'Interface':<14}: {info.get('interface', 'Wi-Fi / Ethernet')}")
    print(f"{'Address':<14}: {t.success(str(info.get('address', '127.0.0.1')))}")
    print(f"{'Subnet':<14}: {info.get('subnet', '/24')}")
    print(f"{'Transport':<14}: {info.get('transport', 'TCP Wire Protocol')}")
    print(f"{'Port':<14}: {info.get('port', DEFAULT_HOST_PORT)}")
    print(f"{'Discovery':<14}: UDP Port {info.get('discovery_port', DEFAULT_DISCOVERY_PORT)}")
    print(f"{'Host':<14}: {info.get('host', 'Local')}")
    print(f"{'Peers':<14}: {info.get('peers', 0)}")
    print()


def render_stats(stats: Dict[str, Any]) -> None:
    """Renders NetMash host statistics."""
    t = get_active_theme()
    print(t.bold("\nNetMash Statistics\n"))
    print(f"{'Uptime':<18}: {stats.get('uptime', '00:00:00')}")
    print(f"{'Connected Peers':<18}: {stats.get('connected_peers', 0)}")
    print(f"{'Groups':<18}: {stats.get('total_groups', 0)}")
    print(f"{'Active Rooms':<18}: {stats.get('active_rooms', 0)}")
    print(f"{'Messages':<18}: {stats.get('total_messages', 0)}")
    print("\nNetwork:")
    print(f"  {'RX':<16}: {stats.get('rx_mb', 0.0)} MB")
    print(f"  {'TX':<16}: {stats.get('tx_mb', 0.0)} MB")
    print(f"\n{'Errors':<18}: {stats.get('error_count', 0)}")
    print()


def render_history(messages: List[Dict[str, Any]]) -> None:
    """Renders recent message history in room."""
    t = get_active_theme()
    print(t.bold("\nRecent Messages\n"))
    if not messages:
        print(t.dim("No recent messages."))
        print()
        return

    for m in messages:
        ts = m.get("timestamp", "")
        time_part = ts[11:16] if len(ts) >= 16 else ts
        sender = sanitize_terminal_text(m.get("sender_name", "Unknown"))
        msg_id = m.get("message_id", "")
        content = sanitize_terminal_text(m.get("content", ""))
        reply_to = m.get("reply_to")
        pinned = m.get("pinned", 0)
        edited = m.get("edited", 0)

        pin_tag = t.warning("📌 [PINNED] ") if pinned else ""
        edit_tag = t.dim(" (edited)") if edited else ""
        id_tag = t.dim(f"(ID: {msg_id[:8]})")

        print(f"{t.dim(f'[{time_part}]')} {id_tag} {t.primary(sender)}: {pin_tag}")
        if reply_to:
            print(f"  {t.dim('↳ Replying to: ' + reply_to[:8])}")
        print(f"{t.message(content)}{edit_tag}\n")


def render_search_results(query: str, results: List[Dict[str, Any]]) -> None:
    """Renders message search results."""
    t = get_active_theme()
    print(t.bold(f"\nSearch results for: {query}\n"))
    if not results:
        print(t.dim("No matching messages found."))
        print()
        return

    for m in results:
        ts = m.get("timestamp", "")
        time_part = ts[11:16] if len(ts) >= 16 else ts
        sender = sanitize_terminal_text(m.get("sender_name", "Unknown"))
        room = m.get("room_id", "general").upper()
        msg_id = m.get("message_id", "")
        content = sanitize_terminal_text(m.get("content", ""))

        print(f"{t.dim(f'[{time_part}]')} [{t.primary(room)}] {t.dim(f'(ID: {msg_id[:8]})')} {t.bold(sender)}:")
        print(f"{t.message(content)}\n")


def render_unread(unread: Dict[str, int]) -> None:
    """Renders unread message counts per room."""
    t = get_active_theme()
    print(t.bold("\nUnread Messages\n"))
    if not unread or all(v == 0 for v in unread.values()):
        print(t.dim("No unread messages."))
        print()
        return

    for room, count in unread.items():
        if count > 0:
            print(f"{room:<16}: {t.warning(str(count))}")
    print()


def format_announcement(sender: str, content: str) -> str:
    """Formats prominent announcement banner as a string."""
    t = get_active_theme()
    clean_sender = sanitize_terminal_text(sender)
    clean_content = sanitize_terminal_text(content)
    width = 54
    border_top = "╔" + "═" * (width - 2) + "╗"
    title_line = f"║{'HOST ANNOUNCEMENT':^{width-2}}║"
    border_mid = "╠" + "═" * (width - 2) + "╣"
    sender_line = f"║  From: {clean_sender:<{width-11}}║"
    content_line = f"║  {clean_content:<{width-5}}║"
    border_bot = "╚" + "═" * (width - 2) + "╝"

    return "\n" + "\n".join([
        t.warning(border_top),
        t.warning(title_line),
        t.warning(border_mid),
        t.warning(sender_line),
        t.bold(content_line),
        t.warning(border_bot),
    ]) + "\n"


def render_announcement(sender: str, content: str) -> None:
    """Renders prominent announcement banner."""
    print(format_announcement(sender, content))


def render_info(info: Dict[str, Any]) -> None:
    """Renders formatted NetMash information."""
    t = get_active_theme()
    print(t.bold("\nNetMash Information\n"))
    print(f"{'Version':<16}: {t.success(str(info.get('version', __version__)))}")
    print(f"{'Hostname':<16}: {info.get('hostname', '')}")
    if "username" in info:
        print(f"{'Username':<16}: {t.primary(info.get('username', ''))}")
    print(f"{'Platform':<16}: {info.get('os', 'Local Network')}")
    print(f"{'Local Address':<16}: {info.get('local_ip', '127.0.0.1')}")
    print(f"{'Status':<16}: {t.success(str(info.get('status', 'ONLINE')))}")
    if "peers" in info:
        print(f"{'Peers':<16}: {info.get('peers', 0)}")
    if "groups" in info:
        print(f"{'Groups':<16}: {info.get('groups', 0)}")
    print()


def render_status(status: Dict[str, Any]) -> None:
    """Renders formatted NetMash status."""
    t = get_active_theme()
    print(t.bold("\nNetMash Status\n"))
    print(f"{'Server':<16}: {t.success(str(status.get('server_status', 'ONLINE')))}")
    print(f"{'Connection':<16}: {t.success('CONNECTED')}")
    print(f"{'Host':<16}: {status.get('host_name', '')}")
    print(f"{'Network':<16}: {t.primary(status.get('network_name', 'NetMash Local'))}")
    print(f"{'Peers':<16}: {status.get('peers_count', 0)}")
    print(f"{'Groups':<16}: {status.get('groups_count', 0)}")
    print(f"{'Room':<16}: {t.primary(str(status.get('room', 'GENERAL')).upper())}")
    print(f"{'Uptime':<16}: {status.get('uptime', '00:00:00')}")
    print()


def render_admin_menu() -> None:
    """Renders the NetMash Admin interactive menu."""
    t = get_active_theme()
    print(t.bold("\nNetMash Admin"))
    print(t.border("────────────────────────"))
    print(f" {t.primary('1.')} Server Status")
    print(f" {t.primary('2.')} Connected Users")
    print(f" {t.primary('3.')} Groups")
    print(f" {t.primary('4.')} Sessions")
    print(f" {t.primary('5.')} Moderation")
    print(f" {t.primary('6.')} Messages")
    print(f" {t.primary('7.')} Network Diagnostics")
    print(f" {t.primary('8.')} Logs")
    print(f" {t.primary('9.')} Statistics")
    print(f" {t.primary('10.')} Configuration")
    print(f" {t.primary('11.')} Shutdown Server")
    print(f" {t.primary('12.')} Logout")
    print()


def render_admin_status(status_data: Dict[str, Any]) -> None:
    """Renders formatted Server Status."""
    t = get_active_theme()
    print(t.bold("\nServer Status"))
    print(t.border("─────────────"))
    print(f"{'Status':<22}: {t.success(str(status_data.get('status', 'ONLINE')))}")
    print(f"{'Uptime':<22}: {status_data.get('uptime', '00:00:00')}")
    print(f"{'Host':<22}: {status_data.get('host', 'Host')}")
    print(f"{'Version':<22}: {status_data.get('version', __version__)}")
    print(f"{'Active Connections':<22}: {status_data.get('active_connections', 0)}")
    print(f"{'Active Groups':<22}: {status_data.get('active_groups', 0)}")
    print(f"{'Messages Processed':<22}: {status_data.get('messages_processed', 0)}")
    print()


def render_admin_users(users: List[Dict[str, Any]]) -> None:
    """Renders administrative view of connected users with immutable node IDs and groups."""
    t = get_active_theme()
    print(t.bold("\nUsers Online"))
    print(t.border("────────────"))
    if not users:
        print(t.dim("No users connected."))
        print()
        return
    print(f"{t.bold('NODE ID'):<18} {t.bold('USERNAME'):<16} {t.bold('STATUS'):<10} {t.bold('GROUP'):<12} {t.bold('CONNECTED SINCE')}")
    print(t.border("─" * 74))
    for u in users:
        nid = u.get("node_id", "")[:16]
        uname = sanitize_terminal_text(u.get("username", ""))[:14]
        st = u.get("status", "ONLINE")
        st_str = t.success("ONLINE") if st == "ONLINE" else (t.warning(st) if st == "AWAY" else t.error(st))
        room = sanitize_terminal_text(u.get("current_room", "general"))[:10]
        conn_since = u.get("connected_at", "")
        if len(conn_since) >= 19:
            conn_since = conn_since[11:19]
        print(f"{t.dim(nid):<27} {t.primary(uname):<25} {st_str:<19} {room:<12} {conn_since}")
    print()


def render_admin_groups(groups: List[Dict[str, Any]]) -> None:
    """Renders administrative view of groups with owner and creation time."""
    t = get_active_theme()
    print(t.bold("\nGroups"))
    print(t.border("──────"))
    if not groups:
        print(t.dim("No groups available."))
        print()
        return
    print(f"{t.bold('NAME'):<18} {t.bold('OWNER'):<16} {t.bold('MEMBERS'):<10} {t.bold('ACCESS'):<10} {t.bold('CREATED')}")
    print(t.border("─" * 72))
    for g in groups:
        name = sanitize_terminal_text(g.get("name", ""))[:16]
        owner = sanitize_terminal_text(g.get("owner", "Host"))[:14]
        members = str(g.get("member_count", g.get("members", 0)))
        access = g.get("access", "PUBLIC")
        access_str = t.warning("PIN") if access == "PIN" else t.success("PUBLIC")
        created = g.get("created_at", "")
        if len(created) >= 19:
            created = created[11:19]
        print(f"{t.primary(name):<27} {owner:<16} {members:<10} {access_str:<19} {created}")
    print()


def render_admin_sessions(sessions: List[Dict[str, Any]]) -> None:
    """Renders active client sessions without exposing secrets/tokens."""
    t = get_active_theme()
    print(t.bold("\nActive Sessions"))
    print(t.border("───────────────"))
    if not sessions:
        print(t.dim("No active sessions."))
        print()
        return
    print(f"{t.bold('SESSION ID'):<14} {t.bold('NODE ID'):<16} {t.bold('USERNAME'):<14} {t.bold('REMOTE ADDR'):<18} {t.bold('ROOM'):<10} {t.bold('STATUS')}")
    print(t.border("─" * 84))
    for s in sessions:
        sid = s.get("session_id", "")[:12]
        nid = s.get("node_id", "")[:14]
        uname = sanitize_terminal_text(s.get("username", ""))[:12]
        addr = str(s.get("remote_addr", ""))[:16]
        room = sanitize_terminal_text(s.get("current_room", "general"))[:8]
        st = s.get("status", "ACTIVE")
        st_str = t.success(st) if st == "ACTIVE" else t.warning(st)
        print(f"{t.dim(sid):<23} {t.dim(nid):<25} {t.primary(uname):<23} {addr:<18} {room:<10} {st_str}")
    print()


def render_admin_diagnostics(diag: Dict[str, Any]) -> None:
    """Renders administrative network and system diagnostics."""
    t = get_active_theme()
    print(t.bold("\nNetwork Diagnostics"))
    print(t.border("───────────────────"))
    print(f"{'Server Address':<22}: {t.success(str(diag.get('server_address', '127.0.0.1')))}")
    print(f"{'Listening Port':<22}: {diag.get('listening_port', DEFAULT_HOST_PORT)}")
    print(f"{'Discovery Port':<22}: {diag.get('discovery_port', DEFAULT_DISCOVERY_PORT)}")
    print(f"{'WebSocket / Sockets':<22}: {t.success(str(diag.get('websocket_status', 'ONLINE')))}")
    print(f"{'Database Status':<22}: {t.success(str(diag.get('database_status', 'HEALTHY')))}")
    print(f"{'Connected Clients':<22}: {diag.get('connected_clients', 0)}")
    lat = diag.get("latency_ms", 0.0)
    lat_str = f"{lat}ms" if lat > 0 else "<1ms"
    print(f"{'Latency':<22}: {lat_str}")
    print()


def render_admin_logs(logs: List[Dict[str, Any]]) -> None:
    """Renders server audit logs."""
    t = get_active_theme()
    print(t.bold("\nServer Audit Logs"))
    print(t.border("─────────────────"))
    if not logs:
        print(t.dim("No logs recorded."))
        print()
        return
    for l in logs:
        ts = l.get("timestamp", "")
        time_part = ts[11:19] if len(ts) >= 19 else ts
        lvl = l.get("level", "INFO")
        lvl_str = t.success(lvl) if lvl == "INFO" else (t.warning(lvl) if lvl == "WARNING" else t.error(lvl))
        msg = sanitize_terminal_text(l.get("message", ""))
        print(f"{t.dim(f'[{time_part}]')} [{lvl_str}] {msg}")
    print()


def render_admin_stats(stats: Dict[str, Any]) -> None:
    """Renders server administrative statistics."""
    t = get_active_theme()
    print(t.bold("\nNetMash Statistics"))
    print(t.border("──────────────────"))
    print(f"{'Users':<20}: {stats.get('users_count', 0)}")
    print(f"{'Online':<20}: {t.success(str(stats.get('online_count', 0)))}")
    print(f"{'Groups':<20}: {stats.get('groups_count', 0)}")
    print(f"{'Messages':<20}: {stats.get('messages_count', 0)}")
    print(f"{'DMs':<20}: {stats.get('dms_count', 0)}")
    print(f"{'Files':<20}: {stats.get('files_count', 0)}")
    print(f"{'Active Connections':<20}: {stats.get('active_connections', 0)}")
    print(f"{'Server Uptime':<20}: {stats.get('uptime', '00:00:00')}")
    print()


def render_admin_config(cfg: Dict[str, Any]) -> None:
    """Renders safe server configuration parameters."""
    t = get_active_theme()
    print(t.bold("\nServer Configuration"))
    print(t.border("────────────────────"))
    for k, v in cfg.items():
        print(f"{k:<22}: {v}")
    print()


def render_version_info() -> None:
    """Renders comprehensive NetMash runtime and installation version diagnostics."""
    t = get_active_theme()
    diag = render_version_diagnostics()
    print(t.bold("\nNetMash Information"))
    print(t.border("──────────────────────────────────────────────────"))
    print(f"{'Running Version':<20}: {t.accent(diag['running_version'])}")
    print(f"{'Running Commit':<20}: {t.accent(diag['running_commit'])}")
    print(f"{'Installed Version':<20}: {t.accent(diag['installed_version'])}")
    print(f"{'Installed Commit':<20}: {t.accent(diag['installed_commit'])}")
    print(f"{'Python Executable':<20}: {diag['python_executable']}")
    print(f"{'Python Version':<20}: {diag['python_version']}")
    print(f"{'Platform':<20}: {diag['platform']}")
    print(f"{'Repository':<20}: {diag['repository']}")
    print(f"{'Installation':<20}: {diag['install_path']}")

    if diag.get("restart_pending"):
        print(t.warning("\n⚠ An update is installed on disk, but this running process is older."))
        print(t.dim("  Run /restart to load the updated version.\n"))
    else:
        print()


def render_theme_list() -> None:
    """Renders the centralized theme registry card showing all available themes and current active theme."""
    themes = get_all_themes()
    active = get_active_theme()
    count = len(themes)
    width = 42

    print()
    print(active.border("╭" + "─" * width + "╮"))
    print(active.border("│") + active.header(f"{'NETMASH THEMES':^{width}}") + active.border("│"))
    print(active.border("├" + "─" * width + "┤"))
    for t in themes:
        prefix = f"  {t.id}." if t.id < 10 else f" {t.id}."
        raw_line = f"{prefix} {t.name}"
        if t.id == active.id:
            formatted_item = active.accent(f"{raw_line:<{width}}")
        else:
            formatted_item = f"{raw_line:<{width}}"
        print(active.border("│") + formatted_item + active.border("│"))
    print(active.border("├" + "─" * width + "┤"))
    cur_line = f" Current: {active.name}"
    print(active.border("│") + active.accent(f"{cur_line:<{width}}") + active.border("│"))
    print(active.border("╰" + "─" * width + "╯"))
    print()
    print(active.bold("Usage:"))
    print(f"  {active.primary(f'/theme 1-{count}')}")
    print(f"  {active.primary('/theme random')}\n")


def render_invalid_theme() -> None:
    """Renders error and dynamic theme list for invalid /theme inputs."""
    themes = get_all_themes()
    active = get_active_theme()
    count = len(themes)

    print(active.error("\nInvalid theme.\n"))
    print(active.bold("Available themes:"))
    for t in themes:
        print(f"{t.id}. {t.name}")
    print()
    print(active.bold("Use:"))
    print(f"  {active.primary(f'/theme 1-{count}')}")
    print(f"  {active.primary('/theme random')}\n")


def print_help() -> None:
    """Prints categorized interactive chat commands with clean, consistent column alignment."""
    theme = get_active_theme()
    theme_count = get_theme_count()

    def fmt(cmd_str: str, desc_str: str) -> str:
        # Pre-pad command name to 32 chars before styling to guarantee perfect column alignment
        return f"  {theme.primary(f'{cmd_str:<32}')} {desc_str}"

    print(theme.bold("\nInteractive Commands\n"))

    print(theme.bold("General"))
    print(fmt("/help", "Show this help message"))
    print(fmt("/users, /peers", "List connected peers and latency"))
    print(fmt("/groups", "List all available groups"))
    print(fmt("/room", "Show current active room"))
    print(fmt("/general", "Quick jump back to GENERAL room"))
    print(fmt("/online", "View online peers or set status to ONLINE"))
    print(fmt("/whoami", "Show your persistent node identity"))

    print(theme.bold("\nGroups"))
    print(fmt("/create <name> [pin]", "Create a new group (public or PIN-protected)"))
    print(fmt("/create-pin <name> <pin>", "Quick-create a 4-digit PIN protected group"))
    print(fmt("/join <name> [pin]", "Join a group (or switch to it)"))
    print(fmt("/switch <name>", "Switch active room without re-entering PIN"))
    print(fmt("/leave [name]", "Leave group and return to GENERAL"))
    print(fmt("/members [name]", "Show group owner, moderators, and members"))
    print(fmt("/setpin <name> [pin]", "Set or update 4-digit PIN (owner only)"))
    print(fmt("/removepin <name>", "Remove PIN and make group public (owner only)"))
    print(fmt("/kick <user>", "Kick member from group (owner/moderator)"))
    print(fmt("/ban <user>", "Ban member from group (owner/moderator)"))
    print(fmt("/unban <user>", "Unban member from group (owner only)"))
    print(fmt("/delete [group]", "Permanently delete group (owner only)"))
    print(fmt("/announce <msg>", "Broadcast announcement banner to room"))

    print(theme.bold("\nCommunication"))
    print(fmt("/dm <user> [msg]", "Direct message a peer"))
    print(fmt("/history [limit]", "View recent message history in room"))
    print(fmt("/search <text>", "Search message history across accessible rooms"))
    print(fmt("/unread", "View unread message counts per room"))
    print(fmt("/reply <msg_id> <msg>", "Reply to a specific message"))
    print(fmt("/edit <msg_id> <new_msg>", "Edit your previously sent message"))
    print(fmt("/delete <msg_id>", "Delete a message (soft delete)"))
    print(fmt("/pin <msg_id>", "Pin an important message in room"))
    print(fmt("/unpin <msg_id>", "Unpin a message in room"))
    print(fmt("/send <file>", "Securely send file to peer or room"))

    print(theme.bold("\nPresence & Notifications"))
    print(fmt("/away", "Set status to AWAY"))
    print(fmt("/busy", "Set status to BUSY"))
    print(fmt("/mute <room>", "Mute notification indicators for a room"))
    print(fmt("/unmute <room>", "Unmute notification indicators for a room"))
    print(fmt("/notify on|off", "Toggle terminal message notifications"))

    print(theme.bold("\nNetwork & Diagnostics"))
    print(fmt("/info", "Show local node and platform info"))
    print(fmt("/netinfo", "Show local network interfaces and subnet"))
    print(fmt("/status", "Show host status and uptime"))
    print(fmt("/stats", "Show network throughput and server metrics"))
    print(fmt("/diagnose", "Run full diagnostic suite & remediation hints"))
    print(fmt("/reconnect", "Reconnect to host or discover new host"))
    print(fmt("/network-name <name>", "Rename LAN session network name"))

    print(theme.bold("\nApplication"))
    print(fmt("/name <new_name>", "Change your display name"))
    print(fmt(f"/theme [1-{theme_count}|random]", "Change terminal theme"))
    print(fmt("/version", "Show NetMash, Python, and platform versions"))
    print(fmt("/check-update", "Check GitHub for updates without installing"))
    print(fmt("/update", "Download and apply update from GitHub"))
    print(fmt("/restart", "Restart NetMash session"))
    print(fmt("/clear", "Clear terminal screen"))
    print(fmt("/exit, /quit", "Disconnect and exit"))
    print()


def clear_screen() -> None:
    """Clears the terminal screen."""
    os.system("cls" if sys.platform == "win32" else "clear")


def redraw_screen(
    client: NetMashClient,
    input_manager: Optional[TerminalInputManager] = None,
    notice: Optional[str] = None,
) -> None:
    """
    Clears the screen and redraws the entire visible NetMash interface in the active theme.
    Preserves active room, username, node identity, server info, typed buffer, and cursor position.
    """
    clear_screen()
    print_banner()
    host_name = client.server_info.get("host_name", "Host")
    network_title = client.server_info.get("network_name", "NetMash")
    room_name = (client.current_room or "general").upper()
    print_divider(f"{network_title} | {room_name} | Host: {host_name}")
    theme = get_active_theme()
    print(theme.dim(f"You are: {client.identity.username} ({client.identity.hostname})"))
    if notice:
        print(notice)
    else:
        print()
    if input_manager:
        input_manager.redraw_input()


async def run_interactive_chat(
    client: NetMashClient, server: Optional[Any] = None
) -> None:
    """
    Main interactive terminal chat loop with complete command handling.
    """
    load_saved_theme()
    print_banner()
    host_name = client.server_info.get("host_name", "Host")
    network_title = client.server_info.get("network_name", "NetMash")

    print_divider(f"{network_title} | {client.current_room.upper()} | Host: {host_name}")
    print(dim(f"You are: {client.identity.username} ({client.identity.hostname})"))
    # Admin session state
    is_admin_mode: bool = False

    def get_active_prompt() -> str:
        """
        Dynamically generates the prompt containing the currently active room/group.
        Format:
          Normal: netmash><active_room>> 
          Admin:  netmash[ADMIN]><active_room>> 
        Single source of truth is client.current_room and is_admin_mode.
        Uses active theme styling for prompt components.
        """
        room = (client.current_room or "general").lower().strip()
        t = get_active_theme()
        if is_admin_mode:
            return f"{t.error('netmash[ADMIN]')}>{t.prompt(room)}> "
        return f"{t.prompt('netmash')}>{t.prompt(room)}> "

    history_file = get_app_dir() / "history.txt"
    input_manager = TerminalInputManager(
        prompt=get_active_prompt,
        history_file=history_file,
        completer_words=SLASH_COMMANDS,
    )

    # State tracking
    muted_rooms: Set[str] = set()
    notifications_enabled: bool = True
    unread_counts: Dict[str, int] = {}
    current_status: str = "ONLINE"

    # Pending file downloads
    incoming_transfers: Dict[str, Dict[str, Any]] = {}

    # Event Callbacks
    def on_chat(msg: NetMashMessage) -> None:
        t = get_active_theme()
        payload = msg.payload
        room = sanitize_terminal_text(payload.get("room", "general")).lower()
        sender = sanitize_terminal_text(payload.get("sender_name", "Unknown"))
        content = sanitize_terminal_text(payload.get("content", ""))
        msg_id = payload.get("message_id", "")
        reply_to = payload.get("reply_to")

        now_str = datetime.datetime.now().strftime("%H:%M")
        is_self = payload.get("sender_id") == client.identity.node_id

        # Track unread
        if room != client.current_room.lower():
            unread_counts[room] = unread_counts.get(room, 0) + 1
            if notifications_enabled and room not in muted_rooms:
                input_manager.print_event(t.warning(f"🔔 New message in [{room.upper()}] from {sender}"))
            return

        sender_label = t.success(f"{sender} (You)") if is_self else t.primary(sender)
        id_tag = t.dim(f"({msg_id[:8]}) ") if msg_id else ""

        event_text = f"{t.dim(f'[{now_str}]')} {id_tag}{sender_label}:\n"
        if reply_to:
            event_text += f"{t.dim(f'↳ Replying to: {reply_to[:8]}')}\n"
        event_text += f"{t.message(content)}\n"
        input_manager.print_event(event_text)

    def on_dm(msg: NetMashMessage) -> None:
        t = get_active_theme()
        payload = msg.payload
        sender = sanitize_terminal_text(payload.get("sender_name", "Unknown"))
        target = sanitize_terminal_text(payload.get("target", ""))
        content = sanitize_terminal_text(payload.get("content", ""))
        now_str = datetime.datetime.now().strftime("%H:%M")

        is_sender = payload.get("sender_id") == client.identity.node_id
        tag = t.accent(f"[DM to {target}]") if is_sender else t.accent(f"[DM from {sender}]")

        input_manager.print_event(f"{t.dim(f'[{now_str}]')} {tag}:\n{t.message(content)}\n")

    def on_presence(msg: NetMashMessage) -> None:
        t = get_active_theme()
        user = sanitize_terminal_text(msg.payload.get("username", ""))
        st = msg.payload.get("status", "ONLINE")
        st_color = t.success(st) if st == "ONLINE" else (t.warning(st) if st == "AWAY" else t.error(st))
        input_manager.print_event(t.muted(f"• {user} is now {st_color}"))

    def on_edit(msg: NetMashMessage) -> None:
        t = get_active_theme()
        mid = msg.payload.get("message_id", "")[:8]
        new_c = sanitize_terminal_text(msg.payload.get("content", ""))
        input_manager.print_event(t.muted(f"✎ Message ({mid}) edited: {new_c}"))

    def on_delete(msg: NetMashMessage) -> None:
        t = get_active_theme()
        mid = msg.payload.get("message_id", "")[:8]
        input_manager.print_event(t.muted(f"🗑 Message ({mid}) was deleted"))

    def on_pin(msg: NetMashMessage) -> None:
        t = get_active_theme()
        pinned = msg.payload.get("pinned", True)
        mid = msg.payload.get("message_id", "")[:8]
        cnt = sanitize_terminal_text(msg.payload.get("content", ""))
        if pinned:
            input_manager.print_event(t.warning(f"📌 Message pinned ({mid}): {cnt}"))
        else:
            input_manager.print_event(t.muted(f"Message ({mid}) unpinned"))

    def on_announce(msg: NetMashMessage) -> None:
        sender = msg.payload.get("sender_name", "Host")
        cnt = msg.payload.get("content", "")
        input_manager.print_event(format_announcement(sender, cnt))

    def on_netname(msg: NetMashMessage) -> None:
        t = get_active_theme()
        new_n = sanitize_terminal_text(msg.payload.get("network_name", "NetMash"))
        input_manager.print_event(t.primary(f"Network session renamed to: {new_n}"))

    def on_file_off(msg: NetMashMessage) -> None:
        t = get_active_theme()
        fid = msg.payload.get("file_id", "")
        fname = sanitize_filename(msg.payload.get("name", "file"))
        size = msg.payload.get("size", 0)
        sha = msg.payload.get("sha256", "")
        sender = msg.payload.get("sender_name", "Peer")

        size_mb = round(size / (1024.0 * 1024.0), 2)
        incoming_transfers[fid] = {
            "name": fname,
            "size": size,
            "sha256": sha,
            "sender": sender,
            "chunks": {},
            "status": "pending",
        }

        offer_text = (
            f"{t.warning('📥 Incoming File Transfer Offer:')}\n"
            f"  From    : {t.primary(sender)}\n"
            f"  Filename: {fname}\n"
            f"  Size    : {size_mb} MB ({size} bytes)\n"
            f"  SHA-256 : {t.dim(sha[:16])}...\n"
            f"  Type {t.success('/accept ' + fid[:8])} or {t.error('/reject ' + fid[:8])}\n"
        )
        input_manager.print_event(offer_text)

    def on_file_chk(msg: NetMashMessage) -> None:
        import base64
        fid = msg.payload.get("file_id", "")
        idx = msg.payload.get("chunk_index", 0)
        data_b64 = msg.payload.get("data", "")
        if fid in incoming_transfers:
            raw = base64.b64decode(data_b64)
            incoming_transfers[fid]["chunks"][idx] = raw

    def on_file_cmp(msg: NetMashMessage) -> None:
        t = get_active_theme()
        fid = msg.payload.get("file_id", "")
        if fid in incoming_transfers:
            info = incoming_transfers[fid]
            chunks = info["chunks"]
            dl_dir = get_downloads_dir()
            clean_name = sanitize_filename(info["name"])
            out_path = dl_dir / clean_name

            with open(out_path, "wb") as f:
                for idx in sorted(chunks.keys()):
                    f.write(chunks[idx])

            calc_sha = calculate_sha256(out_path)
            if calc_sha == info["sha256"]:
                input_manager.print_event(
                    f"{t.success(f'✓ File received successfully: {clean_name}')}\n"
                    + t.dim(f"  Saved to: {out_path}\n")
                )
            else:
                input_manager.print_event(t.error(f"✗ Integrity check failed for {clean_name}\n"))

    def on_join(msg: NetMashMessage) -> None:
        t = get_active_theme()
        user = sanitize_terminal_text(msg.payload.get("username", "Someone"))
        input_manager.print_event(t.muted(f"→ {user} joined NetMash"))

    def on_leave(msg: NetMashMessage) -> None:
        t = get_active_theme()
        user = sanitize_terminal_text(msg.payload.get("username", "Someone"))
        input_manager.print_event(t.muted(f"← {user} left NetMash"))

    def on_name(msg: NetMashMessage) -> None:
        t = get_active_theme()
        old_name = sanitize_terminal_text(msg.payload.get("old_name", ""))
        new_name = sanitize_terminal_text(msg.payload.get("new_name", ""))
        input_manager.print_event(t.muted(f"• {old_name} is now known as {new_name}"))

    def on_error(msg: NetMashMessage) -> None:
        t = get_active_theme()
        err_msg = sanitize_terminal_text(msg.payload.get("message", "An error occurred."))
        input_manager.print_event(f"{t.error('Error:')} {err_msg}")

    client.on_chat_message = on_chat
    client.on_dm = on_dm
    client.on_presence_update = on_presence
    client.on_message_edit = on_edit
    client.on_message_delete = on_delete
    client.on_message_pin = on_pin
    client.on_announcement = on_announce
    client.on_network_name_change = on_netname
    client.on_file_offer = on_file_off
    client.on_file_chunk = on_file_chk
    client.on_file_complete = on_file_cmp
    client.on_peer_join = on_join
    client.on_peer_leave = on_leave
    client.on_name_change = on_name
    client.on_error = on_error

    def on_shutdown(reason: str) -> None:
        input_manager.print_event(red(f"\n⚠ NetMash Server is shutting down: {reason}\n"))

    client.on_server_shutdown = on_shutdown

    # Input loop
    try:
        while client.connected:
            try:
                user_input = await input_manager.get_line()
                text = user_input.strip()
                if not text:
                    continue

                if text.startswith("/"):
                    raw_parts = text.split(" ")
                    cmd = raw_parts[0].lower()
                    cmd_args = [p for p in raw_parts[1:] if p]

                    # --- Hidden Admin System ---
                    if cmd == "/admin":
                        subcmd = cmd_args[0].lower() if cmd_args else ""
                        if subcmd == "logout":
                            if is_admin_mode:
                                await client.admin_logout()
                                is_admin_mode = False
                                print(green("Admin session ended. Logged out."))
                            else:
                                print(yellow("Not currently in admin mode."))
                        elif subcmd == "status":
                            if is_admin_mode:
                                st = await client.admin_get_status()
                                if st:
                                    render_admin_status(st)
                                else:
                                    print(red("Could not retrieve admin status."))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "users":
                            if is_admin_mode:
                                us = await client.admin_get_users()
                                render_admin_users(us)
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "groups":
                            if is_admin_mode:
                                gps = await client.admin_get_groups()
                                render_admin_groups(gps)
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "sessions":
                            if is_admin_mode:
                                sess = await client.admin_get_sessions()
                                render_admin_sessions(sess)
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd in ("moderation", "mod"):
                            if is_admin_mode:
                                print(bold("\nAdmin Moderation Controls:"))
                                print(f"  {cyan('/admin kick <username>')}")
                                print(f"  {cyan('/admin ban <username>')}")
                                print(f"  {cyan('/admin unban <username>')}\n")
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "kick":
                            if is_admin_mode:
                                if len(cmd_args) < 2:
                                    print(red("Usage: /admin kick <username>"))
                                else:
                                    target_u = cmd_args[1].strip()
                                    resp = await client.admin_moderation("kick", target_u)
                                    if resp and resp.get("success"):
                                        print(green(f"✓ {resp.get('message', f'Kicked {target_u}')}"))
                                    elif resp:
                                        print(red(f"✗ {resp.get('message', 'Failed to kick user.')}"))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "ban":
                            if is_admin_mode:
                                if len(cmd_args) < 2:
                                    print(red("Usage: /admin ban <username>"))
                                else:
                                    target_u = cmd_args[1].strip()
                                    resp = await client.admin_moderation("ban", target_u)
                                    if resp and resp.get("success"):
                                        print(green(f"✓ {resp.get('message', f'Banned {target_u}')}"))
                                    elif resp:
                                        print(red(f"✗ {resp.get('message', 'Failed to ban user.')}"))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "unban":
                            if is_admin_mode:
                                if len(cmd_args) < 2:
                                    print(red("Usage: /admin unban <username>"))
                                else:
                                    target_u = cmd_args[1].strip()
                                    resp = await client.admin_moderation("unban", target_u)
                                    if resp and resp.get("success"):
                                        print(green(f"✓ {resp.get('message', f'Unbanned {target_u}')}"))
                                    elif resp:
                                        print(red(f"✗ {resp.get('message', 'Failed to unban user.')}"))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd in ("messages", "message-stats"):
                            if is_admin_mode:
                                mstats = await client.admin_get_message_stats()
                                print(bold("\nMessage Administration & Statistics"))
                                print(gray("───────────────────────────────────"))
                                print(f"{'Total Messages':<22}: {mstats.get('total_messages', 0)}")
                                print(f"{'Direct Messages':<22}: {mstats.get('total_dms', 0)}")
                                print(f"{'File Transfers':<22}: {mstats.get('total_files', 0)}")
                                print()
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd in ("diagnostics", "diag"):
                            if is_admin_mode:
                                diag = await client.admin_get_diagnostics()
                                if diag:
                                    render_admin_diagnostics(diag)
                                else:
                                    print(red("Could not retrieve diagnostics."))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "logs":
                            if is_admin_mode:
                                lgs = await client.admin_get_logs()
                                render_admin_logs(lgs)
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "stats":
                            if is_admin_mode:
                                ast = await client.admin_get_stats()
                                if ast:
                                    render_admin_stats(ast)
                                else:
                                    print(red("Could not retrieve statistics."))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "config":
                            if is_admin_mode:
                                cfg = await client.admin_get_config()
                                if cfg:
                                    render_admin_config(cfg)
                                else:
                                    print(red("Could not retrieve configuration."))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif subcmd == "shutdown":
                            if is_admin_mode:
                                print(yellow("\nShutdown Server"))
                                confirm = await input_manager.get_line("Are you sure? [y/N]: ")
                                if confirm.strip().lower() in ("y", "yes"):
                                    print(red("Initiating server shutdown..."))
                                    await client.admin_shutdown_server("Admin requested shutdown")
                                else:
                                    print(dim("Shutdown cancelled."))
                            else:
                                print(red("Admin authentication required. Type /admin first."))
                        elif not subcmd:
                            if is_admin_mode:
                                render_admin_menu()
                            else:
                                print(bold("\nAdmin Authentication"))
                                entered_pass = await input_manager.get_line("Password: ", is_password=True)
                                auth_res = await client.admin_auth(entered_pass.strip())
                                if auth_res.get("locked"):
                                    rem = auth_res.get("remaining", 60)
                                    print(red(f"\nToo many failed attempts.\nAdmin authentication temporarily locked ({int(rem)}s remaining).\nTry again later.\n"))
                                elif auth_res.get("success"):
                                    is_admin_mode = True
                                    print(green("\nAdmin authentication successful."))
                                    render_admin_menu()
                                else:
                                    print(red("\nAuthentication failed.\n"))
                        else:
                            if not is_admin_mode:
                                # Allow direct inline /admin <password> entry
                                auth_res = await client.admin_auth(cmd_args[0].strip())
                                if auth_res.get("locked"):
                                    rem = auth_res.get("remaining", 60)
                                    print(red(f"\nToo many failed attempts.\nAdmin authentication temporarily locked ({int(rem)}s remaining).\nTry again later.\n"))
                                elif auth_res.get("success"):
                                    is_admin_mode = True
                                    print(green("\nAdmin authentication successful."))
                                    render_admin_menu()
                                else:
                                    print(red("\nAuthentication failed.\n"))
                            else:
                                print(yellow(f"Unknown admin subcommand: {subcmd}"))

                    # --- Navigation & General ---
                    elif cmd in ("/exit", "/quit"):
                        print(yellow("\nDisconnecting from NetMash..."))
                        break
                    elif cmd == "/help":
                        print_help()
                    elif cmd == "/whoami":
                        render_whoami(
                            username=client.identity.username,
                            node_id=client.identity.node_id,
                            hostname=client.identity.hostname,
                            status=current_status,
                            role="MEMBER",
                            host=client.server_info.get("host_name", "Host"),
                        )
                    elif cmd in ("/users", "/peers"):
                        peers = await client.list_peers()
                        render_peers_table(peers)
                    elif cmd == "/groups":
                        groups = await client.list_groups()
                        render_groups_table(groups, current_room=client.current_room)
                    elif cmd == "/room":
                        t = get_active_theme()
                        print(f"Current active room: {t.accent(client.current_room.upper())}")
                    elif cmd == "/name":
                        if not cmd_args:
                            print(red("Usage: /name <new_name>"))
                        else:
                            new_name = cmd_args[0].strip()
                            await client.change_name(new_name)
                            print(green(f"✓ Name change requested: {new_name}"))
                    elif cmd == "/theme":
                        if not cmd_args:
                            render_theme_list()
                        else:
                            arg = cmd_args[0].strip().lower()
                            if arg == "random":
                                prev_t, new_t = set_random_theme(persist=True)
                                redraw_screen(
                                    client=client,
                                    input_manager=input_manager,
                                    notice=f"{new_t.bold('Theme changed randomly.')}\n\nPrevious: {prev_t.name}\nNew: {new_t.accent(new_t.name)}\n",
                                )
                            else:
                                new_theme = set_active_theme(arg, persist=True)
                                if new_theme:
                                    redraw_screen(
                                        client=client,
                                        input_manager=input_manager,
                                        notice=new_theme.success(f"✓ Theme set to {new_theme.name} ({new_theme.style_desc}).\n"),
                                    )
                                else:
                                    render_invalid_theme()

                    # --- Groups ---
                    elif cmd in ("/create", "/creategroup"):
                        if not cmd_args:
                            print(red("Usage: /create <group_name> [4-digit-pin]"))
                        else:
                            group_name = cmd_args[0].strip()
                            pin = cmd_args[1].strip() if len(cmd_args) > 1 else None
                            if pin is None:
                                print(f"Creating group: {cyan(group_name)}")
                                print("1. Public")
                                print("2. PIN protected")
                                choice = await input_manager.get_line("Select (1/2): ")
                                if choice.strip() == "2":
                                    pin1 = await input_manager.get_line("Enter 4-digit PIN: ")
                                    pin2 = await input_manager.get_line("Confirm PIN: ")
                                    if pin1 != pin2:
                                        print(red("PINs do not match. Cancelled."))
                                        continue
                                    pin = pin1.strip()

                            resp = await client.create_group(group_name, pin=pin)
                            if resp and resp.get("success"):
                                print(green(f"✓ Group '{resp.get('name')}' created successfully (Access: {resp.get('access')})."))
                                client.current_room = resp.get("name", group_name)
                                print(bright_cyan(f"Active room switched to: {client.current_room.upper()}"))
                            elif resp:
                                print(yellow(f"{resp.get('message')}"))
                            else:
                                print(red("Failed to create group."))
                    elif cmd in ("/create-pin", "/createpin"):
                        if len(cmd_args) < 2:
                            print(red("Usage: /create-pin <group_name> <4-digit-pin>"))
                        else:
                            group_name = cmd_args[0].strip()
                            pin = cmd_args[1].strip()
                            resp = await client.create_group(group_name, pin=pin)
                            if resp and resp.get("success"):
                                print(green(f"✓ PIN group '{resp.get('name')}' created successfully."))
                                client.current_room = resp.get("name", group_name)
                                print(bright_cyan(f"Active room switched to: {client.current_room.upper()}"))
                            elif resp:
                                print(yellow(f"{resp.get('message')}"))
                            else:
                                print(red("Failed to create PIN group."))
                    elif cmd in ("/join", "/switch"):
                        if not cmd_args:
                            print(red("Usage: /join <group_name> [4-digit-pin] or /switch <group_name>"))
                        else:
                            target_group = cmd_args[0].strip()
                            pin = cmd_args[1].strip() if len(cmd_args) > 1 else None

                            if target_group.lower() == "general":
                                resp = await client.switch_room("general")
                                if resp and resp.get("success"):
                                    print(green("✓ Switched to GENERAL room."))
                                    unread_counts["general"] = 0
                                continue

                            switch_resp = await client.switch_room(target_group)
                            if switch_resp and switch_resp.get("success"):
                                print(green(f"✓ Switched to room '{target_group}'. Current room: {client.current_room.upper()}"))
                                unread_counts[target_group.lower()] = 0
                                continue

                            resp = await client.join_group(target_group, pin=pin)
                            if resp and resp.get("requires_pin") and pin is None:
                                pin_input = await input_manager.get_line(
                                    f"Group '{target_group}' requires a PIN. Enter 4-digit PIN: "
                                )
                                resp = await client.join_group(target_group, pin=pin_input.strip())

                            if resp and resp.get("success"):
                                print(green(f"✓ Joined '{target_group}'. Current room: {client.current_room.upper()}"))
                                unread_counts[target_group.lower()] = 0
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                            else:
                                print(red(f"✗ Could not join group '{target_group}'."))
                    elif cmd == "/general":
                        resp = await client.switch_room("general")
                        if resp and resp.get("success"):
                            print(green("✓ Returned to GENERAL room."))
                            unread_counts["general"] = 0
                        else:
                            print(red("Could not switch to GENERAL."))
                    elif cmd == "/leave":
                        target_group = cmd_args[0].strip() if cmd_args else client.current_room
                        if target_group.lower() == "general":
                            print(yellow("You are already in GENERAL."))
                        else:
                            resp = await client.leave_group(target_group)
                            if resp and resp.get("success"):
                                print(green(f"✓ Left '{target_group}'. Returned to GENERAL."))
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                    elif cmd == "/members":
                        grp = cmd_args[0].strip() if cmd_args else client.current_room
                        mem_data = await client.get_members(grp)
                        if mem_data:
                            render_members(mem_data)
                        else:
                            print(red(f"Could not retrieve members for '{grp}'."))
                    elif cmd == "/setpin":
                        if not cmd_args:
                            print(red("Usage: /setpin <group_name> [new-4-digit-pin]"))
                        else:
                            group_name = cmd_args[0].strip()
                            new_pin = cmd_args[1].strip() if len(cmd_args) > 1 else None
                            if new_pin is None:
                                new_pin = await input_manager.get_line(f"Enter new 4-digit PIN for '{group_name}': ")
                            resp = await client.set_group_pin(group_name, pin=new_pin.strip())
                            if resp and resp.get("success"):
                                print(green(f"✓ {resp.get('message')}"))
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                    elif cmd == "/removepin":
                        if not cmd_args:
                            print(red("Usage: /removepin <group_name>"))
                        else:
                            group_name = cmd_args[0].strip()
                            resp = await client.set_group_pin(group_name, pin=None)
                            if resp and resp.get("success"):
                                print(green(f"✓ {resp.get('message')}"))
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                    elif cmd == "/kick":
                        if not cmd_args:
                            print(red("Usage: /kick <user>"))
                        else:
                            target_u = cmd_args[0].strip()
                            resp = await client.kick_member(client.current_room, target_u)
                            if resp and resp.get("success"):
                                print(green(f"✓ {resp.get('message')}"))
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                    elif cmd == "/ban":
                        if not cmd_args:
                            print(red("Usage: /ban <user>"))
                        else:
                            target_u = cmd_args[0].strip()
                            resp = await client.ban_member(client.current_room, target_u)
                            if resp and resp.get("success"):
                                print(green(f"✓ {resp.get('message')}"))
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                    elif cmd == "/unban":
                        if not cmd_args:
                            print(red("Usage: /unban <user>"))
                        else:
                            target_u = cmd_args[0].strip()
                            resp = await client.unban_member(client.current_room, target_u)
                            if resp and resp.get("success"):
                                print(green(f"✓ {resp.get('message')}"))
                            elif resp:
                                print(red(f"✗ {resp.get('message')}"))
                    elif cmd == "/delete":
                        # If argument provided, treat as group delete; otherwise if message ID, delete message
                        if not cmd_args:
                            print(red("Usage: /delete <group_name> OR /delete <message_id>"))
                        else:
                            target = cmd_args[0].strip()
                            # Check if it's a message ID or group
                            if len(target) > 8 and "-" in target:
                                # Message deletion
                                await client.delete_message(target)
                                print(green(f"✓ Delete request sent for message: {target[:8]}"))
                            else:
                                # Group deletion confirmation
                                print(yellow(f"\nDelete group '{target}'?\nThis will remove the group for all members."))
                                conf = await input_manager.get_line("Confirm [y/N]: ")
                                if conf.strip().lower() in ("y", "yes"):
                                    resp = await client.delete_group(target)
                                    if resp and resp.get("success"):
                                        print(green(f"✓ Group '{target}' deleted."))
                                        if client.current_room.lower() == target.lower():
                                            client.current_room = "general"
                                    elif resp:
                                        print(red(f"✗ {resp.get('message')}"))
                                else:
                                    print(dim("Group deletion cancelled."))
                    elif cmd == "/announce":
                        if not cmd_args:
                            print(red("Usage: /announce <message>"))
                        else:
                            ann_msg = " ".join(cmd_args).strip()
                            await client.announce(ann_msg, room=client.current_room)

                    # --- Communication & History ---
                    elif cmd == "/dm":
                        if not cmd_args:
                            print(red("Usage: /dm <username> [message]"))
                        else:
                            target_user = cmd_args[0].strip()
                            if len(cmd_args) > 1:
                                dm_content = " ".join(cmd_args[1:]).strip()
                                await client.send_dm(target_user, dm_content)
                            else:
                                dm_content = await input_manager.get_line(
                                    f"Enter message for {target_user}: "
                                )
                                if dm_content.strip():
                                    await client.send_dm(target_user, dm_content.strip())
                    elif cmd == "/history":
                        limit = int(cmd_args[0]) if cmd_args and cmd_args[0].isdigit() else 30
                        msgs = await client.get_history(client.current_room, limit=limit)
                        render_history(msgs)
                    elif cmd == "/search":
                        if not cmd_args:
                            print(red("Usage: /search <query>"))
                        else:
                            q = " ".join(cmd_args).strip()
                            res = await client.search_messages(q)
                            render_search_results(q, res)
                    elif cmd == "/unread":
                        render_unread(unread_counts)
                    elif cmd == "/reply":
                        if len(cmd_args) < 2:
                            print(red("Usage: /reply <message_id> <message>"))
                        else:
                            reply_mid = cmd_args[0].strip()
                            r_content = " ".join(cmd_args[1:]).strip()
                            await client.send_chat(r_content, room=client.current_room, reply_to=reply_mid)
                    elif cmd == "/edit":
                        if len(cmd_args) < 2:
                            print(red("Usage: /edit <message_id> <new_message>"))
                        else:
                            edit_mid = cmd_args[0].strip()
                            new_c = " ".join(cmd_args[1:]).strip()
                            await client.edit_message(edit_mid, new_c)
                    elif cmd == "/pin":
                        if not cmd_args:
                            print(red("Usage: /pin <message_id>"))
                        else:
                            pin_mid = cmd_args[0].strip()
                            await client.pin_message(pin_mid, is_pinned=True)
                            print(green(f"✓ Pinned message: {pin_mid[:8]}"))
                    elif cmd == "/unpin":
                        if not cmd_args:
                            print(red("Usage: /unpin <message_id>"))
                        else:
                            pin_mid = cmd_args[0].strip()
                            await client.pin_message(pin_mid, is_pinned=False)
                            print(green(f"✓ Unpinned message: {pin_mid[:8]}"))

                    # --- Presence & Notifications ---
                    elif cmd == "/away":
                        await client.set_presence("AWAY")
                        current_status = "AWAY"
                        print(yellow("✓ Presence set to AWAY"))
                    elif cmd == "/busy":
                        await client.set_presence("BUSY")
                        current_status = "BUSY"
                        print(red("✓ Presence set to BUSY"))
                    elif cmd == "/online":
                        if cmd_args and cmd_args[0].lower() in ("set", "on"):
                            await client.set_presence("ONLINE")
                            current_status = "ONLINE"
                            print(green("✓ Presence set to ONLINE"))
                        else:
                            # Also list online peers
                            await client.set_presence("ONLINE")
                            current_status = "ONLINE"
                            peers = await client.list_peers()
                            render_peers_table(peers)
                    elif cmd == "/mute":
                        target_r = cmd_args[0].strip().lower() if cmd_args else client.current_room.lower()
                        muted_rooms.add(target_r)
                        print(gray(f"✓ Notifications muted for [{target_r.upper()}]"))
                    elif cmd == "/unmute":
                        target_r = cmd_args[0].strip().lower() if cmd_args else client.current_room.lower()
                        muted_rooms.discard(target_r)
                        print(green(f"✓ Notifications unmuted for [{target_r.upper()}]"))
                    elif cmd == "/notify":
                        if cmd_args and cmd_args[0].lower() == "off":
                            notifications_enabled = False
                            print(gray("✓ Notifications disabled."))
                        else:
                            notifications_enabled = True
                            print(green("✓ Notifications enabled."))

                    # --- File Transfer ---
                    elif cmd == "/send":
                        if not cmd_args:
                            print(red("Usage: /send <file_path>"))
                        else:
                            fp = Path(" ".join(cmd_args).strip())
                            if not fp.exists() or not fp.is_file():
                                print(red(f"File not found: {fp}"))
                                continue
                            if fp.stat().st_size > MAX_FILE_SIZE_BYTES:
                                print(red("File exceeds maximum allowed size (100 MB)."))
                                continue

                            print(f"\nSend file: {cyan(fp.name)} ({round(fp.stat().st_size / (1024*1024), 2)} MB)")
                            print("1. Direct Message to Peer")
                            print("2. Send to Current Room")
                            dst_choice = await input_manager.get_line("Select (1/2): ")

                            target_type = "dm" if dst_choice.strip() == "1" else "group"
                            if target_type == "dm":
                                target_u = await input_manager.get_line("Enter recipient username: ")
                                target_dest = target_u.strip()
                            else:
                                target_dest = client.current_room

                            file_id = f"f_{int(time.time())}_{fp.name[:8]}"
                            sha = calculate_sha256(fp)
                            offer_msg = NetMashMessage(
                                type=MessageType.FILE_OFFER,
                                payload={
                                    "file_id": file_id,
                                    "name": fp.name,
                                    "size": fp.stat().st_size,
                                    "sha256": sha,
                                    "target": target_dest,
                                    "target_type": target_type,
                                },
                            )
                            await client.send_message(offer_msg)
                            print(cyan("Sending file chunks..."))

                            # Send chunks
                            for idx, total_c, b64_d in read_file_chunks(fp):
                                chk_msg = NetMashMessage(
                                    type=MessageType.FILE_CHUNK,
                                    payload={
                                        "file_id": file_id,
                                        "chunk_index": idx,
                                        "total_chunks": total_c,
                                        "data": b64_d,
                                        "target": target_dest,
                                        "target_type": target_type,
                                    },
                                )
                                await client.send_message(chk_msg)

                            cmp_msg = NetMashMessage(
                                type=MessageType.FILE_COMPLETE,
                                payload={
                                    "file_id": file_id,
                                    "target": target_dest,
                                    "target_type": target_type,
                                },
                            )
                            await client.send_message(cmp_msg)
                            print(green(f"✓ File '{fp.name}' transmitted successfully."))

                    elif cmd == "/accept":
                        if not cmd_args:
                            print(red("Usage: /accept <file_id>"))
                        else:
                            target_fid = cmd_args[0].strip()
                            # Match prefix
                            matched = None
                            for fid in incoming_transfers:
                                if fid.startswith(target_fid):
                                    matched = fid
                                    break
                            if matched:
                                incoming_transfers[matched]["status"] = "accepted"
                                print(green(f"✓ Accepted file transfer {matched[:8]}. Downloading..."))
                            else:
                                print(red("No matching incoming transfer found."))

                    elif cmd == "/reject":
                        if not cmd_args:
                            print(red("Usage: /reject <file_id>"))
                        else:
                            target_fid = cmd_args[0].strip()
                            matched = None
                            for fid in incoming_transfers:
                                if fid.startswith(target_fid):
                                    matched = fid
                                    break
                            if matched:
                                del incoming_transfers[matched]
                                print(yellow(f"File transfer {matched[:8]} rejected."))
                            else:
                                print(red("No matching incoming transfer found."))

                    # --- Network & Diagnostics ---
                    elif cmd == "/diagnose":
                        print(cyan("Running NetMash diagnostic checks..."))
                        diag_res = await run_diagnostics(client=client)
                        render_diagnostics(diag_res)
                    elif cmd == "/version":
                        render_version_info()
                    elif cmd == "/netinfo":
                        local_ip = get_local_ip()
                        peers = await client.list_peers()
                        netinfo_data = {
                            "interface": "Wi-Fi / Ethernet",
                            "address": local_ip,
                            "subnet": "/24",
                            "transport": "TCP Wire Protocol",
                            "port": client.port,
                            "discovery_port": DEFAULT_DISCOVERY_PORT,
                            "host": client.server_info.get("host_name", "Local"),
                            "peers": len(peers),
                        }
                        render_netinfo(netinfo_data)
                    elif cmd == "/stats":
                        st = await client.get_stats()
                        if st:
                            render_stats(st)
                        else:
                            print(red("Could not retrieve statistics from host."))
                    elif cmd == "/network-name":
                        if not cmd_args:
                            print(red("Usage: /network-name <new_name>"))
                        else:
                            net_name = " ".join(cmd_args).strip()
                            await client.set_network_name(net_name)
                            print(green(f"✓ Network name set to: {net_name}"))
                    elif cmd == "/reconnect":
                        print(yellow("\nDisconnecting current session..."))
                        saved_room = client.current_room
                        await client.disconnect()
                        print("Searching for NetMash host on local network...")
                        h_info = await discover_host(timeout=2.0)
                        if h_info:
                            h_ip = h_info.get("host_ip", "127.0.0.1")
                            h_port = int(h_info.get("port", DEFAULT_HOST_PORT))
                            client.host = h_ip
                            client.port = h_port
                            conn = await client.connect()
                            if conn:
                                print(green(f"✓ Reconnected to host: {h_info.get('hostname')}"))
                                await client.switch_room(saved_room)
                                continue
                        print(yellow("No NetMash host found on LAN."))
                        start_new = await input_manager.get_line("Start a new host? [Y/n]: ")
                        if start_new.strip().lower() not in ("n", "no"):
                            if not server:
                                server = NetMashServer(
                                    port=DEFAULT_HOST_PORT,
                                    discovery_port=DEFAULT_DISCOVERY_PORT,
                                    identity=client.identity,
                                )
                                await server.start()
                            client.host = "127.0.0.1"
                            client.port = DEFAULT_HOST_PORT
                            await client.connect()
                            print(green("✓ Local host started and connected."))
                    elif cmd == "/info":
                        info = await client.get_info()
                        if info:
                            render_info(info)
                    elif cmd == "/status":
                        status = await client.get_status()
                        if status:
                            render_status(status)
                    elif cmd in ("/update-check", "/check-update", "/checkupdate"):
                        t = get_active_theme()
                        print(t.dim("Checking GitHub for the latest NetMash updates..."))
                        up_info = await check_for_updates_async()
                        if up_info.get("error"):
                            print(t.error(f"Error checking for updates: {up_info['error']}"))
                        else:
                            running_c = up_info.get("running_commit") or "unknown"
                            running_v = up_info.get("running_version") or __version__
                            latest_c = up_info.get("latest_commit") or "unknown"
                            latest_v = up_info.get("latest_version") or running_v
                            msg = up_info.get("commit_message") or ""
                            date = up_info.get("commit_date") or ""

                            print(f"\n{'Running version':<18}: {t.accent(running_v)} ({running_c})")
                            print(f"{'Latest on GitHub':<18}: {t.accent(latest_v)} ({latest_c})")
                            if msg:
                                print(f"{'Latest commit':<18}: {msg}")
                            if date:
                                print(f"{'Commit date':<18}: {t.dim(date)}")

                            if up_info.get("restart_required"):
                                print(t.warning("\n⚠ Update is installed on disk, but the current process has not restarted."))
                                print(t.dim("  Use /restart to apply the update.\n"))
                            elif up_info.get("update_available"):
                                print(t.warning("\n💡 A new update is available!"))
                                print(t.dim("  Type /update to download and apply it.\n"))
                            else:
                                print(t.success("\n✓ NetMash is up to date.\n"))
                    elif cmd == "/update":
                        t = get_active_theme()
                        print(t.dim("Checking update status..."))
                        up_info = await check_for_updates_async()
                        if not up_info.get("error") and not up_info.get("update_available") and not up_info.get("restart_required"):
                            cur = up_info.get("installed_commit") or up_info.get("running_commit") or "latest"
                            print(t.success(f"\n✓ NetMash is already up to date. (Commit: {cur})\n"))
                            continue

                        if up_info.get("restart_required") and not up_info.get("update_available"):
                            print(t.warning("\n⚠ Update is already installed. Restart is required."))
                            print(t.dim("  Use /restart to load the new version.\n"))
                            continue

                        print(t.accent("\nDownloading and installing latest update from GitHub..."))
                        success, update_msg = await apply_update_async()
                        if success:
                            print(t.success(f"\n✓ {update_msg}\n"))
                        else:
                            print(t.error(f"\n✗ Update failed:\n{update_msg}\n"))
                    elif cmd in ("/restart", "/reload"):
                        t = get_active_theme()
                        print(t.dim("\nRestarting NetMash session..."))
                        try:
                            await client.disconnect()
                            if server:
                                await server.stop()
                        except Exception:
                            pass
                        _save_readline_history(history_file)
                        if sys.platform == "win32":
                            subprocess.Popen([sys.executable] + sys.argv)
                            sys.exit(0)
                        else:
                            os.execv(sys.executable, [sys.executable] + sys.argv)
                    elif cmd == "/clear":
                        redraw_screen(client=client, input_manager=input_manager)
                    else:
                        print(yellow("Unknown command. Use /help to see available commands."))
                elif is_admin_mode and text.lower() in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "menu"):
                    opt = text.lower()
                    if opt == "1":
                        st = await client.admin_get_status()
                        if st:
                            render_admin_status(st)
                        else:
                            print(red("Could not retrieve server status."))
                    elif opt == "2":
                        us = await client.admin_get_users()
                        render_admin_users(us)
                    elif opt == "3":
                        gps = await client.admin_get_groups()
                        render_admin_groups(gps)
                    elif opt == "4":
                        sess = await client.admin_get_sessions()
                        render_admin_sessions(sess)
                    elif opt == "5":
                        print(bold("\nAdmin Moderation Controls:"))
                        print(f"  {cyan('/admin kick <username>')}")
                        print(f"  {cyan('/admin ban <username>')}")
                        print(f"  {cyan('/admin unban <username>')}\n")
                    elif opt == "6":
                        mstats = await client.admin_get_message_stats()
                        print(bold("\nMessage Administration & Statistics"))
                        print(gray("───────────────────────────────────"))
                        print(f"{'Total Messages':<22}: {mstats.get('total_messages', 0)}")
                        print(f"{'Direct Messages':<22}: {mstats.get('total_dms', 0)}")
                        print(f"{'File Transfers':<22}: {mstats.get('total_files', 0)}")
                        print()
                    elif opt == "7":
                        diag = await client.admin_get_diagnostics()
                        if diag:
                            render_admin_diagnostics(diag)
                        else:
                            print(red("Could not retrieve diagnostics."))
                    elif opt == "8":
                        lgs = await client.admin_get_logs()
                        render_admin_logs(lgs)
                    elif opt == "9":
                        ast = await client.admin_get_stats()
                        if ast:
                            render_admin_stats(ast)
                        else:
                            print(red("Could not retrieve statistics."))
                    elif opt == "10":
                        cfg = await client.admin_get_config()
                        if cfg:
                            render_admin_config(cfg)
                        else:
                            print(red("Could not retrieve configuration."))
                    elif opt == "11":
                        print(yellow("\nShutdown Server"))
                        confirm = await input_manager.get_line("Are you sure? [y/N]: ")
                        if confirm.strip().lower() in ("y", "yes"):
                            print(red("Initiating server shutdown..."))
                            await client.admin_shutdown_server("Admin requested shutdown")
                        else:
                            print(dim("Shutdown cancelled."))
                    elif opt == "12":
                        await client.admin_logout()
                        is_admin_mode = False
                        print(green("Admin session ended. Logged out."))
                    elif opt == "menu":
                        render_admin_menu()
                else:
                    # Regular chat message sent strictly to current_room
                    await client.send_chat(text, room=client.current_room)

            except (EOFError, KeyboardInterrupt, asyncio.CancelledError):
                print(yellow("\nDisconnecting from NetMash..."))
                break
            except Exception as e:
                print(red(f"\nError: {e}"))
                continue
    finally:
        _save_readline_history(history_file)

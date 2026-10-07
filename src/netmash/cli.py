"""
CLI Entry Point and command dispatcher for NetMash.
Parses CLI flags, orchestrates automatic host discovery and hosting,
supports multi-network selection, and dispatches interactive chat and subcommands.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import List, Optional, Tuple

from netmash import __version__
from netmash.client.client import NetMashClient
from netmash.config import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_HOST_PORT,
    DEFAULT_MULTICAST_GROUP,
)
from netmash.discovery.service import discover_hosts_all
from netmash.identity import get_or_create_identity
from netmash.server.server import NetMashServer
from netmash.ui.colors import (
    bold,
    cyan,
    dim,
    gray,
    green,
    init_colors,
    red,
    yellow,
)
from netmash.ui.terminal import (
    print_banner,
    render_diagnostics,
    render_groups_table,
    render_info,
    render_members,
    render_netinfo,
    render_peers_table,
    render_stats,
    render_status,
    render_version_info,
    render_whoami,
    run_interactive_chat,
)
from netmash.updater import (
    apply_update_async,
    check_for_updates_async,
    render_version_diagnostics,
)
from netmash.utils.diagnostics import run_diagnostics
from netmash.utils.network import get_local_ip, get_platform_info


def build_parser() -> argparse.ArgumentParser:
    """Builds the NetMash argument parser with subcommands and short options."""
    parser = argparse.ArgumentParser(
        prog="netmash",
        description="NetMash - Local-network peer communication and discovery platform.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # General flags
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"NetMash {__version__}",
        help="Show version information and exit.",
    )
    parser.add_argument(
        "-i", "--info",
        action="store_true",
        help="Display local node and network information.",
    )
    parser.add_argument(
        "-s", "--status",
        action="store_true",
        help="Check status of the active NetMash host and connection.",
    )
    parser.add_argument(
        "-n", "--nodes",
        dest="nodes",
        action="store_true",
        help="List all active online NetMash peers on the network.",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run comprehensive NetMash diagnostic checks.",
    )
    parser.add_argument(
        "--whoami",
        action="store_true",
        help="Show persistent node identity.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Display server throughput and statistics.",
    )
    parser.add_argument(
        "--netinfo",
        action="store_true",
        help="Display local network interface and routing details.",
    )
    parser.add_argument(
        "--name",
        type=str,
        metavar="NAME",
        help="Set or override your display name for this session.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HOST_PORT,
        metavar="PORT",
        help=f"Port to bind or connect to (default: {DEFAULT_HOST_PORT}).",
    )
    parser.add_argument(
        "--discovery-port",
        type=int,
        default=DEFAULT_DISCOVERY_PORT,
        metavar="PORT",
        help=f"UDP discovery port (default: {DEFAULT_DISCOVERY_PORT}).",
    )
    parser.add_argument(
        "--host-only",
        action="store_true",
        help="Run as a dedicated NetMash host without opening interactive chat.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color formatting in output.",
    )
    parser.add_argument(
        "-g", "--group",
        dest="group_flag",
        action="store_true",
        help="Open group management / list groups.",
    )
    parser.add_argument(
        "-l", "--list",
        dest="list_flag",
        action="store_true",
        help="List available groups (when combined with -g).",
    )
    parser.add_argument(
        "-j", "--join",
        dest="join_group_name",
        type=str,
        metavar="GROUP",
        help="Join a specific group directly.",
    )

    parser.add_argument(
        "--check-update",
        action="store_true",
        help="Check GitHub for the latest updates to NetMash.",
    )
    parser.add_argument(
        "--update",
        dest="update_flag",
        action="store_true",
        help="Automatically download and apply the latest update from GitHub.",
    )
    parser.add_argument(
        "--restart",
        dest="restart_flag",
        action="store_true",
        help="Restart NetMash session.",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommands")

    # diagnose subcommand
    subparsers.add_parser("diagnose", help="Run diagnostic checks")

    # whoami subcommand
    subparsers.add_parser("whoami", help="Show node identity")

    # stats subcommand
    subparsers.add_parser("stats", help="Show host statistics")

    # netinfo subcommand
    subparsers.add_parser("netinfo", help="Show network info")

    # restart subcommand
    subparsers.add_parser("restart", help="Restart NetMash session")

    # version subcommand
    subparsers.add_parser("version", help="Show complete version and runtime information")

    # update subcommand
    update_p = subparsers.add_parser("update", help="Check and apply NetMash updates from GitHub")
    update_p.add_argument(
        "--check",
        dest="update_check",
        action="store_true",
        help="Check for updates without installing them",
    )

    # group subcommand
    group_parser = subparsers.add_parser("group", help="Manage groups")
    group_subparsers = group_parser.add_subparsers(
        dest="group_action", help="Group actions"
    )

    # group create
    create_p = group_subparsers.add_parser("create", help="Create a new group")
    create_p.add_argument("group_name", help="Name of the group to create")
    create_p.add_argument(
        "--pin",
        nargs="?",
        const="PROMPT",
        default=None,
        help="4-digit PIN for the group (leave blank to prompt interactively)",
    )

    # group list
    group_subparsers.add_parser("list", help="List all available groups")

    # group join
    join_p = group_subparsers.add_parser("join", help="Join an existing group")
    join_p.add_argument("group_name", help="Name of the group to join")
    join_p.add_argument(
        "--pin",
        type=str,
        default=None,
        help="4-digit PIN if the group is protected",
    )

    # group set-pin
    set_pin_p = group_subparsers.add_parser("set-pin", help="Set or update group PIN (owner only)")
    set_pin_p.add_argument("group_name", help="Name of the group")
    set_pin_p.add_argument("pin", nargs="?", default=None, help="New 4-digit PIN")

    # group remove-pin
    rm_pin_p = group_subparsers.add_parser("remove-pin", help="Remove group PIN and make public (owner only)")
    rm_pin_p.add_argument("group_name", help="Name of the group")

    # group leave
    leave_p = group_subparsers.add_parser("leave", help="Leave a group")
    leave_p.add_argument("group_name", help="Name of the group to leave")

    # group members
    mem_p = group_subparsers.add_parser("members", help="List group members by role")
    mem_p.add_argument("group_name", help="Name of the group")

    # group info
    info_p = group_subparsers.add_parser("info", help="Get info about a group")
    info_p.add_argument("group_name", help="Name of the group")

    # peers subcommand alias
    subparsers.add_parser("peers", help="List online peers (alias for -n)")

    # dm subcommand
    dm_p = subparsers.add_parser("dm", help="Send a direct message to a peer")
    dm_p.add_argument("target_user", help="Username of the peer to message")
    dm_p.add_argument(
        "message", nargs="?", default=None, help="Message content (optional)"
    )

    return parser


async def get_or_discover_client(
    port: int,
    discovery_port: int,
    custom_name: Optional[str] = None,
    timeout: float = 1.5,
    interactive_choice: bool = True,
) -> Tuple[Optional[NetMashClient], Optional[dict]]:
    """
    Attempts to discover active NetMash hosts on the local network.
    If multiple hosts are discovered, prompts the user to select one if interactive.
    Connects to chosen host and returns (client, host_info).
    If not found, returns (None, None).
    """
    identity = get_or_create_identity(custom_name)
    found_hosts = await discover_hosts_all(
        timeout=timeout,
        multicast_group=DEFAULT_MULTICAST_GROUP,
        discovery_port=discovery_port,
    )

    if not found_hosts:
        return None, None

    chosen_host = found_hosts[0]

    # Handle multiple networks discovered
    if len(found_hosts) > 1 and interactive_choice:
        print(bold("\nFound multiple NetMash networks:\n"))
        for idx, h in enumerate(found_hosts, 1):
            net_name = h.get("network_name", "NetMash Local")
            h_host = h.get("hostname", "Host")
            h_ip = h.get("host_ip", "127.0.0.1")
            h_p = h.get("port", port)
            print(f"  {cyan(str(idx))}. {bold(net_name)} ({h_host} - {h_ip}:{h_p})")
        print()

        try:
            sel = input(f"Select network (1-{len(found_hosts)}) [1]: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(found_hosts):
                chosen_host = found_hosts[int(sel) - 1]
        except (EOFError, KeyboardInterrupt):
            pass

    host_ip = chosen_host.get("host_ip", "127.0.0.1")
    host_port = int(chosen_host.get("port", port))
    client = NetMashClient(host=host_ip, port=host_port, identity=identity)
    connected = await client.connect(timeout=3.0)
    if connected:
        return client, chosen_host
    else:
        await client.disconnect()

    return None, None


async def handle_oneshot_command(args: argparse.Namespace) -> bool:
    """
    Handles one-shot commands like -i, -s, -n, --diagnose, --whoami, etc.
    Returns True if handled, False if standard interactive mode should proceed.
    """
    # -1. Version subcommand
    if getattr(args, "subcommand", None) == "version":
        render_version_info()
        return True

    # 0. Update commands
    is_update_check = getattr(args, "check_update", False) or (
        getattr(args, "subcommand", None) == "update"
        and getattr(args, "update_check", False)
    )
    is_update_apply = getattr(args, "update_flag", False) or (
        getattr(args, "subcommand", None) == "update"
        and not getattr(args, "update_check", False)
    )

    if is_update_check:
        print("Checking GitHub for the latest NetMash updates...")
        info = await check_for_updates_async()
        if info.get("error"):
            print(red(f"Error checking for updates: {info['error']}"))
        else:
            running_c = info.get("running_commit") or "unknown"
            running_v = info.get("running_version") or __version__
            latest_c = info.get("latest_commit") or "unknown"
            latest_v = info.get("latest_version") or running_v
            msg = info.get("commit_message") or ""
            date = info.get("commit_date") or ""

            print(f"\n{'Running version':<18}: {cyan(running_v)} ({running_c})")
            print(f"{'Latest on GitHub':<18}: {cyan(latest_v)} ({latest_c})")
            if msg:
                print(f"{'Latest commit':<18}: {msg}")
            if date:
                print(f"{'Commit date':<18}: {dim(date)}")

            if info.get("restart_required"):
                print(yellow("\n⚠ Update is installed on disk, but the current process has not restarted."))
                print(dim("  Use netmash restart to apply the update.\n"))
            elif info.get("update_available"):
                print(yellow("\n💡 A new update is available!"))
                print(dim("  Run: netmash update\n"))
            else:
                print(green("\n✓ NetMash is up to date!\n"))
        return True

    if is_update_apply:
        print("Checking update status...")
        info = await check_for_updates_async()
        if not info.get("error") and not info.get("update_available") and not info.get("restart_required"):
            cur = info.get("installed_commit") or info.get("running_commit") or "latest"
            print(green(f"\n✓ NetMash is already up to date! (Commit: {cur})\n"))
            return True

        if info.get("restart_required") and not info.get("update_available"):
            print(yellow("\n⚠ Update is already installed. Restart is required."))
            print(dim("  Run: netmash restart\n"))
            return True

        print(cyan("Applying latest update from GitHub (https://github.com/Shadab-2604/netmash.git)..."))
        success, msg = await apply_update_async()
        if success:
            print(green(f"\n✓ {msg}"))
            print(green("Restart NetMash to use the updated version.\n"))
        else:
            print(red(f"\n✗ Update failed:\n{msg}\n"))
        return True

    # 1. Diagnostics command (--diagnose / diagnose)
    if args.diagnose or getattr(args, "subcommand", None) == "diagnose":
        diag_res = await run_diagnostics()
        render_diagnostics(diag_res)
        return True

    # 2. Whoami command (--whoami / whoami)
    if args.whoami or getattr(args, "subcommand", None) == "whoami":
        identity = get_or_create_identity(args.name)
        render_whoami(
            username=identity.username,
            node_id=identity.node_id,
            hostname=identity.hostname,
            status="ONLINE",
            role="MEMBER",
            host=identity.hostname,
        )
        return True

    # 3. Netinfo command (--netinfo / netinfo)
    if args.netinfo or getattr(args, "subcommand", None) == "netinfo":
        local_ip = get_local_ip()
        netinfo_data = {
            "interface": "Wi-Fi / Ethernet",
            "address": local_ip,
            "subnet": "/24",
            "transport": "TCP Wire Protocol",
            "port": args.port,
            "discovery_port": args.discovery_port,
            "host": "Local",
            "peers": 1,
        }
        render_netinfo(netinfo_data)
        return True

    # Handle restart CLI flag or subcommand
    is_restart_cmd = getattr(args, "restart_flag", False) or getattr(args, "subcommand", None) == "restart"
    if is_restart_cmd:
        print(cyan("Restarting NetMash session..."))
        args.restart_flag = False
        args.subcommand = None
        return False

    # 4. Local info request (-i / --info) without connecting
    if args.info:
        platform_info = get_platform_info()
        identity = get_or_create_identity(args.name)
        platform_info["username"] = identity.username
        platform_info["version"] = __version__

        client, host_info = await get_or_discover_client(
            args.port, args.discovery_port, args.name, timeout=0.8, interactive_choice=False
        )
        if client:
            status = await client.get_status()
            if status:
                platform_info["peers"] = status.get("peers_count", 1)
                platform_info["groups"] = status.get("groups_count", 1)
            await client.disconnect()

        render_info(platform_info)
        return True

    # 5. Stats / Nodes / Peers / Group Subcommands
    is_nodes_cmd = args.nodes or args.subcommand == "peers"
    is_status_cmd = args.status
    is_stats_cmd = args.stats or getattr(args, "subcommand", None) == "stats"
    is_group_cmd = args.group_flag or args.subcommand == "group" or args.join_group_name
    is_dm_cmd = args.subcommand == "dm"

    if not (is_nodes_cmd or is_status_cmd or is_stats_cmd or is_group_cmd or is_dm_cmd):
        return False

    # Connect to active host
    client, host_info = await get_or_discover_client(
        args.port, args.discovery_port, args.name, timeout=1.5, interactive_choice=False
    )
    if not client:
        print(yellow("No NetMash host found on the local network."))
        print(dim("Start NetMash without flags to launch a new session:\n  netmash\n"))
        return True

    try:
        if is_nodes_cmd:
            peers = await client.list_peers()
            render_peers_table(peers)

        elif is_status_cmd:
            status = await client.get_status()
            if status:
                render_status(status)
            else:
                print(red("Could not retrieve status from host."))

        elif is_stats_cmd:
            st = await client.get_stats()
            if st:
                render_stats(st)
            else:
                print(red("Could not retrieve statistics from host."))

        elif is_dm_cmd:
            target = args.target_user
            msg = args.message
            if not msg:
                msg = input(f"Enter message for {target}: ")
            if msg.strip():
                await client.send_dm(target, msg.strip())
                print(green(f"✓ Sent direct message to {target}."))

        elif is_group_cmd:
            action = getattr(args, "group_action", None)
            if args.join_group_name or action == "join":
                target_group = args.join_group_name or args.group_name
                pin = getattr(args, "pin", None)
                resp = await client.join_group(target_group, pin=pin)
                if resp and resp.get("requires_pin") and pin is None:
                    pin = input(f"Group '{target_group}' requires a PIN. Enter 4-digit PIN: ")
                    resp = await client.join_group(target_group, pin=pin.strip())
                if resp and resp.get("success"):
                    print(green(f"✓ Joined group '{target_group}' successfully."))
                elif resp:
                    print(red(f"✗ {resp.get('message')}"))
                else:
                    print(red(f"✗ Could not join group '{target_group}'."))

            elif action == "create":
                group_name = args.group_name
                pin = getattr(args, "pin", None)
                if pin == "PROMPT":
                    pin1 = input("Enter 4-digit PIN: ")
                    pin2 = input("Confirm PIN: ")
                    if pin1 != pin2:
                        print(red("PINs do not match. Cancelled."))
                        return True
                    pin = pin1.strip()

                resp = await client.create_group(group_name, pin=pin)
                if resp and resp.get("success"):
                    print(green(f"✓ Group '{resp.get('name')}' created successfully (Access: {resp.get('access')})."))
                elif resp:
                    print(yellow(f"{resp.get('message')}"))
                else:
                    print(red("Failed to create group."))

            elif action == "set-pin":
                group_name = args.group_name
                pin = getattr(args, "pin", None)
                if pin is None:
                    pin = input(f"Enter new 4-digit PIN for '{group_name}': ")
                resp = await client.set_group_pin(group_name, pin=pin.strip())
                if resp and resp.get("success"):
                    print(green(f"✓ {resp.get('message')}"))
                elif resp:
                    print(red(f"✗ {resp.get('message')}"))
                else:
                    print(red("Failed to set group PIN."))

            elif action == "remove-pin":
                group_name = args.group_name
                resp = await client.set_group_pin(group_name, pin=None)
                if resp and resp.get("success"):
                    print(green(f"✓ {resp.get('message')}"))
                elif resp:
                    print(red(f"✗ {resp.get('message')}"))
                else:
                    print(red("Failed to remove group PIN."))

            elif action == "leave":
                group_name = args.group_name
                resp = await client.leave_group(group_name)
                if resp and resp.get("success"):
                    print(green(f"✓ {resp.get('message')}"))
                elif resp:
                    print(red(f"✗ {resp.get('message')}"))

            elif action == "members":
                group_name = args.group_name
                resp = await client.get_members(group_name)
                if resp:
                    render_members(resp)
                else:
                    print(red(f"Could not retrieve members for '{group_name}'."))

            elif action == "info":
                group_name = args.group_name
                resp = await client.get_group_info(group_name)
                if resp:
                    print(bold(f"\nGroup Information: {resp.get('name')}\n"))
                    print(f"{'Access':<14}: {yellow('PIN') if resp.get('access') == 'PIN' else green('PUBLIC')}")
                    print(f"{'Members':<14}: {resp.get('members', 0)}")
                    print(f"{'Created At':<14}: {resp.get('created_at', '')}\n")
                else:
                    print(red(f"Group '{group_name}' not found."))

            else:
                groups = await client.list_groups()
                render_groups_table(groups, current_room=client.current_room)

    finally:
        await client.disconnect()

    return True


async def run_netmash_main(args: argparse.Namespace) -> None:
    """
    Main NetMash session loop.
    Discovers an existing host; if none exists, starts local host and connects.
    """
    init_colors(not args.no_color)
    identity = get_or_create_identity(args.name)

    # 1. Handle one-shot commands
    if await handle_oneshot_command(args):
        return

    # 2. Interactive Session / Dedicated Host
    print_banner()

    # If --host-only was passed, just run the host server
    if args.host_only:
        server = NetMashServer(
            port=args.port,
            discovery_port=args.discovery_port,
            identity=identity,
        )
        await server.start()
        print(green("✓ NetMash dedicated host is running."))
        print(dim(f"Host: {identity.hostname} | Port: {args.port}"))
        print(dim("Press Ctrl+C to stop.\n"))
        try:
            while server.running:
                await asyncio.sleep(1.0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            print(yellow("\nShutting down host..."))
            await server.stop()
            print(green("Goodbye."))
        return

    # 3. Default: Automatic Discovery & Connect / Host
    print("Searching for NetMash host on local network...")
    client, host_info = await get_or_discover_client(
        args.port, args.discovery_port, args.name, timeout=1.5, interactive_choice=True
    )

    server: Optional[NetMashServer] = None

    if client and host_info:
        host_name = host_info.get("hostname", "Host")
        net_name = host_info.get("network_name", "NetMash Local")
        print(green(f"\n✓ NetMash host discovered: {host_name} (Network: {net_name})"))
        print(dim("Connecting..."))
        print(green("✓ Connected.\n"))
    else:
        print(yellow("\nNo NetMash host found on the local network."))
        print("Starting a new NetMash host...")

        server = NetMashServer(
            port=args.port,
            discovery_port=args.discovery_port,
            identity=identity,
        )
        try:
            await server.start()
        except Exception as e:
            print(red(f"\n{e}\n"))
            return

        print(green("✓ Host started"))
        print(green("✓ Discovery enabled"))
        print(green("✓ GENERAL room created\n"))

        # Connect local client to the newly started host
        client = NetMashClient(host="127.0.0.1", port=args.port, identity=identity)
        connected = await client.connect(timeout=3.0)
        if not connected:
            print(red("Could not connect to local host."))
            await server.stop()
            return

    # 4. Start interactive terminal chat
    try:
        await run_interactive_chat(client, server=server)
    finally:
        print(yellow("\nShutting down NetMash..."))
        await client.disconnect()
        if server:
            await server.stop()
            print(green("✓ Host stopped"))
            print(green("✓ Discovery stopped"))
            print(green("✓ Database closed"))
        print(green("Goodbye.\n"))


def main() -> None:
    """CLI entry point function."""
    init_colors()
    parser = build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(run_netmash_main(args))
    except KeyboardInterrupt:
        print("\nGoodbye.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

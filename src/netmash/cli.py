"""
CLI Entry Point and command dispatcher for NetMash.
Parses CLI flags, orchestrates automatic host discovery and hosting,
and dispatches interactive chat and subcommands.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional

from netmash import __version__
from netmash.client.client import NetMashClient
from netmash.config import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_HOST_PORT,
    DEFAULT_MULTICAST_GROUP,
)
from netmash.discovery.service import discover_host
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
    render_groups_table,
    render_info,
    render_peers_table,
    render_status,
    run_interactive_chat,
)
from netmash.updater import (
    apply_update,
    check_for_updates,
    check_for_updates_async,
)
from netmash.utils.network import get_platform_info


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

    # Subcommands
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommands")

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
) -> tuple[Optional[NetMashClient], Optional[dict]]:
    """
    Attempts to discover an active NetMash host on the local network.
    If found, connects and returns (client, host_info).
    If not found, returns (None, None).
    """
    identity = get_or_create_identity(custom_name)
    host_info = await discover_host(
        timeout=timeout,
        multicast_group=DEFAULT_MULTICAST_GROUP,
        discovery_port=discovery_port,
    )

    if host_info:
        host_ip = host_info.get("host_ip", "127.0.0.1")
        host_port = int(host_info.get("port", port))
        client = NetMashClient(host=host_ip, port=host_port, identity=identity)
        connected = await client.connect(timeout=3.0)
        if connected:
            return client, host_info
        else:
            await client.disconnect()

    return None, None


async def handle_oneshot_command(args: argparse.Namespace) -> bool:
    """
    Handles one-shot commands like -i, -s, -n, group list, etc.
    Returns True if handled, False if standard interactive mode should proceed.
    """
    # 0. Update commands (--check-update, --update, netmash update [--check])
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
            cur = info.get("current_commit") or "installed"
            latest = info.get("latest_commit") or "latest"
            msg = info.get("commit_message") or ""
            date = info.get("commit_date") or ""
            print(f"\nCurrent version: {cyan(__version__)} (Commit: {cyan(cur)})")
            print(f"Latest on GitHub: {green(latest)} ({msg})")
            if date:
                print(f"Commit date:     {dim(date)}")

            if info.get("update_available"):
                print(yellow("\n💡 A new update is available!"))
                print(dim("Run the following command to update:\n  netmash update\n"))
            else:
                print(green("\n✓ NetMash is already up to date!"))
        return True

    if is_update_apply:
        print("Checking GitHub for updates...")
        info = await check_for_updates_async()
        if not info.get("error") and not info.get("update_available"):
            cur = info.get("current_commit") or "latest"
            print(green(f"✓ NetMash is already up to date! (Commit: {cur})"))
            return True

        print(cyan("Applying latest update from GitHub (https://github.com/Shadab-2604/netmash.git)..."))
        success, msg = await apply_update_async()
        if success:
            print(green(f"\n✓ {msg}"))
            print(green("Restart NetMash to use the updated version."))
        else:
            print(red(f"\n✗ Update failed:\n{msg}"))
        return True

    # 1. Local info request (-i / --info) without connecting
    if args.info:
        platform_info = get_platform_info()
        identity = get_or_create_identity(args.name)
        platform_info["username"] = identity.username
        platform_info["version"] = __version__

        # Try a quick discovery to count peers/groups if host is running
        client, host_info = await get_or_discover_client(
            args.port, args.discovery_port, args.name, timeout=0.8
        )
        if client:
            status = await client.get_status()
            if status:
                platform_info["peers"] = status.get("peers_count", 1)
                platform_info["groups"] = status.get("groups_count", 1)
            await client.disconnect()

        render_info(platform_info)
        return True

    # 2. Status / Nodes / Peers / Group Subcommands
    is_nodes_cmd = args.nodes or args.subcommand == "peers"
    is_status_cmd = args.status
    is_group_cmd = args.group_flag or args.subcommand == "group" or args.join_group_name
    is_dm_cmd = args.subcommand == "dm"

    if not (is_nodes_cmd or is_status_cmd or is_group_cmd or is_dm_cmd):
        return False

    # Connect to active host
    client, host_info = await get_or_discover_client(
        args.port, args.discovery_port, args.name, timeout=1.5
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

        elif is_dm_cmd:
            target = args.target_user
            msg = args.message
            if not msg:
                msg = input(f"Enter message for {target}: ")
            if msg.strip():
                await client.send_dm(target, msg.strip())
                print(green(f"✓ Sent direct message to {target}."))

        elif is_group_cmd:
            # Check specific group action
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
                # Default group list (-g, -g -l, group list)
                groups = await client.list_groups()
                render_groups_table(groups)

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
        args.port, args.discovery_port, args.name, timeout=1.5
    )

    server: Optional[NetMashServer] = None

    if client and host_info:
        host_name = host_info.get("hostname", "Host")
        print(green(f"\n✓ NetMash host discovered: {host_name}"))
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
        await run_interactive_chat(client)
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

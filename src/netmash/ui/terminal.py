"""
Terminal UI components and interactive chat loop for NetMash.
Provides banners, tables, formatted outputs, and non-blocking CLI input handling.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import sys
from typing import Any, Dict, List, Optional

from netmash.client.client import NetMashClient
from netmash.protocol.messages import NetMashMessage
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
from netmash.utils.security import sanitize_terminal_text


def print_banner() -> None:
    """Prints the NetMash welcome banner."""
    print()
    print(cyan("╭──────────────────────────────────────────╮"))
    print(cyan("│") + bold("                 NETMASH                  ") + cyan("│"))
    print(cyan("│") + dim("         Connect. Discover. Chat.         ") + cyan("│"))
    print(cyan("╰──────────────────────────────────────────╯"))
    print()


def print_divider(label: Optional[str] = None) -> None:
    """Prints a clean horizontal terminal divider."""
    width = 50
    if label:
        sanitized_label = f" {label} "
        left_len = (width - len(sanitized_label)) // 2
        right_len = width - len(sanitized_label) - left_len
        print(gray("─" * left_len) + cyan(sanitized_label) + gray("─" * right_len))
    else:
        print(gray("─" * width))


def render_peers_table(peers: List[Dict[str, Any]]) -> None:
    """Renders the formatted list of online peers."""
    print(bold("\nNetMash Peers\n"))
    print(f"{bold('USER'):<18} {bold('HOSTNAME'):<20} {bold('STATUS')}")
    print(gray("─" * 48))
    if not peers:
        print(dim("No peers online."))
        print()
        return

    for p in peers:
        user = sanitize_terminal_text(p.get("username", ""))[:16]
        host = sanitize_terminal_text(p.get("hostname", ""))[:18]
        status = green("ONLINE") if p.get("status") == "ONLINE" else gray("OFFLINE")
        print(f"{cyan(user):<27} {host:<20} {status}")
    print()


def render_groups_table(groups: List[Dict[str, Any]]) -> None:
    """Renders the formatted list of available groups."""
    print(bold("\nAvailable Groups\n"))
    print(f"{bold('NAME'):<20} {bold('MEMBERS'):<12} {bold('ACCESS')}")
    print(gray("─" * 42))
    if not groups:
        print(dim("No groups available."))
        print()
        return

    for g in groups:
        name = sanitize_terminal_text(g.get("name", ""))[:18]
        members = str(g.get("members", 0))
        access = g.get("access", "PUBLIC")
        access_str = yellow("PIN") if access == "PIN" else green("PUBLIC")
        mem_flag = bright_cyan(" *") if g.get("is_member") else ""
        print(f"{name + mem_flag:<20} {members:<12} {access_str}")
    print()


def render_info(info: Dict[str, Any]) -> None:
    """Renders formatted NetMash information."""
    print(bold("\nNetMash Information\n"))
    print(f"{'Version':<16}: {green(str(info.get('version', '1.0.0')))}")
    print(f"{'Hostname':<16}: {info.get('hostname', '')}")
    if "username" in info:
        print(f"{'Username':<16}: {cyan(info.get('username', ''))}")
    print(f"{'Platform':<16}: {info.get('os', 'Local Network')}")
    print(f"{'Local Address':<16}: {info.get('local_ip', '127.0.0.1')}")
    print(f"{'Status':<16}: {green(str(info.get('status', 'ONLINE')))}")
    if "peers" in info:
        print(f"{'Peers':<16}: {info.get('peers', 0)}")
    if "groups" in info:
        print(f"{'Groups':<16}: {info.get('groups', 0)}")
    print()


def render_status(status: Dict[str, Any]) -> None:
    """Renders formatted NetMash status."""
    print(bold("\nNetMash Status\n"))
    print(f"{'Server':<16}: {green(str(status.get('server_status', 'ONLINE')))}")
    print(f"{'Connection':<16}: {green('CONNECTED')}")
    print(f"{'Host':<16}: {status.get('host_name', '')}")
    print(f"{'Peers':<16}: {status.get('peers_count', 0)}")
    print(f"{'Groups':<16}: {status.get('groups_count', 0)}")
    print(f"{'Room':<16}: {cyan(str(status.get('room', 'GENERAL')).upper())}")
    print(f"{'Uptime':<16}: {status.get('uptime', '00:00:00')}")
    print()


def print_help() -> None:
    """Prints interactive chat commands."""
    print(bold("\nInteractive Commands:"))
    print(f"  {cyan('/help')}                 Show this help message")
    print(f"  {cyan('/users')}, {cyan('/peers')}        List connected peers")
    print(f"  {cyan('/groups')}               List available groups")
    print(f"  {cyan('/create <name>')}        Create a new public or PIN group")
    print(f"  {cyan('/join <name>')}          Switch room or join a group")
    print(f"  {cyan('/leave')}                Leave current group and return to GENERAL")
    print(f"  {cyan('/dm <user> [msg]')}      Direct message a peer")
    print(f"  {cyan('/room')}                 Show current active room")
    print(f"  {cyan('/name <new_name>')}      Change your display name")
    print(f"  {cyan('/info')}                 Show local node and network info")
    print(f"  {cyan('/status')}               Show server status")
    print(f"  {cyan('/clear')}                Clear terminal screen")
    print(f"  {cyan('/exit')}, {cyan('/quit')}        Disconnect and exit")
    print()


def clear_screen() -> None:
    """Clears the terminal screen."""
    os.system("cls" if sys.platform == "win32" else "clear")


async def run_interactive_chat(client: NetMashClient) -> None:
    """
    Main interactive terminal chat loop.
    Asynchronously prints incoming messages while accepting user input.
    """
    print_banner()
    peers_count = client.server_info.get("peers_count", 1)
    host_name = client.server_info.get("host_name", "Host")

    print_divider(f"NetMash | {client.current_room.upper()} | Host: {host_name}")
    print(dim(f"You are: {client.identity.username} ({client.identity.hostname})"))
    print(dim("Type a message to chat, or /help for available commands.\n"))

    # Set up client event callbacks for formatted message display
    def on_chat(msg: NetMashMessage) -> None:
        payload = msg.payload
        room = sanitize_terminal_text(payload.get("room", "general")).upper()
        sender = sanitize_terminal_text(payload.get("sender_name", "Unknown"))
        content = sanitize_terminal_text(payload.get("content", ""))

        now_str = datetime.datetime.now().strftime("%H:%M")
        is_self = payload.get("sender_id") == client.identity.node_id

        sender_label = green(f"{sender} (You)") if is_self else cyan(sender)
        room_tag = f"[{room}] " if room.lower() != client.current_room.lower() else ""

        # Erase current prompt line, print message, re-prompt
        sys.stdout.write(f"\r\033[K{dim(f'[{now_str}]')} {room_tag}{sender_label}:\n{content}\n\n")
        sys.stdout.write(f"{cyan('netmash')}> ")
        sys.stdout.flush()

    def on_dm(msg: NetMashMessage) -> None:
        payload = msg.payload
        sender = sanitize_terminal_text(payload.get("sender_name", "Unknown"))
        target = sanitize_terminal_text(payload.get("target", ""))
        content = sanitize_terminal_text(payload.get("content", ""))
        now_str = datetime.datetime.now().strftime("%H:%M")

        is_sender = payload.get("sender_id") == client.identity.node_id
        if is_sender:
            tag = magenta(f"[DM to {target}]")
        else:
            tag = magenta(f"[DM from {sender}]")

        sys.stdout.write(f"\r\033[K{dim(f'[{now_str}]')} {tag}:\n{content}\n\n")
        sys.stdout.write(f"{cyan('netmash')}> ")
        sys.stdout.flush()

    def on_join(msg: NetMashMessage) -> None:
        user = sanitize_terminal_text(msg.payload.get("username", "Someone"))
        sys.stdout.write(f"\r\033[K{gray(f'→ {user} joined NetMash')}\n")
        sys.stdout.write(f"{cyan('netmash')}> ")
        sys.stdout.flush()

    def on_leave(msg: NetMashMessage) -> None:
        user = sanitize_terminal_text(msg.payload.get("username", "Someone"))
        sys.stdout.write(f"\r\033[K{gray(f'← {user} left NetMash')}\n")
        sys.stdout.write(f"{cyan('netmash')}> ")
        sys.stdout.flush()

    def on_name(msg: NetMashMessage) -> None:
        old_name = sanitize_terminal_text(msg.payload.get("old_name", ""))
        new_name = sanitize_terminal_text(msg.payload.get("new_name", ""))
        sys.stdout.write(f"\r\033[K{gray(f'• {old_name} is now known as {new_name}')}\n")
        sys.stdout.write(f"{cyan('netmash')}> ")
        sys.stdout.flush()

    def on_error(msg: NetMashMessage) -> None:
        err_msg = sanitize_terminal_text(msg.payload.get("message", "An error occurred."))
        sys.stdout.write(f"\r\033[K{red('Error:')} {err_msg}\n")
        sys.stdout.write(f"{cyan('netmash')}> ")
        sys.stdout.flush()

    client.on_chat_message = on_chat
    client.on_dm = on_dm
    client.on_peer_join = on_join
    client.on_peer_leave = on_leave
    client.on_name_change = on_name
    client.on_error = on_error

    loop = asyncio.get_running_loop()

    # Input loop
    while client.connected:
        try:
            # Asynchronously wait for user input without blocking the asyncio event loop
            sys.stdout.write(f"{cyan('netmash')}> ")
            sys.stdout.flush()

            user_input = await asyncio.to_thread(sys.stdin.readline)
            if not user_input:
                break  # EOF / stdin closed

            text = user_input.strip()
            if not text:
                continue

            if text.startswith("/"):
                # Handle slash commands
                parts = text.split(" ", 2)
                cmd = parts[0].lower()

                if cmd in ("/exit", "/quit"):
                    print(yellow("\nDisconnecting from NetMash..."))
                    break
                elif cmd == "/help":
                    print_help()
                elif cmd in ("/users", "/peers"):
                    peers = await client.list_peers()
                    render_peers_table(peers)
                elif cmd == "/groups":
                    groups = await client.list_groups()
                    render_groups_table(groups)
                elif cmd == "/create":
                    if len(parts) < 2:
                        print(red("Usage: /create <group_name>"))
                    else:
                        group_name = parts[1].strip()
                        print(f"Creating group: {cyan(group_name)}")
                        print("1. Public")
                        print("2. PIN protected")
                        choice = await asyncio.to_thread(input, "Select (1/2): ")
                        pin = None
                        if choice.strip() == "2":
                            pin1 = await asyncio.to_thread(input, "Enter 4-digit PIN: ")
                            pin2 = await asyncio.to_thread(input, "Confirm PIN: ")
                            if pin1 != pin2:
                                print(red("PINs do not match. Cancelled."))
                                continue
                            pin = pin1.strip()

                        resp = await client.create_group(group_name, pin=pin)
                        if resp and resp.get("success"):
                            print(green(f"✓ Group '{resp.get('name')}' created successfully."))
                            client.current_room = resp.get("name", group_name)
                            print(dim(f"Switched room to: {client.current_room.upper()}"))
                        elif resp:
                            print(yellow(f"{resp.get('message')}"))
                        else:
                            print(red("Failed to create group."))
                elif cmd == "/join":
                    if len(parts) < 2:
                        print(red("Usage: /join <group_name>"))
                    else:
                        target_group = parts[1].strip()
                        resp = await client.join_group(target_group)
                        if resp and resp.get("requires_pin"):
                            pin_input = await asyncio.to_thread(
                                input, f"Group '{target_group}' requires a PIN. Enter 4-digit PIN: "
                            )
                            resp = await client.join_group(target_group, pin=pin_input.strip())

                        if resp and resp.get("success"):
                            print(green(f"✓ Joined '{target_group}'. Current room: {client.current_room.upper()}"))
                        elif resp:
                            print(red(f"✗ {resp.get('message')}"))
                        else:
                            print(red(f"✗ Could not join group '{target_group}'."))
                elif cmd == "/leave":
                    if client.current_room == "general":
                        print(yellow("You are already in GENERAL."))
                    else:
                        resp = await client.leave_group(client.current_room)
                        if resp and resp.get("success"):
                            print(green(f"✓ Left group. Returned to GENERAL."))
                        elif resp:
                            print(red(f"✗ {resp.get('message')}"))
                elif cmd == "/dm":
                    if len(parts) < 2:
                        print(red("Usage: /dm <username> [message]"))
                    else:
                        target_user = parts[1].strip()
                        if len(parts) == 3:
                            dm_content = parts[2].strip()
                            await client.send_dm(target_user, dm_content)
                        else:
                            dm_content = await asyncio.to_thread(
                                input, f"Enter message for {target_user}: "
                            )
                            if dm_content.strip():
                                await client.send_dm(target_user, dm_content.strip())
                elif cmd == "/room":
                    print(f"Current room: {cyan(client.current_room.upper())}")
                elif cmd == "/name":
                    if len(parts) < 2:
                        print(red("Usage: /name <new_name>"))
                    else:
                        new_name = parts[1].strip()
                        await client.change_name(new_name)
                        print(green(f"✓ Name change requested: {new_name}"))
                elif cmd == "/info":
                    info = await client.get_info()
                    if info:
                        render_info(info)
                elif cmd == "/status":
                    status = await client.get_status()
                    if status:
                        render_status(status)
                elif cmd == "/clear":
                    clear_screen()
                    print_banner()
                    print_divider(f"NetMash | {client.current_room.upper()} | Host: {host_name}")
                else:
                    print(yellow("Unknown command. Use /help to see available commands."))
            else:
                # Regular chat message
                await client.send_chat(text)

        except (KeyboardInterrupt, asyncio.CancelledError):
            print(yellow("\nDisconnecting from NetMash..."))
            break
        except Exception as e:
            print(red(f"\nUnexpected input error: {e}"))
            break


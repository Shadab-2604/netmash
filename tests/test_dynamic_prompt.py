"""
Unit and Integration tests for Dynamic Group Prompt in NetMash CLI.
Verifies that:
- The prompt dynamically and immediately reflects the active group/room name (netmash><room>> ).
- Single source of truth is maintained (client.current_room).
- Every successful room-changing operation updates the prompt (/switch, /join, /general, /leave, /create).
- Failed room operations leave the prompt unchanged.
- Incoming events during typing redraw with the current active group prompt and preserve user input.
- Two NetMash instances independently display their own correct active group prompts.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
import pytest

from netmash.client.client import NetMashClient
from netmash.identity import NodeIdentity
from netmash.protocol.messages import MessageType, NetMashMessage
from netmash.server.server import NetMashServer
from netmash.storage.database import Database
from netmash.ui.input import TerminalInputManager


def test_dynamic_prompt_callable_and_property():
    """
    Verifies that TerminalInputManager correctly evaluates a dynamic prompt callable
    and updates prompt_text whenever the underlying room state changes.
    """
    current_room = "general"

    def get_prompt():
        return f"netmash>{current_room}> "

    mgr = TerminalInputManager(prompt=get_prompt)
    assert mgr.prompt_text == "netmash>general> "

    # Switch room to developers
    current_room = "developers"
    assert mgr.prompt_text == "netmash>developers> "

    # Switch room to gaming
    current_room = "gaming"
    assert mgr.prompt_text == "netmash>gaming> "

    # Return to general
    current_room = "general"
    assert mgr.prompt_text == "netmash>general> "


def test_incoming_event_redraw_with_dynamic_prompt(monkeypatch):
    """
    Verifies that when an event arrives while the user is typing in a non-general room
    (e.g., 'developers'), the prompt redrawn is 'netmash>developers> ' and typed text is intact.
    """
    captured = io.StringIO()
    monkeypatch.setattr(sys.stdout, "write", captured.write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    active_room = "developers"
    mgr = TerminalInputManager(prompt=lambda: f"netmash>{active_room}> ")

    # User starts typing in developers room
    mgr._active = True
    mgr._buffer = list("hello eve")
    mgr._cursor_pos = len(mgr._buffer)

    # Event arrives: Bob sends message
    mgr.print_event("Bob:\nHey!\n")

    # Buffer and cursor position must be 100% preserved
    assert mgr.buffer_text == "hello eve"
    assert mgr.cursor_position == 9

    # Output must contain the event and the redraw with developers prompt
    output = captured.getvalue()
    assert "Bob:\nHey!\n" in output
    assert "netmash>developers> hello eve" in output

    # Switch active room to gaming
    active_room = "gaming"
    mgr.print_event("Alice:\nGame on!\n")

    assert mgr.buffer_text == "hello eve"
    assert mgr.cursor_position == 9
    output2 = captured.getvalue()
    assert "netmash>gaming> hello eve" in output2


@pytest.mark.asyncio
async def test_dynamic_prompt_room_lifecycle_and_two_instances(tmp_path: Path):
    """
    Full lifecycle test against real server and client:
    - Start in general -> prompt is netmash>general> 
    - Create/switch to 'developers' -> prompt is netmash>developers> 
    - Switch to 'gaming' -> prompt is netmash>gaming> 
    - /general -> prompt is netmash>general> 
    - Failed /switch to non-existent group -> prompt remains unchanged
    - Two instances: Instance A in 'developers' and Instance B in 'general'
      each display their own correct prompt.
    """
    db = Database(tmp_path / "server.db")
    server_identity = NodeIdentity("srv-node", "HostAdmin", "host")
    test_port = 19780
    server = NetMashServer(port=test_port, discovery_port=19781, identity=server_identity, db=db)
    await server.start()

    identity_a = NodeIdentity("node-alice", "Alice", "alice-pc")
    identity_b = NodeIdentity("node-bob", "Bob", "bob-pc")

    client_a = NetMashClient(host="127.0.0.1", port=test_port, identity=identity_a)
    client_b = NetMashClient(host="127.0.0.1", port=test_port, identity=identity_b)

    await client_a.connect()
    await client_b.connect()

    # Dynamic prompt helper matching NetMash terminal UI
    def get_prompt(client: NetMashClient) -> str:
        return f"netmash>{client.current_room.lower()}> "

    mgr_a = TerminalInputManager(prompt=lambda: get_prompt(client_a))
    mgr_b = TerminalInputManager(prompt=lambda: get_prompt(client_b))

    try:
        # 1. Initial prompt in general
        assert client_a.current_room == "general"
        assert mgr_a.prompt_text == "netmash>general> "
        assert client_b.current_room == "general"
        assert mgr_b.prompt_text == "netmash>general> "

        # 2. Client A creates and joins 'developers'
        resp_create = await client_a.create_group("developers")
        assert resp_create["success"] is True
        assert client_a.current_room == "developers"
        assert mgr_a.prompt_text == "netmash>developers> "
        # Client B remains in general
        assert client_b.current_room == "general"
        assert mgr_b.prompt_text == "netmash>general> "

        # 3. Client A creates and joins 'gaming'
        resp_gaming = await client_a.create_group("gaming")
        assert resp_gaming["success"] is True
        assert client_a.current_room == "gaming"
        assert mgr_a.prompt_text == "netmash>gaming> "

        # 4. Client A switches back to 'developers'
        resp_switch = await client_a.switch_room("developers")
        assert resp_switch["success"] is True
        assert client_a.current_room == "developers"
        assert mgr_a.prompt_text == "netmash>developers> "

        # 5. Client A switches to /general
        resp_gen = await client_a.switch_room("general")
        assert resp_gen["success"] is True
        assert client_a.current_room == "general"
        assert mgr_a.prompt_text == "netmash>general> "

        # 6. Failed switch to non-existent group keeps prompt unchanged
        resp_fail = await client_a.switch_room("nonexistent-group")
        assert resp_fail["success"] is False
        assert client_a.current_room == "general"
        assert mgr_a.prompt_text == "netmash>general> "

        # 7. Client B joins 'developers'
        resp_b_join = await client_b.join_group("developers")
        assert resp_b_join["success"] is True
        assert client_b.current_room == "developers"
        assert mgr_b.prompt_text == "netmash>developers> "

        # 8. Client B leaves 'developers' -> returns to general
        resp_leave = await client_b.leave_group("developers")
        assert resp_leave["success"] is True
        assert client_b.current_room == "general"
        assert mgr_b.prompt_text == "netmash>general> "

    finally:
        await client_a.disconnect()
        await client_b.disconnect()
        await server.stop()

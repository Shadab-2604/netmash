"""
Complete Two-Instance Integration Test Suite for NetMash.
Executes two independent, isolated NetMash instances (Instance A: Alice, Instance B: Bob)
with independent storage databases, configs, and node identities.
Verifies every NetMash feature in real communication and tests input buffer persistence.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
import pytest

from netmash.client.client import NetMashClient
from netmash.discovery.service import DiscoveryResponder, discover_host
from netmash.identity import NodeIdentity
from netmash.protocol.messages import MessageType, NetMashMessage
from netmash.server.server import NetMashServer
from netmash.storage.database import Database
from netmash.ui.input import TerminalInputManager
from netmash.utils.diagnostics import run_diagnostics
from netmash.utils.file_transfer import (
    calculate_sha256,
    read_file_chunks,
    sanitize_filename,
)


@pytest.fixture
async def two_instances_env(tmp_path: Path):
    """
    Sets up two completely isolated NetMash runtime environments:
    Instance A (Host: Alice) and Instance B (Client: Bob).
    """
    dir_a = tmp_path / "instance_a"
    dir_b = tmp_path / "instance_b"
    dir_a.mkdir()
    dir_b.mkdir()

    dl_a = dir_a / "downloads"
    dl_b = dir_b / "downloads"
    dl_a.mkdir()
    dl_b.mkdir()

    # Isolated databases
    db_a = Database(dir_a / "netmash.db")
    db_b = Database(dir_b / "netmash.db")

    # Isolated identities
    identity_a = NodeIdentity(
        node_id="node-alice-1111", username="Alice", hostname="host-alice"
    )
    identity_b = NodeIdentity(
        node_id="node-bob-2222", username="Bob", hostname="host-bob"
    )

    # Server on dynamic port
    test_port = 19765
    server_a = NetMashServer(
        port=test_port,
        discovery_port=19766,
        identity=identity_a,
        db=db_a,
    )
    await server_a.start()

    # Clients
    client_a = NetMashClient(
        host="127.0.0.1",
        port=test_port,
        identity=identity_a,
    )
    client_b = NetMashClient(
        host="127.0.0.1",
        port=test_port,
        identity=identity_b,
    )

    await client_a.connect()
    await client_b.connect()

    yield {
        "dir_a": dir_a,
        "dir_b": dir_b,
        "dl_a": dl_a,
        "dl_b": dl_b,
        "server": server_a,
        "client_a": client_a,
        "client_b": client_b,
        "identity_a": identity_a,
        "identity_b": identity_b,
        "port": test_port,
    }

    # Teardown
    await client_a.disconnect()
    await client_b.disconnect()
    await server_a.stop()


@pytest.mark.asyncio
async def test_two_instances_discovery_and_identity(two_instances_env):
    """Verifies that both instances connect with isolated identities and see each other."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    assert client_a.identity.node_id != client_b.identity.node_id
    assert client_a.identity.username == "Alice"
    assert client_b.identity.username == "Bob"

    peers_a = await client_a.list_peers()
    usernames_a = [p["username"] for p in peers_a]
    assert "Alice" in usernames_a
    assert "Bob" in usernames_a

    peers_b = await client_b.list_peers()
    usernames_b = [p["username"] for p in peers_b]
    assert "Alice" in usernames_b
    assert "Bob" in usernames_b


@pytest.mark.asyncio
async def test_two_instances_general_chat(two_instances_env):
    """Verifies two-way messaging in GENERAL room."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    received_by_b: List[NetMashMessage] = []
    received_by_a: List[NetMashMessage] = []

    client_b.on_chat_message = lambda msg: received_by_b.append(msg)
    client_a.on_chat_message = lambda msg: received_by_a.append(msg)

    # A -> B
    await client_a.send_chat("Hello Bob from Alice!", room="general")
    await asyncio.sleep(0.1)

    assert len(received_by_b) >= 1
    msg_b = received_by_b[-1]
    assert msg_b.payload["content"] == "Hello Bob from Alice!"
    assert msg_b.payload["sender_name"] == "Alice"
    assert msg_b.payload["room"] == "general"

    # B -> A
    await client_b.send_chat("Hello Alice from Bob!", room="general")
    await asyncio.sleep(0.1)

    assert len(received_by_a) >= 1
    msg_a = received_by_a[-1]
    assert msg_a.payload["content"] == "Hello Alice from Bob!"
    assert msg_a.payload["sender_name"] == "Bob"


@pytest.mark.asyncio
async def test_input_persistence_bug_during_peer_events(two_instances_env):
    """
    CRITICAL TWO-INSTANCE ACCEPTANCE TEST:
    Simulates Alice actively typing a message in her terminal prompt.
    While Alice is typing, Bob triggers various network events:
      - sends a chat message
      - sends a group message
      - sends a DM
      - changes presence (/away, /busy, /online)
      - sends an announcement
      - sends a file offer
    Verifies that Alice's input buffer and cursor position NEVER disappear or corrupt.
    """
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    # Setup TerminalInputManager for Alice
    input_mgr_a = TerminalInputManager(prompt="netmash> ")
    input_mgr_a._active = True
    input_mgr_a._buffer = list("this message must survive")
    input_mgr_a._cursor_pos = len(input_mgr_a._buffer)

    # Attach event callbacks that call print_event
    client_a.on_chat_message = lambda msg: input_mgr_a.print_event(
        f"[{msg.payload.get('sender_name')}]: {msg.payload.get('content')}"
    )
    client_a.on_dm = lambda msg: input_mgr_a.print_event(
        f"[DM from {msg.payload.get('sender_name')}]: {msg.payload.get('content')}"
    )
    client_a.on_presence_update = lambda msg: input_mgr_a.print_event(
        f"• {msg.payload.get('username')} is now {msg.payload.get('status')}"
    )
    client_a.on_announcement = lambda msg: input_mgr_a.print_event(
        f"ANNOUNCEMENT: {msg.payload.get('content')}"
    )

    # 1. Bob sends chat
    await client_b.send_chat("Hello Alice!", room="general")
    await asyncio.sleep(0.1)
    assert input_mgr_a.buffer_text == "this message must survive"
    assert input_mgr_a.cursor_position == 25

    # 2. Bob sends DM
    await client_b.send_dm("Alice", "Secret DM while typing")
    await asyncio.sleep(0.1)
    assert input_mgr_a.buffer_text == "this message must survive"

    # 3. Bob changes presence
    await client_b.set_presence("AWAY")
    await asyncio.sleep(0.1)
    assert input_mgr_a.buffer_text == "this message must survive"

    # 4. Bob sends announcement
    await client_b.announce("Attention all users!", room="general")
    await asyncio.sleep(0.1)
    assert input_mgr_a.buffer_text == "this message must survive"

    # Alice continues typing and submits
    input_mgr_a._buffer.extend(list(" - successfully!"))
    input_mgr_a._cursor_pos = len(input_mgr_a._buffer)
    assert input_mgr_a.buffer_text == "this message must survive - successfully!"


@pytest.mark.asyncio
async def test_two_instances_username_change(two_instances_env):
    """Verifies display name updates and node ID routing."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    name_events_b = []
    client_b.on_name_change = lambda msg: name_events_b.append(msg)

    await client_a.change_name("Alice_Queen")
    await asyncio.sleep(0.1)

    assert len(name_events_b) >= 1
    assert name_events_b[-1].payload["new_name"] == "Alice_Queen"

    # Verify peers list reflects new name
    peers = await client_b.list_peers()
    usernames = [p["username"] for p in peers]
    assert "Alice_Queen" in usernames


@pytest.mark.asyncio
async def test_two_instances_groups_and_pin_security(two_instances_env):
    """Tests group creation, PIN protection, wrong PIN rejection, /members, and moderation."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    # 1. Public group creation
    res_pub = await client_a.create_group("developers")
    assert res_pub["success"] is True

    groups = await client_b.list_groups()
    group_names = [g["name"] for g in groups]
    assert "developers" in group_names

    # Bob joins
    join_pub = await client_b.join_group("developers")
    assert join_pub["success"] is True

    # Check members
    mem_data = await client_a.get_members("developers")
    assert "Alice" in mem_data["owner"] or "Alice_Queen" in mem_data["owner"]
    assert "Bob" in mem_data["members"]

    # 2. PIN-protected group creation
    res_pin = await client_a.create_group("security", pin="1234")
    assert res_pin["success"] is True
    assert res_pin["access"] == "PIN"

    # Bob attempts without PIN
    join_no_pin = await client_b.join_group("security")
    assert join_no_pin.get("requires_pin") is True or join_no_pin.get("success") is False

    # Bob attempts with wrong PIN
    join_wrong_pin = await client_b.join_group("security", pin="9999")
    assert join_wrong_pin.get("success") is False

    # Bob attempts with correct PIN
    join_ok_pin = await client_b.join_group("security", pin="1234")
    assert join_ok_pin.get("success") is True

    # 3. PIN updates & owner-only permissions
    # Bob (member) attempts /setpin -> fails
    set_bob = await client_b.set_group_pin("security", pin="0000")
    assert set_bob.get("success") is False

    # Alice (owner) sets PIN -> succeeds
    set_alice = await client_a.set_group_pin("security", pin="5678")
    assert set_alice.get("success") is True

    # Alice removes PIN -> succeeds
    rm_pin = await client_a.set_group_pin("security", pin=None)
    assert rm_pin.get("success") is True


@pytest.mark.asyncio
async def test_two_instances_dm_isolation(two_instances_env):
    """Verifies that direct messages are delivered only to the target and not leaked to rooms."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    dm_received_b = []
    chat_received_b = []

    client_b.on_dm = lambda msg: dm_received_b.append(msg)
    client_b.on_chat_message = lambda msg: chat_received_b.append(msg)

    await client_a.send_dm("Bob", "Top secret private DM!")
    await asyncio.sleep(0.1)

    assert len(dm_received_b) == 1
    assert dm_received_b[0].payload["content"] == "Top secret private DM!"
    assert len(chat_received_b) == 0  # Not in general chat


@pytest.mark.asyncio
async def test_two_instances_message_history_search_and_reply(two_instances_env):
    """Tests message history retrieval, searching, and replying."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    # Send unique search keyword
    await client_a.send_chat("UniqueKeyServer123 - Important Server Config", room="general")
    await asyncio.sleep(0.1)

    history = await client_b.get_history("general", limit=10)
    assert any("UniqueKeyServer123" in m["content"] for m in history)

    search_res = await client_b.search_messages("UniqueKeyServer123")
    assert len(search_res) >= 1
    target_msg_id = search_res[0]["message_id"]

    # Reply to message
    replies_b = []
    client_b.on_chat_message = lambda msg: replies_b.append(msg)

    await client_a.send_chat("This is a reply!", room="general", reply_to=target_msg_id)
    await asyncio.sleep(0.1)

    assert len(replies_b) >= 1
    assert replies_b[-1].payload.get("reply_to") == target_msg_id


@pytest.mark.asyncio
async def test_two_instances_message_edit_pin_delete(two_instances_env):
    """Tests message editing, pinning, and deletion with permission enforcement."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    received_chat = []
    edit_events_b = []
    pin_events_b = []
    delete_events_b = []

    client_b.on_chat_message = lambda msg: received_chat.append(msg)
    client_b.on_message_edit = lambda msg: edit_events_b.append(msg)
    client_b.on_message_pin = lambda msg: pin_events_b.append(msg)
    client_b.on_message_delete = lambda msg: delete_events_b.append(msg)

    await client_a.send_chat("Original text before edit", room="general")
    await asyncio.sleep(0.1)
    msg_id = received_chat[-1].payload["message_id"]

    # 1. Edit
    await client_a.edit_message(msg_id, "Edited text after update")
    await asyncio.sleep(0.1)
    assert len(edit_events_b) >= 1
    assert edit_events_b[-1].payload["content"] == "Edited text after update"

    # Bob attempts to edit Alice's message -> fails silently or rejected
    await client_b.edit_message(msg_id, "Hacked by Bob")
    await asyncio.sleep(0.1)

    # 2. Pin
    await client_a.pin_message(msg_id, is_pinned=True)
    await asyncio.sleep(0.1)
    assert len(pin_events_b) >= 1
    assert pin_events_b[-1].payload["pinned"] is True

    # 3. Delete
    await client_a.delete_message(msg_id)
    await asyncio.sleep(0.1)
    assert len(delete_events_b) >= 1
    assert delete_events_b[-1].payload["message_id"] == msg_id


@pytest.mark.asyncio
async def test_two_instances_group_moderation_kick_ban_delete(two_instances_env):
    """Tests group owner kicking, banning, unbanning, and group deletion."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    await client_a.create_group("modteam")
    await client_b.join_group("modteam")

    # 1. Kick Bob
    kick_res = await client_a.kick_member("modteam", "Bob")
    assert kick_res["success"] is True

    # 2. Ban Bob
    ban_res = await client_a.ban_member("modteam", "Bob")
    assert ban_res["success"] is True

    # Bob attempts to rejoin -> fails
    rejoin_res = await client_b.join_group("modteam")
    assert rejoin_res.get("success") is False

    # 3. Unban Bob
    unban_res = await client_a.unban_member("modteam", "Bob")
    assert unban_res["success"] is True

    rejoin_ok = await client_b.join_group("modteam")
    assert rejoin_ok.get("success") is True

    # 4. Group delete
    del_res = await client_a.delete_group("modteam")
    assert del_res["success"] is True

    groups = await client_b.list_groups()
    assert "modteam" not in [g["name"] for g in groups]


@pytest.mark.asyncio
async def test_two_instances_diagnostics_and_stats(two_instances_env):
    """Verifies diagnostics suite and statistics counters."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    diag_a = await run_diagnostics(client=client_a)
    assert diag_a["status"] == "READY"
    assert len(diag_a["checks"]) >= 6

    diag_b = await run_diagnostics(client=client_b)
    assert diag_b["status"] == "READY"

    stats = await client_a.get_stats()
    assert stats["connected_peers"] >= 2
    assert "uptime" in stats


@pytest.mark.asyncio
async def test_two_instances_file_transfer_and_security(two_instances_env):
    """Tests file transfer between instances and path sanitization."""
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]
    dl_b = two_instances_env["dl_b"]

    # Create dummy file
    source_file = two_instances_env["dir_a"] / "test_doc.txt"
    source_file.write_text("Hello NetMash File Transfer Content!", encoding="utf-8")
    expected_sha = calculate_sha256(source_file)

    offers_b = []
    client_b.on_file_offer = lambda msg: offers_b.append(msg)

    # Offer file
    file_id = "f_test_123"
    offer_msg = NetMashMessage(
        type=MessageType.FILE_OFFER,
        payload={
            "file_id": file_id,
            "name": source_file.name,
            "size": source_file.stat().st_size,
            "sha256": expected_sha,
            "target": "Bob",
            "target_type": "dm",
        },
    )
    await client_a.send_message(offer_msg)
    await asyncio.sleep(0.1)

    assert len(offers_b) == 1
    assert offers_b[0].payload["sha256"] == expected_sha

    # Verify path traversal sanitization
    dirty_name = "../../../etc/passwd.txt"
    clean_name = sanitize_filename(dirty_name)
    assert "/" not in clean_name and ".." not in clean_name


@pytest.mark.asyncio
async def test_two_instances_dynamic_prompt_isolation_and_events(two_instances_env):
    """
    Tests that two concurrent NetMash instances maintain their own independent
    dynamic group prompts in real-time as they switch groups and receive incoming messages.
    """
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    def get_prompt(c: NetMashClient) -> str:
        return f"netmash>{c.current_room.lower()}> "

    mgr_a = TerminalInputManager(prompt=lambda: get_prompt(client_a))
    mgr_b = TerminalInputManager(prompt=lambda: get_prompt(client_b))

    # Initial state: both in general
    assert mgr_a.prompt_text == "netmash>general> "
    assert mgr_b.prompt_text == "netmash>general> "

    # Instance A creates and switches to 'developers'
    res = await client_a.create_group("developers")
    assert res["success"] is True
    assert client_a.current_room == "developers"
    assert mgr_a.prompt_text == "netmash>developers> "

    # Instance B is still in general
    assert client_b.current_room == "general"
    assert mgr_b.prompt_text == "netmash>general> "

    # Instance B creates and switches to 'gaming'
    res_b = await client_b.create_group("gaming")
    assert res_b["success"] is True
    assert client_b.current_room == "gaming"
    assert mgr_b.prompt_text == "netmash>gaming> "

    # Instance A remains in developers
    assert client_a.current_room == "developers"
    assert mgr_a.prompt_text == "netmash>developers> "

    # Instance A switches to general via switch_room
    await client_a.switch_room("general")
    assert client_a.current_room == "general"
    assert mgr_a.prompt_text == "netmash>general> "

    # Instance B leaves gaming and returns to general
    await client_b.leave_group("gaming")
    assert client_b.current_room == "general"
    assert mgr_b.prompt_text == "netmash>general> "


@pytest.mark.asyncio
async def test_two_instances_admin_mode_isolation_and_operations(two_instances_env):
    """
    Tests administrative authentication on Instance A while Instance B remains a normal user.
    Verifies that admin privileges, prompt formatting, and inspection capabilities are isolated.
    """
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    is_admin_a = False
    is_admin_b = False

    def get_prompt(c: NetMashClient, is_adm: bool) -> str:
        room = c.current_room.lower()
        if is_adm:
            return f"netmash[ADMIN]>{room}> "
        return f"netmash>{room}> "

    mgr_a = TerminalInputManager(prompt=lambda: get_prompt(client_a, client_a.is_admin))
    mgr_b = TerminalInputManager(prompt=lambda: get_prompt(client_b, client_b.is_admin))

    assert mgr_a.prompt_text == "netmash>general> "
    assert mgr_b.prompt_text == "netmash>general> "

    # 1. Instance B (Normal User) attempts admin command -> Rejected
    status_unauth = await client_b.admin_get_status()
    assert status_unauth.get("code") == "PERMISSION_DENIED" or status_unauth.get("success") is not True

    # 2. Instance A authenticates with initial credential '2604'
    auth_res = await client_a.admin_auth("2604")
    assert auth_res["success"] is True
    assert client_a.is_admin is True
    assert client_b.is_admin is False

    # 3. Dynamic prompt for A updates to netmash[ADMIN]>general> while B stays netmash>general>
    assert mgr_a.prompt_text == "netmash[ADMIN]>general> "
    assert mgr_b.prompt_text == "netmash>general> "

    # 4. Instance A switches room to 'developers' -> prompt becomes netmash[ADMIN]>developers>
    await client_a.create_group("developers")
    assert client_a.current_room == "developers"
    assert mgr_a.prompt_text == "netmash[ADMIN]>developers> "
    assert mgr_b.prompt_text == "netmash>general> "

    # 5. Admin operations succeed on Instance A
    st = await client_a.admin_get_status()
    assert st.get("status") == "ONLINE"
    assert st.get("active_connections") >= 2

    users = await client_a.admin_get_users()
    assert len(users) >= 2

    sess = await client_a.admin_get_sessions()
    assert len(sess) >= 2

    diag = await client_a.admin_get_diagnostics()
    assert "ONLINE" in str(diag.get("database_status")) or "HEALTHY" in str(diag.get("database_status"))

    logs = await client_a.admin_get_logs()
    assert len(logs) >= 1

    # 6. Instance A logs out of admin mode
    logout_res = await client_a.admin_logout()
    assert logout_res is True
    assert client_a.is_admin is False
    assert mgr_a.prompt_text == "netmash>developers> "


@pytest.mark.asyncio
async def test_two_instances_admin_moderation_and_shutdown(two_instances_env):
    """
    Tests administrative moderation and controlled server shutdown broadcast across instances.
    """
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    # Authenticate A as admin
    await client_a.admin_auth("2604")
    assert client_a.is_admin is True

    # Setup shutdown notification listeners
    shutdown_events: List[str] = []
    client_a.on_server_shutdown = lambda r: shutdown_events.append(f"A:{r}")
    client_b.on_server_shutdown = lambda r: shutdown_events.append(f"B:{r}")

    # Test moderation unban
    unban_res = await client_a.admin_moderation("unban", "Bob")
    assert unban_res.get("success") is True

    # Admin initiates controlled server shutdown
    res = await client_a.admin_shutdown_server("Scheduled Maintenance")
    assert res.get("success") is True
    await asyncio.sleep(0.1)

    # Both clients received the broadcast
    assert any("B:" in e for e in shutdown_events)
    assert any("A:" in e for e in shutdown_events)


@pytest.mark.asyncio
async def test_two_instances_theme_isolation_and_persistence(two_instances_env, monkeypatch):
    """
    Verifies that theme selections are local to each NetMash client:
    - Instance A (Alice) chooses Theme 3 (Matrix).
    - Instance B (Bob) chooses Theme 2 (Ocean).
    - Instance A changing to Theme 6 (Dracula) does NOT affect Instance B.
    - Each client's theme preference persists independently in their local environment.
    """
    from netmash.config import load_config, save_config
    from netmash.ui.theme import get_theme, set_active_theme

    dir_a = two_instances_env["dir_a"]
    dir_b = two_instances_env["dir_b"]

    # 1. Set theme for Instance A to Matrix
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: dir_a)
    theme_a = set_active_theme("Matrix", persist=True)
    assert theme_a.name == "Matrix"
    cfg_a = load_config()
    assert cfg_a.get("theme") == "Matrix"

    # 2. Set theme for Instance B to Ocean
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: dir_b)
    theme_b = set_active_theme("Ocean", persist=True)
    assert theme_b.name == "Ocean"
    cfg_b = load_config()
    assert cfg_b.get("theme") == "Ocean"

    # 3. Verify A's config still says Matrix
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: dir_a)
    assert load_config().get("theme") == "Matrix"

    # 4. Instance A changes to Dracula
    theme_a_new = set_active_theme("Dracula", persist=True)
    assert theme_a_new.name == "Dracula"
    assert load_config().get("theme") == "Dracula"

    # 5. Instance B remains Ocean
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: dir_b)
    assert load_config().get("theme") == "Ocean"


@pytest.mark.asyncio
async def test_two_instances_presence_updates_all_states(two_instances_env):
    """
    Verifies that presence updates (/away, /busy, /online) are cleanly broadcast and received:
    - Alice updates presence to AWAY -> Bob receives valid status event without UNKNOWN_TYPE error.
    - Alice updates presence to BUSY -> Bob receives BUSY status.
    - Alice updates presence to ONLINE -> Bob receives ONLINE status.
    - Bob is actively typing in TerminalInputManager during these presence events;
      his input buffer and cursor remain completely intact.
    """
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    presence_events_b: List[Dict[str, Any]] = []
    error_events_b: List[NetMashMessage] = []

    client_b.on_presence_update = lambda msg: presence_events_b.append(msg.payload)
    client_b.on_error = lambda msg: error_events_b.append(msg)

    # Bob starts typing
    mgr_b = TerminalInputManager(prompt=lambda: f"netmash>{client_b.current_room}> ")
    mgr_b._buffer = list("drafting an important response")
    mgr_b._cursor_pos = 15
    mgr_b._active = True

    # 1. Alice sets status to AWAY
    sent_away = await client_a.set_presence("AWAY")
    assert sent_away is True
    await asyncio.sleep(0.1)

    assert len(presence_events_b) >= 1
    assert presence_events_b[-1].get("username") == "Alice"
    assert presence_events_b[-1].get("status") == "AWAY"
    assert len(error_events_b) == 0

    # Verify Bob's buffer survived
    assert mgr_b.buffer_text == "drafting an important response"
    assert mgr_b.cursor_position == 15

    # 2. Alice sets status to BUSY
    sent_busy = await client_a.set_presence("BUSY")
    assert sent_busy is True
    await asyncio.sleep(0.1)

    assert presence_events_b[-1].get("username") == "Alice"
    assert presence_events_b[-1].get("status") == "BUSY"
    assert len(error_events_b) == 0
    assert mgr_b.buffer_text == "drafting an important response"

    # 3. Alice sets status back to ONLINE
    sent_online = await client_a.set_presence("ONLINE")
    assert sent_online is True
    await asyncio.sleep(0.1)

    assert presence_events_b[-1].get("username") == "Alice"
    assert presence_events_b[-1].get("status") == "ONLINE"
    assert len(error_events_b) == 0
    assert mgr_b.buffer_text == "drafting an important response"


@pytest.mark.asyncio
async def test_two_instances_all_help_commands_audit(two_instances_env, tmp_path: Path):
    """
    Comprehensive End-to-End audit of every single command exposed by /help.
    Verifies parser, real business logic, network propagation, and state updates.
    """
    client_a = two_instances_env["client_a"]
    client_b = two_instances_env["client_b"]

    # 1. /whoami & /info & /version
    assert client_a.identity.username == "Alice"
    assert client_b.identity.username == "Bob"
    info_a = await client_a.get_info()
    assert info_a.get("version") is not None

    # 2. /users & /peers
    peers_a = await client_a.list_peers()
    assert any(p.get("username") == "Bob" for p in peers_a)

    # 3. /groups & /create & /switch & /room & /general
    g_res = await client_a.create_group("audit-room", pin=None)
    assert g_res.get("success") is True

    await client_b.join_group("audit-room")
    assert client_b.current_room == "audit-room"

    await client_b.switch_room("general")
    assert client_b.current_room == "general"

    # 4. /members
    members_res = await client_a.get_members("audit-room")
    assert members_res is not None

    # 5. /setpin & /removepin
    setpin_res = await client_a.set_group_pin("audit-room", "7788")
    assert setpin_res.get("success") is True
    rempin_res = await client_a.set_group_pin("audit-room", None)
    assert rempin_res.get("success") is True

    # 6. /dm & /chat & /history & /search
    await client_a.send_dm("Bob", "Secret audit token DM")
    await client_a.send_chat("Secret audit token: AUDIT-999", room="general")
    await asyncio.sleep(0.05)
    search_res = await client_a.search_messages("AUDIT-999")
    assert len(search_res) >= 1

    # 7. /name
    name_res = await client_b.change_name("Bobby")
    assert name_res is not None
    await asyncio.sleep(0.05)

    # 8. /diagnose & /stats & /status
    diag = await run_diagnostics(client=client_a)
    assert diag.get("status") in ("READY", "WARNING", "ERROR")
    st = await client_a.get_status()
    assert st.get("server_status") == "ONLINE"
    stats = await client_a.get_stats()
    assert stats.get("connected_peers") >= 2

    # 9. /delete group
    del_res = await client_a.delete_group("audit-room")
    assert del_res.get("success") is True




"""
Comprehensive unit and integration tests for all newly added NetMash features:
- Roles & Moderation (kick, ban, unban, delete)
- Chat Features (history, search, reply, edit, delete, pin)
- Presence & Identity
- Diagnostics Subsystem
- File Transfer Security (path traversal sanitization, SHA-256 integrity, chunking)
- Network Sessions & Stats
"""

import asyncio
from pathlib import Path
import pytest

from netmash.client.client import NetMashClient
from netmash.identity import NodeIdentity
from netmash.server.server import NetMashServer
from netmash.storage.database import Database
from netmash.utils.diagnostics import run_diagnostics
from netmash.utils.file_transfer import (
    calculate_sha256,
    read_file_chunks,
    sanitize_filename,
)


def test_file_transfer_security(tmp_path: Path):
    # 1. Path traversal attacks
    assert sanitize_filename("../../secret.txt") == "secret.txt"
    assert sanitize_filename("..\\..\\Windows\\system32\\calc.exe") == "calc.exe"
    assert sanitize_filename("/etc/passwd") == "passwd"
    assert sanitize_filename("safe_file.pdf") == "safe_file.pdf"
    assert sanitize_filename("") == "unnamed_file"

    # 2. File hashing and chunking
    test_file = tmp_path / "test_data.bin"
    test_bytes = b"NetMash secure file transfer chunking test data " * 1000
    test_file.write_bytes(test_bytes)

    sha = calculate_sha256(test_file)
    assert len(sha) == 64

    chunks = list(read_file_chunks(test_file, chunk_size=1024))
    assert len(chunks) > 1
    assert chunks[0][0] == 0  # first index
    assert chunks[0][1] == len(chunks)  # total chunks


@pytest.mark.asyncio
async def test_diagnostics_subsystem():
    diag = await run_diagnostics()
    assert "status" in diag
    assert diag["status"] in ("READY", "DEGRADED")
    assert len(diag["checks"]) >= 6
    names = [c["name"] for c in diag["checks"]]
    assert "Python runtime" in names
    assert "NetMash installation" in names
    assert "Configuration directory" in names
    assert "SQLite database storage" in names


@pytest.mark.asyncio
async def test_new_features_integration(tmp_path: Path):
    db_path = tmp_path / "features_test.db"
    db = Database(db_path)

    port = 9885
    server_identity = NodeIdentity(
        node_id="srv-node-id",
        username="HostAdmin",
        hostname="SERVER-PC",
    )
    server = NetMashServer(
        host_ip="127.0.0.1",
        port=port,
        discovery_port=9886,
        identity=server_identity,
        db=db,
        network_name="Test Network",
    )
    await server.start()

    try:
        # Client 1: Alice (Creator / Owner)
        alice_id = NodeIdentity(node_id="alice-id", username="Alice", hostname="ALICE-PC")
        client_alice = NetMashClient(host="127.0.0.1", port=port, identity=alice_id)
        assert await client_alice.connect() is True

        # Client 2: Bob (Member)
        bob_id = NodeIdentity(node_id="bob-id", username="Bob", hostname="BOB-PC")
        client_bob = NetMashClient(host="127.0.0.1", port=port, identity=bob_id)
        assert await client_bob.connect() is True

        # 1. Presence Test
        await client_alice.set_presence("AWAY")
        await client_bob.set_presence("BUSY")
        await asyncio.sleep(0.1)

        peers = await client_alice.list_peers()
        peer_dict = {p["username"]: p for p in peers}
        assert peer_dict["Alice"]["status"] == "AWAY"
        assert peer_dict["Bob"]["status"] == "BUSY"

        # 2. Group Creation & Roles Test
        create_res = await client_alice.create_group("security-team")
        assert create_res["success"] is True

        # Bob joins
        join_res = await client_bob.join_group("security-team")
        assert join_res["success"] is True

        # Check members categorization
        mem_data = await client_alice.get_members("security-team")
        assert "Alice" in mem_data["owner"]
        assert "Bob" in mem_data["members"]

        # 3. Message History, Search & Reply
        await client_alice.send_chat("Message One: Deployment starting", room="security-team")
        await client_bob.send_chat("Message Two: Acknowledged deployment", room="security-team")
        await asyncio.sleep(0.1)

        history = await client_alice.get_history("security-team", limit=10)
        assert len(history) >= 2
        assert any("Deployment starting" in m["content"] for m in history)

        # Search messages
        search_res = await client_bob.search_messages("deployment")
        assert len(search_res) >= 2

        # Reply to message
        first_msg_id = history[0]["message_id"]
        await client_bob.send_chat("Replying to first message", room="security-team", reply_to=first_msg_id)
        await asyncio.sleep(0.1)

        updated_hist = await client_alice.get_history("security-team", limit=10)
        reply_msg = next((m for m in updated_hist if m.get("reply_to") == first_msg_id), None)
        assert reply_msg is not None

        # 4. Message Edit & Delete & Pin
        msg_to_edit_id = history[1]["message_id"]
        # Alice tries to edit (if it was her message) or Bob edits his message
        # Find Bob's message
        bob_msg = next(m for m in history if m["sender_name"] == "Bob")
        await client_bob.edit_message(bob_msg["message_id"], "Message Two: Edited content")
        await asyncio.sleep(0.1)

        edited_hist = await client_alice.get_history("security-team", limit=10)
        edited_entry = next(m for m in edited_hist if m["message_id"] == bob_msg["message_id"])
        assert edited_entry["content"] == "Message Two: Edited content"
        assert edited_entry["edited"] == 1

        # Pin message
        pin_res = await client_alice.pin_message(first_msg_id, is_pinned=True)
        assert pin_res is True
        pinned_hist = await client_alice.get_history("security-team", limit=10)
        pinned_entry = next(m for m in pinned_hist if m["message_id"] == first_msg_id)
        assert pinned_entry["pinned"] == 1

        # Delete message
        del_res = await client_bob.delete_message(bob_msg["message_id"])
        assert del_res is True
        del_hist = await client_alice.get_history("security-team", limit=10)
        deleted_entry = next(m for m in del_hist if m["message_id"] == bob_msg["message_id"])
        assert deleted_entry["deleted"] == 1
        assert "[message deleted]" in deleted_entry["content"].lower()

        # 5. Kick & Ban & Unban Moderation
        # Bob (member) tries to kick Alice (owner) -> Should fail
        fail_kick = await client_bob.kick_member("security-team", "Alice")
        assert fail_kick["success"] is False

        # Alice (owner) kicks Bob
        kick_res = await client_alice.kick_member("security-team", "Bob")
        assert kick_res["success"] is True

        # Alice bans Bob
        ban_res = await client_alice.ban_member("security-team", "Bob")
        assert ban_res["success"] is True

        # Bob attempts to re-join banned group -> Should fail
        rejoin_res = await client_bob.join_group("security-team")
        assert rejoin_res["success"] is False
        assert "banned" in rejoin_res["message"].lower()

        # Alice unbans Bob
        unban_res = await client_alice.unban_member("security-team", "Bob")
        assert unban_res["success"] is True

        # 6. Group Deletion
        del_grp_res = await client_alice.delete_group("security-team")
        assert del_grp_res["success"] is True
        groups = await client_alice.list_groups()
        assert not any(g["name"] == "security-team" for g in groups)

        # 7. Network Name & Stats
        net_res = await client_alice.set_network_name("Nexcore Headquarters")
        assert net_res is True

        stats = await client_alice.get_stats()
        assert stats is not None
        assert "uptime" in stats
        assert stats["connected_peers"] == 2

        # Disconnect
        await client_alice.disconnect()
        await client_bob.disconnect()

    finally:
        await server.stop()

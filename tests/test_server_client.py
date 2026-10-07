"""
Asynchronous end-to-end integration tests for NetMash Server and Client.
"""

import asyncio
from pathlib import Path
import pytest

from netmash.client.client import NetMashClient
from netmash.identity import NodeIdentity
from netmash.server.server import NetMashServer
from netmash.storage.database import Database


@pytest.mark.asyncio
async def test_server_client_full_lifecycle(tmp_path: Path):
    db_path = tmp_path / "integration.db"
    db = Database(db_path)

    server_identity = NodeIdentity(
        node_id="server-node",
        username="HostUser",
        hostname="HOST-PC",
    )

    # Use port 9875 to avoid collisions during tests
    port = 9875
    server = NetMashServer(
        host_ip="127.0.0.1",
        port=port,
        discovery_port=9876,
        identity=server_identity,
        db=db,
    )
    await server.start()

    try:
        # Client 1: Alice
        alice_identity = NodeIdentity(
            node_id="alice-node",
            username="Alice",
            hostname="ALICE-PC",
        )
        client_alice = NetMashClient(host="127.0.0.1", port=port, identity=alice_identity)
        connected = await client_alice.connect(timeout=3.0)
        assert connected is True
        assert client_alice.server_info["host_name"] == "HOST-PC"

        # Client 2: Bob
        bob_identity = NodeIdentity(
            node_id="bob-node",
            username="Bob",
            hostname="BOB-PC",
        )
        client_bob = NetMashClient(host="127.0.0.1", port=port, identity=bob_identity)
        connected_bob = await client_bob.connect(timeout=3.0)
        assert connected_bob is True

        # Track received messages
        alice_received_chats = []
        alice_received_dms = []
        client_alice.on_chat_message = lambda msg: alice_received_chats.append(msg)
        client_alice.on_dm = lambda msg: alice_received_dms.append(msg)

        bob_received_chats = []
        bob_received_dms = []
        client_bob.on_chat_message = lambda msg: bob_received_chats.append(msg)
        client_bob.on_dm = lambda msg: bob_received_dms.append(msg)

        # 1. General Chat Test
        await client_alice.send_chat("Hello from Alice")
        await asyncio.sleep(0.1)

        assert any(c.payload.get("content") == "Hello from Alice" for c in bob_received_chats)

        # 2. Peer List Test
        peers = await client_bob.list_peers()
        usernames = [p["username"] for p in peers]
        assert "Alice" in usernames
        assert "Bob" in usernames

        # 3. Public Group Creation & Join Test
        create_res = await client_alice.create_group("developers")
        assert create_res["success"] is True

        join_res = await client_bob.join_group("developers")
        assert join_res["success"] is True

        # Chat in group
        await client_alice.send_chat("Dev discussion", room="developers")
        await asyncio.sleep(0.1)

        assert any(c.payload.get("content") == "Dev discussion" for c in bob_received_chats)

        # 4. PIN Protected Group Test
        pin_group_res = await client_alice.create_group("security", pin="1234")
        assert pin_group_res["success"] is True
        assert pin_group_res["access"] == "PIN"

        # Bob joins with wrong PIN
        wrong_pin_res = await client_bob.join_group("security", pin="9999")
        assert wrong_pin_res["success"] is False

        # Bob joins with correct PIN
        correct_pin_res = await client_bob.join_group("security", pin="1234")
        assert correct_pin_res["success"] is True

        # 5. Direct Message (DM) Test
        await client_alice.send_dm("Bob", "Secret DM to Bob")
        await asyncio.sleep(0.1)

        assert any(d.payload.get("content") == "Secret DM to Bob" for d in bob_received_dms)

        # 6. Status Test
        status = await client_bob.get_status()
        assert status["server_status"] == "ONLINE"
        assert status["peers_count"] == 2

        # Disconnect clients
        await client_alice.disconnect()
        await client_bob.disconnect()

    finally:
        await server.stop()

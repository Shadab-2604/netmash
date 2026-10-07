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

        # 7. Strict Room Isolation Test
        # Create third client Charlie who stays in GENERAL
        charlie_identity = NodeIdentity(node_id="charlie-node", username="Charlie", hostname="CHARLIE-PC")
        client_charlie = NetMashClient(host="127.0.0.1", port=port, identity=charlie_identity)
        await client_charlie.connect(timeout=3.0)
        charlie_received = []
        client_charlie.on_chat_message = lambda msg: charlie_received.append(msg)

        # Clear bob's received chats
        bob_received_chats.clear()

        # Alice is in security room and sends a message
        await client_alice.switch_room("security")
        await client_bob.switch_room("security")
        await client_alice.send_chat("Top secret security chat")
        await asyncio.sleep(0.1)

        # Bob (in security room) received it
        assert any(c.payload.get("content") == "Top secret security chat" for c in bob_received_chats)
        # Charlie (in general room) MUST NOT receive it
        assert not any(c.payload.get("content") == "Top secret security chat" for c in charlie_received)

        # Charlie sends message in GENERAL
        await client_charlie.send_chat("General announcement")
        await asyncio.sleep(0.1)

        # Alice and Bob are in security room, so they MUST NOT receive general announcement
        assert not any(c.payload.get("content") == "General announcement" for c in bob_received_chats)

        # 8. Set / Modify Group PIN Test
        # Alice (owner) modifies PIN of security group
        set_pin_res = await client_alice.set_group_pin("security", "5678")
        assert set_pin_res["success"] is True

        # Bob (non-owner) attempts to modify PIN -> should fail
        non_owner_res = await client_bob.set_group_pin("security", "0000")
        assert non_owner_res["success"] is False

        # Disconnect clients
        await client_alice.disconnect()
        await client_bob.disconnect()
        await client_charlie.disconnect()

    finally:
        await server.stop()


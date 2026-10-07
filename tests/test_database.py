"""
Unit tests for NetMash SQLite storage engine.
"""

from pathlib import Path
from netmash.storage.database import Database


def test_database_initialization(tmp_path: Path):
    db_path = tmp_path / "test_netmash.db"
    db = Database(db_path)

    # General group must exist by default
    gen = db.get_group("general")
    assert gen is not None
    assert gen["name"] == "general"

    # Upsert user
    db.upsert_user("node-1", "Alice", "Alice-PC")
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM users WHERE node_id = 'node-1'").fetchone()
    assert row is not None
    assert row["username"] == "Alice"

    # Save message
    db.save_message("msg-1", "node-1", "Alice", "general", "general", "Hello DB")
    msg_row = conn.execute("SELECT * FROM messages WHERE message_id = 'msg-1'").fetchone()
    assert msg_row is not None
    assert msg_row["content"] == "Hello DB"

    db.close()

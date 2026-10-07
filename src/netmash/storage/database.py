"""
SQLite database storage for NetMash.
Stores user records, group configurations, membership relations, and message history.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from netmash.config import get_db_file_path


class Database:
    """
    Manages local SQLite database operations for NetMash server and client.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or get_db_file_path()
        self._conn: Optional[sqlite3.Connection] = None
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def init_db(self) -> None:
        """Creates schema tables if they do not exist."""
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT UNIQUE NOT NULL,
                    username TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    owner_id TEXT NOT NULL,
                    pin_hash TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_members (
                    group_id INTEGER NOT NULL,
                    user_node_id TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, user_node_id),
                    FOREIGN KEY (group_id) REFERENCES groups (id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE NOT NULL,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    room_type TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )

            # Ensure default 'general' room exists
            cursor = conn.execute("SELECT id FROM groups WHERE name = 'general';")
            if not cursor.fetchone():
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO groups (name, owner_id, pin_hash, created_at)
                    VALUES ('general', 'system', NULL, ?);
                    """,
                    (now,),
                )

    def upsert_user(self, node_id: str, username: str, hostname: str) -> None:
        """Records or updates user presence in the database."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO users (node_id, username, hostname, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    username = excluded.username,
                    hostname = excluded.hostname,
                    last_seen = excluded.last_seen;
                """,
                (node_id, username, hostname, now, now),
            )

    def create_group(
        self, name: str, owner_id: str, pin_hash: Optional[str] = None
    ) -> bool:
        """Creates a new group. Returns True if created, False if already exists."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO groups (name, owner_id, pin_hash, created_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (name.lower(), owner_id, pin_hash, now),
                )
                group_id = cursor.lastrowid
                # Automatically add owner as member
                conn.execute(
                    """
                    INSERT INTO group_members (group_id, user_node_id, joined_at)
                    VALUES (?, ?, ?);
                    """,
                    (group_id, owner_id, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_group(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves group details by name."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT id, name, owner_id, pin_hash, created_at FROM groups WHERE name = ?;",
            (name.lower(),),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def update_group_pin(self, name: str, pin_hash: Optional[str]) -> bool:
        """Updates or removes the PIN hash for a group."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE groups SET pin_hash = ? WHERE name = ?;",
                    (pin_hash, name.lower()),
                )
                return cursor.rowcount > 0
        except Exception:
            return False

    def list_groups(self) -> List[Dict[str, Any]]:
        """Lists all groups along with total registered member counts."""
        conn = self.get_connection()
        cursor = conn.execute(
            """
            SELECT g.id, g.name, g.owner_id, g.pin_hash, g.created_at,
                   COUNT(m.user_node_id) as member_count
            FROM groups g
            LEFT JOIN group_members m ON g.id = m.group_id
            GROUP BY g.id
            ORDER BY g.id ASC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def add_group_member(self, group_name: str, user_node_id: str) -> bool:
        """Adds a user to a group."""
        group = self.get_group(group_name)
        if not group:
            return False
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO group_members (group_id, user_node_id, joined_at)
                    VALUES (?, ?, ?);
                    """,
                    (group["id"], user_node_id, now),
                )
            return True
        except Exception:
            return False

    def remove_group_member(self, group_name: str, user_node_id: str) -> bool:
        """Removes a user from a group."""
        group = self.get_group(group_name)
        if not group:
            return False
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    DELETE FROM group_members
                    WHERE group_id = ? AND user_node_id = ?;
                    """,
                    (group["id"], user_node_id),
                )
            return True
        except Exception:
            return False

    def is_group_member(self, group_name: str, user_node_id: str) -> bool:
        """Checks if a user is a member of a group."""
        group = self.get_group(group_name)
        if not group:
            return False
        if group["name"] == "general":
            return True
        conn = self.get_connection()
        cursor = conn.execute(
            """
            SELECT 1 FROM group_members
            WHERE group_id = ? AND user_node_id = ?;
            """,
            (group["id"], user_node_id),
        )
        return cursor.fetchone() is not None

    def save_message(
        self,
        message_id: str,
        sender_id: str,
        sender_name: str,
        room_type: str,
        room_id: str,
        content: str,
        timestamp: Optional[str] = None,
    ) -> None:
        """Stores a message record."""
        now = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                    (message_id, sender_id, sender_name, room_type, room_id, content, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (message_id, sender_id, sender_name, room_type, room_id, content, now),
                )
        except Exception:
            pass

    def close(self) -> None:
        """Closes database connection cleanly."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

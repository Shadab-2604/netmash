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
                    role TEXT NOT NULL DEFAULT 'MEMBER',
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, user_node_id),
                    FOREIGN KEY (group_id) REFERENCES groups (id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bans (
                    group_id INTEGER NOT NULL,
                    user_node_id TEXT NOT NULL,
                    banned_by TEXT NOT NULL,
                    banned_at TEXT NOT NULL,
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
                    timestamp TEXT NOT NULL,
                    edited INTEGER NOT NULL DEFAULT 0,
                    edited_at TEXT,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    reply_to TEXT,
                    pinned INTEGER NOT NULL DEFAULT 0
                );
                """
            )

            # Auto-migrate existing databases if columns are missing
            try:
                conn.execute("ALTER TABLE group_members ADD COLUMN role TEXT NOT NULL DEFAULT 'MEMBER';")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN edited INTEGER NOT NULL DEFAULT 0;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN edited_at TEXT;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN reply_to TEXT;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;")
            except Exception:
                pass

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

    def get_user_by_node_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves user by node_id."""
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM users WHERE node_id = ?;", (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_node_id_by_username(self, username: str) -> Optional[str]:
        """Finds node_id for a given username."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT node_id FROM users WHERE LOWER(username) = LOWER(?) ORDER BY last_seen DESC LIMIT 1;",
            (username.strip(),),
        )
        row = cursor.fetchone()
        return row["node_id"] if row else None

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
                # Automatically add owner as member with OWNER role
                conn.execute(
                    """
                    INSERT INTO group_members (group_id, user_node_id, role, joined_at)
                    VALUES (?, ?, 'OWNER', ?);
                    """,
                    (group_id, owner_id, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_group(self, name: str) -> bool:
        """Deletes a group and cascades its memberships and bans."""
        norm_name = name.lower().strip()
        if norm_name == "general":
            return False
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute("DELETE FROM groups WHERE name = ?;", (norm_name,))
                return cursor.rowcount > 0
        except Exception:
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

    def add_group_member(self, group_name: str, user_node_id: str, role: str = "MEMBER") -> bool:
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
                    INSERT INTO group_members (group_id, user_node_id, role, joined_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(group_id, user_node_id) DO UPDATE SET role = excluded.role;
                    """,
                    (group["id"], user_node_id, role, now),
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

    def get_group_role(self, group_name: str, user_node_id: str) -> str:
        """Returns the role of a user in a group ('OWNER', 'MODERATOR', 'MEMBER', or 'NONE')."""
        group = self.get_group(group_name)
        if not group:
            return "NONE"
        if group["owner_id"] == user_node_id:
            return "OWNER"
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT role FROM group_members WHERE group_id = ? AND user_node_id = ?;",
            (group["id"], user_node_id),
        )
        row = cursor.fetchone()
        if row:
            return row["role"]
        return "MEMBER" if group["name"] == "general" else "NONE"

    def list_group_members(self, group_name: str) -> List[Dict[str, Any]]:
        """Returns detailed list of members for a group."""
        group = self.get_group(group_name)
        if not group:
            return []
        conn = self.get_connection()
        cursor = conn.execute(
            """
            SELECT gm.user_node_id, gm.role, gm.joined_at, u.username, u.hostname
            FROM group_members gm
            LEFT JOIN users u ON gm.user_node_id = u.node_id
            WHERE gm.group_id = ?
            ORDER BY CASE gm.role WHEN 'OWNER' THEN 1 WHEN 'MODERATOR' THEN 2 ELSE 3 END, gm.joined_at ASC;
            """,
            (group["id"],),
        )
        return [dict(row) for row in cursor.fetchall()]

    def ban_user(self, group_name: str, user_node_id: str, banned_by: str) -> bool:
        """Bans a user from a group and removes their membership."""
        group = self.get_group(group_name)
        if not group or group["name"] == "general":
            return False
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bans (group_id, user_node_id, banned_by, banned_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (group["id"], user_node_id, banned_by, now),
                )
                conn.execute(
                    "DELETE FROM group_members WHERE group_id = ? AND user_node_id = ?;",
                    (group["id"], user_node_id),
                )
            return True
        except Exception:
            return False

    def unban_user(self, group_name: str, user_node_id: str) -> bool:
        """Unbans a user from a group."""
        group = self.get_group(group_name)
        if not group:
            return False
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM bans WHERE group_id = ? AND user_node_id = ?;",
                    (group["id"], user_node_id),
                )
                return cursor.rowcount > 0
        except Exception:
            return False

    def is_banned(self, group_name: str, user_node_id: str) -> bool:
        """Checks if a user is banned from a group."""
        group = self.get_group(group_name)
        if not group:
            return False
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT 1 FROM bans WHERE group_id = ? AND user_node_id = ?;",
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
        reply_to: Optional[str] = None,
    ) -> None:
        """Stores a message record."""
        now = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                    (message_id, sender_id, sender_name, room_type, room_id, content, timestamp, reply_to)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (message_id, sender_id, sender_name, room_type, room_id, content, now, reply_to),
                )
        except Exception:
            pass

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single message by ID."""
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM messages WHERE message_id = ?;", (message_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_room_history(self, room_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves recent non-deleted or soft-deleted messages for a room."""
        conn = self.get_connection()
        cursor = conn.execute(
            """
            SELECT message_id, sender_id, sender_name, room_type, room_id, content,
                   timestamp, edited, edited_at, deleted, reply_to, pinned
            FROM messages
            WHERE room_id = ?
            ORDER BY id DESC LIMIT ?;
            """,
            (room_id.lower().strip(), max(1, min(limit, 200))),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        rows.reverse()
        return rows

    def search_messages(self, query: str, allowed_rooms: List[str], limit: int = 20) -> List[Dict[str, Any]]:
        """Searches authorized room messages."""
        if not allowed_rooms or not query.strip():
            return []
        conn = self.get_connection()
        placeholders = ",".join("?" for _ in allowed_rooms)
        search_term = f"%{query.strip()}%"
        params = [search_term] + [r.lower().strip() for r in allowed_rooms] + [max(1, min(limit, 50))]
        cursor = conn.execute(
            f"""
            SELECT message_id, sender_id, sender_name, room_type, room_id, content,
                   timestamp, edited, edited_at, deleted, reply_to, pinned
            FROM messages
            WHERE content LIKE ? AND room_id IN ({placeholders}) AND deleted = 0
            ORDER BY id DESC LIMIT ?;
            """,
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]
        rows.reverse()
        return rows

    def edit_message(self, message_id: str, sender_id: str, new_content: str) -> bool:
        """Edits an existing message (sender only)."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE messages
                    SET content = ?, edited = 1, edited_at = ?
                    WHERE message_id = ? AND sender_id = ? AND deleted = 0;
                    """,
                    (new_content, now, message_id, sender_id),
                )
                return cursor.rowcount > 0
        except Exception:
            return False

    def delete_message(self, message_id: str) -> bool:
        """Soft-deletes a message."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE messages
                    SET deleted = 1, content = '[message deleted]'
                    WHERE message_id = ?;
                    """,
                    (message_id,),
                )
                return cursor.rowcount > 0
        except Exception:
            return False

    def pin_message(self, message_id: str, is_pinned: bool = True) -> bool:
        """Pins or unpins a message."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE messages SET pinned = ? WHERE message_id = ?;",
                    (1 if is_pinned else 0, message_id),
                )
                return cursor.rowcount > 0
        except Exception:
            return False

    def get_pinned_messages(self, room_id: str) -> List[Dict[str, Any]]:
        """Returns pinned messages for a room."""
        conn = self.get_connection()
        cursor = conn.execute(
            """
            SELECT message_id, sender_id, sender_name, room_type, room_id, content,
                   timestamp, edited, edited_at, deleted, reply_to, pinned
            FROM messages
            WHERE room_id = ? AND pinned = 1 AND deleted = 0
            ORDER BY id ASC;
            """,
            (room_id.lower().strip(),),
        )
        return [dict(r) for r in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Returns database counts."""
        conn = self.get_connection()
        total_msgs = conn.execute("SELECT COUNT(*) FROM messages;").fetchone()[0]
        total_groups = conn.execute("SELECT COUNT(*) FROM groups;").fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
        return {
            "total_messages": total_msgs,
            "total_groups": total_groups,
            "total_users": total_users,
        }

    def close(self) -> None:
        """Closes database connection cleanly."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

"""
Chat message coordinator and history tracker for NetMash.
Provides message formatting and storage integration.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional
from netmash.storage.database import Database
from netmash.utils.security import sanitize_terminal_text


@dataclass
class ChatEntry:
    message_id: str
    sender_id: str
    sender_name: str
    room: str
    content: str
    timestamp: str
    reply_to: Optional[str] = None


class ChatManager:
    """
    Coordinates chat message persistence and sanitized formatting.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def record_message(
        self,
        message_id: str,
        sender_id: str,
        sender_name: str,
        room: str,
        content: str,
        timestamp: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> ChatEntry:
        """
        Sanitizes, records to database, and returns a ChatEntry.
        """
        now = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        sanitized_content = sanitize_terminal_text(content)
        sanitized_name = sanitize_terminal_text(sender_name)

        self.db.save_message(
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sanitized_name,
            room_type="group" if room != "general" else "general",
            room_id=room,
            content=sanitized_content,
            timestamp=now,
            reply_to=reply_to,
        )

        return ChatEntry(
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sanitized_name,
            room=room,
            content=sanitized_content,
            timestamp=now,
            reply_to=reply_to,
        )

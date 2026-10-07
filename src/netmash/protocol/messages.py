"""
Structured protocol messages for NetMash.
Provides message serialization, parsing, and framing over TCP streams.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from netmash.config import PROTOCOL_VERSION


class MessageType:
    HELLO = "hello"
    WELCOME = "welcome"
    CHAT_MESSAGE = "chat_message"
    GROUP_CREATE = "group_create"
    GROUP_CREATE_RESPONSE = "group_create_response"
    GROUP_LIST = "group_list"
    GROUP_LIST_RESPONSE = "group_list_response"
    GROUP_JOIN = "group_join"
    GROUP_JOIN_RESPONSE = "group_join_response"
    GROUP_LEAVE = "group_leave"
    GROUP_LEAVE_RESPONSE = "group_leave_response"
    GROUP_INFO = "group_info"
    GROUP_INFO_RESPONSE = "group_info_response"
    GROUP_SET_PIN = "group_set_pin"
    GROUP_SET_PIN_RESPONSE = "group_set_pin_response"
    ROOM_SWITCH = "room_switch"
    ROOM_SWITCH_RESPONSE = "room_switch_response"
    DM = "dm"
    PEER_LIST = "peer_list"
    PEER_LIST_RESPONSE = "peer_list_response"
    PEER_JOIN = "peer_join"
    PEER_LEAVE = "peer_leave"
    NAME_CHANGE = "name_change"
    NAME_CHANGE_BROADCAST = "name_change_broadcast"
    INFO_REQUEST = "info_request"
    INFO_RESPONSE = "info_response"
    STATUS_REQUEST = "status_request"
    STATUS_RESPONSE = "status_response"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"
    # Future V2 File Transfer Placeholders
    FILE_OFFER = "file_offer"
    FILE_ACCEPT = "file_accept"
    FILE_REJECT = "file_reject"
    FILE_CHUNK = "file_chunk"
    FILE_COMPLETE = "file_complete"


@dataclass
class NetMashMessage:
    """
    Standard message wrapper for NetMash communication.
    """
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        """Serializes message to a JSON string."""
        data = {
            "type": self.type,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        return json.dumps(data, separators=(",", ":"))

    def to_bytes(self) -> bytes:
        """Serializes message to newline-delimited UTF-8 bytes for TCP stream."""
        return (self.to_json() + "\n").encode("utf-8")

    @classmethod
    def from_json(cls, json_str: str) -> "NetMashMessage":
        """
        Parses JSON string into NetMashMessage.
        Raises ValueError if malformed or invalid schema.
        """
        if not json_str or not json_str.strip():
            raise ValueError("Empty message string")

        data = json.loads(json_str)
        if not isinstance(data, dict):
            raise ValueError("Message root must be a JSON object")

        msg_type = data.get("type")
        if not msg_type or not isinstance(msg_type, str):
            raise ValueError("Message missing valid 'type' field")

        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        request_id = str(data.get("request_id", uuid.uuid4()))
        timestamp = str(data.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat()))

        return cls(
            type=msg_type,
            payload=payload,
            request_id=request_id,
            timestamp=timestamp,
        )


# Helper constructors for standard messages


def make_hello(node_id: str, username: str, hostname: str) -> NetMashMessage:
    return NetMashMessage(
        type=MessageType.HELLO,
        payload={
            "node_id": node_id,
            "username": username,
            "hostname": hostname,
            "version": PROTOCOL_VERSION,
        },
    )


def make_welcome(
    node_id: str,
    host_name: str,
    host_node_id: str,
    peers_count: int,
    groups_count: int,
    default_room: str = "general",
) -> NetMashMessage:
    return NetMashMessage(
        type=MessageType.WELCOME,
        payload={
            "node_id": node_id,
            "host_name": host_name,
            "host_node_id": host_node_id,
            "server_version": PROTOCOL_VERSION,
            "peers_count": peers_count,
            "groups_count": groups_count,
            "default_room": default_room,
        },
    )


def make_chat_message(
    room: str,
    content: str,
    sender_name: str = "",
    sender_id: str = "",
    message_id: Optional[str] = None,
) -> NetMashMessage:
    return NetMashMessage(
        type=MessageType.CHAT_MESSAGE,
        payload={
            "message_id": message_id or str(uuid.uuid4()),
            "room": room,
            "content": content,
            "sender_name": sender_name,
            "sender_id": sender_id,
        },
    )


def make_dm(
    target_username: str,
    content: str,
    sender_name: str = "",
    sender_id: str = "",
    message_id: Optional[str] = None,
) -> NetMashMessage:
    return NetMashMessage(
        type=MessageType.DM,
        payload={
            "message_id": message_id or str(uuid.uuid4()),
            "target": target_username,
            "content": content,
            "sender_name": sender_name,
            "sender_id": sender_id,
        },
    )


def make_error(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> NetMashMessage:
    return NetMashMessage(
        type=MessageType.ERROR,
        payload={
            "code": code,
            "message": message,
            "details": details or {},
        },
    )


def make_ping() -> NetMashMessage:
    return NetMashMessage(type=MessageType.PING, payload={})


def make_pong() -> NetMashMessage:
    return NetMashMessage(type=MessageType.PONG, payload={})

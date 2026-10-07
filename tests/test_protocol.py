"""
Unit tests for NetMash message protocol serialization and parsing.
"""

import pytest
from netmash.protocol.messages import (
    MessageType,
    NetMashMessage,
    make_chat_message,
    make_dm,
    make_hello,
    make_welcome,
)


def test_message_serialization_and_parsing():
    msg = make_hello("node-123", "Shadab", "PC-1")
    json_bytes = msg.to_bytes()

    assert json_bytes.endswith(b"\n")

    decoded = NetMashMessage.from_json(json_bytes.decode("utf-8").strip())
    assert decoded.type == MessageType.HELLO
    assert decoded.payload["node_id"] == "node-123"
    assert decoded.payload["username"] == "Shadab"
    assert decoded.payload["hostname"] == "PC-1"


def test_malformed_message_rejection():
    invalid_inputs = [
        "",
        "   ",
        "not json",
        '{"missing_type": true}',
        '{"type": 123}',
        "[]",
    ]

    for inv in invalid_inputs:
        with pytest.raises(ValueError):
            NetMashMessage.from_json(inv)


def test_chat_message_creation():
    chat = make_chat_message(
        room="developers",
        content="Hello world",
        sender_name="Alice",
        sender_id="node-alice",
    )
    assert chat.type == MessageType.CHAT_MESSAGE
    assert chat.payload["room"] == "developers"
    assert chat.payload["content"] == "Hello world"
    assert chat.payload["sender_name"] == "Alice"


def test_dm_message_creation():
    dm = make_dm(
        target_username="Bob",
        content="Secret message",
        sender_name="Alice",
        sender_id="node-alice",
    )
    assert dm.type == MessageType.DM
    assert dm.payload["target"] == "Bob"
    assert dm.payload["content"] == "Secret message"


def test_oversized_message_validation():
    from netmash.utils.validation import validate_message_content
    # Max size is 4096
    valid_content = "x" * 4096
    is_valid, _, err = validate_message_content(valid_content)
    assert is_valid is True

    oversized = "x" * 4097
    is_valid, _, err = validate_message_content(oversized)
    assert is_valid is False
    assert "maximum size" in err


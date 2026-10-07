"""
Unit tests for NetMash identity and node ID management.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from netmash.identity import get_or_create_identity, update_username
from netmash.utils.validation import validate_username


def test_node_id_generation_and_persistence(tmp_path: Path):
    with patch("netmash.config.get_app_dir", return_value=tmp_path):
        identity1 = get_or_create_identity()
        assert identity1.node_id is not None
        assert len(identity1.node_id) > 10
        assert identity1.username is not None

        # Call again, should return the exact same node_id
        identity2 = get_or_create_identity()
        assert identity1.node_id == identity2.node_id


def test_custom_username_override(tmp_path: Path):
    with patch("netmash.config.get_app_dir", return_value=tmp_path):
        identity = get_or_create_identity(custom_name="Alice")
        assert identity.username == "Alice"

        # Update username
        success, msg, updated = update_username("Bob")
        assert success is True
        assert updated.username == "Bob"


def test_username_validation():
    # Valid usernames
    valid_names = ["Shadab", "Alice_123", "User-Name", "John Doe", "A" * 32]
    for name in valid_names:
        is_valid, cleaned, err = validate_username(name)
        assert is_valid is True, f"Failed for {name}: {err}"
        assert cleaned == name.strip()

    # Invalid usernames
    invalid_cases = [
        ("", "cannot be empty"),
        (" ", "cannot be empty"),
        ("a", "at least 2 characters"),
        ("A" * 33, "at most 32 characters"),
        ("User\x1b[31mRed", "valid or stripped"),
        ("User\x00Bad", "control characters"),
    ]
    for name, expected_err in invalid_cases:
        is_valid, cleaned, err = validate_username(name)
        if name == "User\x1b[31mRed":
            # ANSI should be cleanly stripped to 'UserRed'
            assert is_valid is True
            assert cleaned == "UserRed"
        else:
            assert is_valid is False, f"Expected invalid for {name}"

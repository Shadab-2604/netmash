"""
Unit tests for NetMash group management and PIN access.
"""

from pathlib import Path
from netmash.groups.manager import GroupManager
from netmash.storage.database import Database
from netmash.utils.validation import validate_group_name, validate_pin


def test_group_name_validation():
    # Valid
    for name in ["developers", "dev-team", "dev_ops", "team123", "g1"]:
        is_valid, cleaned, err = validate_group_name(name)
        assert is_valid is True, f"Failed for {name}: {err}"
        assert cleaned == name.lower()

    # Invalid
    for name in ["", "a", "A" * 33, "dev team", "dev@ops", "dev/team"]:
        is_valid, cleaned, err = validate_group_name(name)
        assert is_valid is False, f"Expected invalid for {name}"


def test_pin_validation():
    # Valid 4-digit PINs
    for pin in ["1234", "0000", "9876", "0123"]:
        is_valid, cleaned, err = validate_pin(pin)
        assert is_valid is True, f"Failed for {pin}: {err}"

    # Invalid PINs
    for pin in ["123", "12345", "abcd", "12a4", "", " 123 "]:
        if pin == " 123 ":
            is_valid, _, _ = validate_pin(pin)
            assert is_valid is False
        else:
            is_valid, _, _ = validate_pin(pin)
            assert is_valid is False, f"Expected invalid for {pin}"


def test_group_creation_and_duplicates(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    mgr = GroupManager(db)

    # Create public group
    success, msg, details = mgr.create_group("developers", "node-1")
    assert success is True
    assert details["name"] == "developers"
    assert details["access"] == "PUBLIC"

    # Duplicate group creation should fail
    dup_success, dup_msg, _ = mgr.create_group("developers", "node-2")
    assert dup_success is False
    assert "already exists" in dup_msg.lower()

    # Case insensitive duplicate
    dup_success2, dup_msg2, _ = mgr.create_group("DEVELOPERS", "node-3")
    assert dup_success2 is False
    assert "already exists" in dup_msg2.lower()


def test_pin_protected_group_join_and_lockout(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    mgr = GroupManager(db)

    # Create PIN group
    success, _, details = mgr.create_group("security", "node-owner", pin="4321")
    assert success is True
    assert details["access"] == "PIN"

    # Attempt join without PIN
    j_succ, j_msg, req_pin = mgr.join_group("security", "node-visitor")
    assert j_succ is False
    assert req_pin is True

    # Attempt join with wrong PIN
    for _ in range(4):
        j_succ, j_msg, req_pin = mgr.join_group("security", "node-visitor", pin="0000")
        assert j_succ is False
        assert "Invalid PIN" in j_msg

    # 5th failed attempt triggers lockout
    j_succ, j_msg, req_pin = mgr.join_group("security", "node-visitor", pin="0000")
    assert j_succ is False

    # 6th attempt should be locked out
    j_succ, j_msg, req_pin = mgr.join_group("security", "node-visitor", pin="4321")
    assert j_succ is False
    assert "locked out" in j_msg.lower()

    # Different user with correct PIN can join immediately
    j_succ2, j_msg2, _ = mgr.join_group("security", "node-other", pin="4321")
    assert j_succ2 is True
    assert "successfully" in j_msg2.lower()

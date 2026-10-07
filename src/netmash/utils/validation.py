"""
Input validation utilities for NetMash.
Provides validation and sanitization for usernames, group names, PINs, and messages.
"""

from __future__ import annotations

import re
from typing import Tuple
from netmash.config import (
    MAX_GROUP_NAME_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_GROUP_NAME_LENGTH,
    MIN_USERNAME_LENGTH,
    PIN_LENGTH,
)

# Regex to detect control characters (excluding standard whitespace like space)
CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Regex for ANSI escape sequences
ANSI_ESCAPE_REGEX = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Regex for valid group names (alphanumeric, hyphens, underscores)
GROUP_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")
# Regex for 4-digit PIN
PIN_REGEX = re.compile(r"^\d{4}$")


def validate_username(username: str | None) -> Tuple[bool, str, str]:
    """
    Validates a username.
    Returns (is_valid, sanitized_name, error_message).
    Rules:
    - 2-32 characters
    - Trim whitespace
    - No control characters
    - No terminal escape sequences
    """
    if username is None:
        return False, "", "Username cannot be empty."

    # Remove escape sequences and trim
    cleaned = ANSI_ESCAPE_REGEX.sub("", username).strip()

    if not cleaned:
        return False, "", "Username cannot be empty."

    if len(cleaned) < MIN_USERNAME_LENGTH:
        return False, "", f"Username must be at least {MIN_USERNAME_LENGTH} characters."

    if len(cleaned) > MAX_USERNAME_LENGTH:
        return False, "", f"Username must be at most {MAX_USERNAME_LENGTH} characters."

    if CONTROL_CHAR_REGEX.search(cleaned):
        return False, "", "Username cannot contain control characters."

    return True, cleaned, ""


def validate_group_name(group_name: str | None) -> Tuple[bool, str, str]:
    """
    Validates a group name.
    Returns (is_valid, normalized_name, error_message).
    Rules:
    - 2-32 characters
    - Alphanumeric, hyphens, and underscores only
    - Normalized to lowercase
    """
    if group_name is None:
        return False, "", "Group name cannot be empty."

    cleaned = group_name.strip().lower()

    if not cleaned:
        return False, "", "Group name cannot be empty."

    if len(cleaned) < MIN_GROUP_NAME_LENGTH:
        return False, "", f"Group name must be at least {MIN_GROUP_NAME_LENGTH} characters."

    if len(cleaned) > MAX_GROUP_NAME_LENGTH:
        return False, "", f"Group name must be at most {MAX_GROUP_NAME_LENGTH} characters."

    if not GROUP_NAME_REGEX.match(cleaned):
        return (
            False,
            "",
            "Group name must contain only letters, numbers, hyphens, and underscores.",
        )

    return True, cleaned, ""


def validate_pin(pin: str | None) -> Tuple[bool, str, str]:
    """
    Validates a 4-digit PIN.
    Returns (is_valid, pin, error_message).
    """
    if pin is None:
        return False, "", "PIN cannot be empty."

    cleaned = pin.strip()

    if not PIN_REGEX.match(cleaned):
        return False, "", f"PIN must be exactly {PIN_LENGTH} digits (0-9)."

    return True, cleaned, ""


def validate_message_content(content: str | None) -> Tuple[bool, str, str]:
    """
    Validates chat message content.
    Returns (is_valid, sanitized_content, error_message).
    Rules:
    - 1 to 4096 characters
    """
    if content is None:
        return False, "", "Message cannot be empty."

    cleaned = content.strip()
    if not cleaned:
        return False, "", "Message cannot be empty."

    if len(content) > MAX_MESSAGE_LENGTH:
        return False, "", f"Message exceeds maximum size of {MAX_MESSAGE_LENGTH} characters."

    return True, content, ""

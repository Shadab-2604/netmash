"""
Node identity and user management for NetMash.
Manages persistent node UUID and display name configuration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from netmash.config import load_config, save_config
from netmash.utils.network import get_system_hostname
from netmash.utils.validation import validate_username


@dataclass
class NodeIdentity:
    node_id: str
    username: str
    hostname: str


def get_or_create_identity(custom_name: Optional[str] = None) -> NodeIdentity:
    """
    Retrieves the persistent node identity from config, or generates a new one.
    If custom_name is provided, it overrides the username if valid.
    """
    config = load_config()
    hostname = get_system_hostname()

    node_id = config.get("node_id")
    if not node_id:
        node_id = str(uuid.uuid4())
        config["node_id"] = node_id

    # Determine username
    saved_username = config.get("username")

    if custom_name:
        is_valid, sanitized, _ = validate_username(custom_name)
        username = sanitized if is_valid else (saved_username or hostname)
    elif saved_username:
        is_valid, sanitized, _ = validate_username(saved_username)
        username = sanitized if is_valid else hostname
    else:
        is_valid, sanitized, _ = validate_username(hostname)
        username = sanitized if is_valid else "User"

    # Save updated config
    config["username"] = username
    config["hostname"] = hostname
    save_config(config)

    return NodeIdentity(
        node_id=node_id,
        username=username,
        hostname=hostname,
    )


def update_username(new_name: str) -> tuple[bool, str, NodeIdentity | None]:
    """
    Updates the local node's saved username.
    Returns (success, message, updated_identity).
    """
    is_valid, sanitized, err = validate_username(new_name)
    if not is_valid:
        return False, err, None

    config = load_config()
    config["username"] = sanitized
    save_config(config)

    identity = NodeIdentity(
        node_id=config.get("node_id", str(uuid.uuid4())),
        username=sanitized,
        hostname=get_system_hostname(),
    )
    return True, f"Username updated to '{sanitized}'.", identity

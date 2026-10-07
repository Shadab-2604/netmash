"""
Security and sanitization utilities for NetMash.
Includes terminal escape code sanitization, cryptographic PIN hashing with scrypt,
and rate limiting to prevent message flooding and brute force attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Dict, Tuple

# Regex to strip ANSI escape sequences, CSI codes, OSC sequences, and control codes
# Leaves standard printable unicode and normal whitespace (space, tab, newline)
ANSI_STRIP_REGEX = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI (Control Sequence Introducer)
    r"|\x1b\][^\x07\x1b]*(\x07|\x1b\\)"  # OSC (Operating System Command)
    r"|\x1b[@-Z\\-_]"  # 2-character Fe escape sequences
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # Unprintable ASCII control characters
)


def sanitize_terminal_text(text: str) -> str:
    """
    Sanitizes text before displaying it in the terminal.
    Strips harmful escape sequences, control characters, and terminal manipulation codes.
    Preserves normal newlines and tabs.
    """
    if not text:
        return ""
    # Strip dangerous sequences
    sanitized = ANSI_STRIP_REGEX.sub("", text)
    return sanitized


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    """
    Hashes a 4-digit PIN using scrypt (memory-hard password hashing).
    Format: scrypt$<salt_hex>$<hash_hex>
    """
    if salt is None:
        salt = os.urandom(16)

    # Scrypt parameters: N=16384, r=8, p=1, maxmem=32MB
    derived = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        maxmem=32 * 1024 * 1024,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    """
    Verifies a PIN against a stored scrypt hash in constant time.
    """
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3 or parts[0] != "scrypt":
            return False

        salt = bytes.fromhex(parts[1])
        expected_hash = bytes.fromhex(parts[2])

        actual_hash = hashlib.scrypt(
            pin.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            maxmem=32 * 1024 * 1024,
            dklen=32,
        )

        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


class MessageRateLimiter:
    """
    Token bucket rate limiter for message traffic per client.
    Prevents message flooding and server resource exhaustion.
    """

    def __init__(self, rate: float = 5.0, capacity: float = 10.0) -> None:
        self.rate = rate  # Tokens per second
        self.capacity = capacity  # Maximum bucket capacity
        self.tokens: Dict[str, float] = {}
        self.last_update: Dict[str, float] = {}

    def allow_message(self, client_id: str) -> bool:
        now = time.monotonic()
        tokens = self.tokens.get(client_id, self.capacity)
        last = self.last_update.get(client_id, now)

        # Refill tokens based on elapsed time
        elapsed = now - last
        tokens = min(self.capacity, tokens + elapsed * self.rate)

        self.last_update[client_id] = now

        if tokens >= 1.0:
            self.tokens[client_id] = tokens - 1.0
            return True
        else:
            self.tokens[client_id] = tokens
            return False

    def remove_client(self, client_id: str) -> None:
        self.tokens.pop(client_id, None)
        self.last_update.pop(client_id, None)


class PinAttemptLimiter:
    """
    Rate limiter and lockout tracker for group PIN verification.
    Mitigates 4-digit PIN brute-force guessing attacks.
    """

    def __init__(self, max_attempts: int = 5, lockout_seconds: float = 30.0) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self.attempts: Dict[str, int] = {}  # key: f"{node_id}:{group_name}" -> count
        self.lockout_until: Dict[str, float] = {}

    def is_locked_out(self, node_id: str, group_name: str) -> Tuple[bool, float]:
        key = f"{node_id}:{group_name}"
        now = time.monotonic()
        locked_until = self.lockout_until.get(key, 0.0)
        if now < locked_until:
            remaining = locked_until - now
            return True, remaining
        return False, 0.0

    def record_attempt(self, node_id: str, group_name: str, success: bool) -> None:
        key = f"{node_id}:{group_name}"
        if success:
            self.attempts.pop(key, None)
            self.lockout_until.pop(key, None)
            return

        now = time.monotonic()
        count = self.attempts.get(key, 0) + 1
        self.attempts[key] = count

        if count >= self.max_attempts:
            self.lockout_until[key] = now + self.lockout_seconds
            self.attempts[key] = 0  # Reset counter for next round after lockout expires

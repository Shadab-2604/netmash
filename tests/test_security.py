"""
Unit tests for NetMash security features: terminal sanitization, scrypt hashing, and rate limiting.
"""

import time
from netmash.utils.security import (
    MessageRateLimiter,
    hash_pin,
    sanitize_terminal_text,
    verify_pin,
)


def test_terminal_escape_sanitization():
    # ANSI color codes
    input_text = "\x1b[31mRed Alert\x1b[0m"
    assert sanitize_terminal_text(input_text) == "Red Alert"

    # OSC title setting command
    malicious_osc = "\x1b]0;Hacked Title\x07Hello"
    assert sanitize_terminal_text(malicious_osc) == "Hello"

    # Control characters
    control_text = "Safe\x00\x07\x1fText"
    assert sanitize_terminal_text(control_text) == "SafeText"

    # Preserves tabs and newlines
    normal_multiline = "Line 1\n\tLine 2"
    assert sanitize_terminal_text(normal_multiline) == "Line 1\n\tLine 2"


def test_pin_hashing_and_verification():
    pin = "1234"
    pin_hash = hash_pin(pin)

    assert pin_hash.startswith("scrypt$")
    # Correct PIN verifies
    assert verify_pin("1234", pin_hash) is True
    # Wrong PIN fails
    assert verify_pin("0000", pin_hash) is False
    assert verify_pin("1235", pin_hash) is False


def test_message_rate_limiter():
    limiter = MessageRateLimiter(rate=2.0, capacity=3.0)
    client_id = "node-test"

    # Should allow up to capacity
    assert limiter.allow_message(client_id) is True
    assert limiter.allow_message(client_id) is True
    assert limiter.allow_message(client_id) is True

    # 4th message in immediate succession should be blocked
    assert limiter.allow_message(client_id) is False

    # Wait for token replenishment
    time.sleep(0.6)
    assert limiter.allow_message(client_id) is True

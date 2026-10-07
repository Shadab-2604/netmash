"""
Unit and Integration tests for NetMash 10-Theme System.
Tests:
- Centralized theme registry containing all 10 distinct themes.
- Semantic style application across all themes.
- Theme retrieval by numeric ID (1-10) and case-insensitive name.
- Invalid theme ID handling.
- Random theme selection avoiding the active theme.
- Persistent local configuration saving and loading.
- Graceful plain-text fallback when ANSI colors are disabled.
- Terminal theme list rendering and dynamic usage instructions.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
import pytest

from netmash.config import get_app_dir, load_config, save_config
from netmash.ui.terminal import render_invalid_theme, render_theme_list
from netmash.ui.theme import (
    THEMES,
    Theme,
    get_active_theme,
    get_all_themes,
    get_theme,
    get_theme_count,
    init_colors,
    is_color_enabled,
    load_saved_theme,
    save_active_theme,
    set_active_theme,
    set_random_theme,
)


def test_theme_registry_contains_10_themes():
    """Verifies that exactly 10 built-in themes are registered with unique IDs 1-10."""
    themes = get_all_themes()
    assert len(themes) == 10
    assert get_theme_count() == 10

    expected_names = [
        "Classic",
        "Ocean",
        "Matrix",
        "Sunset",
        "Mono",
        "Dracula",
        "Cyberpunk",
        "Forest",
        "Royal",
        "Terminal",
    ]

    for idx, expected_name in enumerate(expected_names, 1):
        theme = get_theme(idx)
        assert theme is not None
        assert theme.id == idx
        assert theme.name == expected_name
        assert theme.style_desc != ""


def test_theme_lookup_by_id_and_name():
    """Tests theme lookup by integer ID, string digit ID, and case-insensitive name."""
    # Lookup by int ID
    assert get_theme(1).name == "Classic"
    assert get_theme(3).name == "Matrix"
    assert get_theme(7).name == "Cyberpunk"
    assert get_theme(10).name == "Terminal"

    # Lookup by string digit
    assert get_theme("2").name == "Ocean"
    assert get_theme("6").name == "Dracula"
    assert get_theme("10").name == "Terminal"

    # Lookup by name (case-insensitive)
    assert get_theme("classic").id == 1
    assert get_theme("OCEAN").id == 2
    assert get_theme("mAtRiX").id == 3
    assert get_theme("dracula").id == 6
    assert get_theme("Cyberpunk").id == 7
    assert get_theme("royal").id == 9


def test_invalid_theme_lookup():
    """Verifies that invalid theme IDs or names return None and do not raise exceptions."""
    assert get_theme(0) is None
    assert get_theme(11) is None
    assert get_theme(99) is None
    assert get_theme(-1) is None
    assert get_theme("0") is None
    assert get_theme("11") is None
    assert get_theme("nonexistent") is None
    assert get_theme("abc") is None
    assert get_theme("") is None


def test_set_active_theme_by_id_and_name(tmp_path: Path, monkeypatch):
    """Verifies setting the active theme by numerical ID or name."""
    # Mock config directory
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: tmp_path)

    # Set by ID
    t3 = set_active_theme(3, persist=True)
    assert t3 is not None
    assert t3.name == "Matrix"
    assert get_active_theme().name == "Matrix"

    # Verify config saved
    cfg = load_config()
    assert cfg.get("theme") == "Matrix"

    # Set by name
    t6 = set_active_theme("dracula", persist=True)
    assert t6 is not None
    assert t6.name == "Dracula"
    assert get_active_theme().name == "Dracula"
    assert load_config().get("theme") == "Dracula"

    # Invalid ID returns None and leaves active theme unchanged
    inv = set_active_theme(15, persist=True)
    assert inv is None
    assert get_active_theme().name == "Dracula"


def test_set_random_theme_avoids_current(tmp_path: Path, monkeypatch):
    """Verifies that /theme random chooses a different theme when >= 2 themes exist."""
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: tmp_path)

    set_active_theme(1, persist=False)  # Classic
    assert get_active_theme().id == 1

    # Run multiple random selections and verify current is never picked
    for _ in range(25):
        prev_theme, new_theme = set_random_theme(persist=False)
        assert prev_theme.id != new_theme.id
        assert get_active_theme().id == new_theme.id


def test_theme_semantic_styling():
    """Verifies all semantic methods apply appropriate ANSI styling."""
    init_colors(True)
    theme = get_theme("Dracula")
    assert theme is not None

    text = "Hello NetMash"
    assert "Hello NetMash" in theme.primary(text)
    assert "Hello NetMash" in theme.secondary(text)
    assert "Hello NetMash" in theme.accent(text)
    assert "Hello NetMash" in theme.success(text)
    assert "Hello NetMash" in theme.warning(text)
    assert "Hello NetMash" in theme.error(text)
    assert "Hello NetMash" in theme.muted(text)
    assert "Hello NetMash" in theme.prompt(text)
    assert "Hello NetMash" in theme.message(text)
    assert "Hello NetMash" in theme.system(text)
    assert "Hello NetMash" in theme.border(text)
    assert "Hello NetMash" in theme.header(text)
    assert "Hello NetMash" in theme.bold(text)
    assert "Hello NetMash" in theme.dim(text)


def test_theme_plain_text_fallback_when_colors_disabled():
    """Verifies that semantic methods return clean plain text when colors are disabled."""
    init_colors(False)
    try:
        theme = get_theme("Matrix")
        text = "Cybersecurity"
        assert theme.primary(text) == text
        assert theme.accent(text) == text
        assert theme.error(text) == text
        assert theme.prompt(text) == text
        assert theme.border(text) == text
    finally:
        init_colors(True)


def test_load_and_save_saved_theme(tmp_path: Path, monkeypatch):
    """Tests loading theme preference from local config.json file and fallback to default."""
    monkeypatch.setattr("netmash.config.get_app_dir", lambda: tmp_path)

    # Initially empty config -> loads Classic
    t = load_saved_theme()
    assert t.name == "Classic"

    # Save Forest theme
    save_active_theme("Forest")
    t_loaded = load_saved_theme()
    assert t_loaded.name == "Forest"
    assert get_active_theme().name == "Forest"

    # Corrupt or invalid theme name in config -> falls back to Classic
    cfg = load_config()
    cfg["theme"] = "InvalidTheme123"
    save_config(cfg)

    t_fallback = load_saved_theme()
    assert t_fallback.name == "Classic"


def test_render_theme_list_output(capsys):
    """Verifies that render_theme_list prints all 10 themes and the active theme."""
    set_active_theme("Matrix", persist=False)
    render_theme_list()
    captured = capsys.readouterr().out

    assert "NETMASH THEMES" in captured
    assert "1. Classic" in captured
    assert "2. Ocean" in captured
    assert "3. Matrix" in captured
    assert "4. Sunset" in captured
    assert "5. Mono" in captured
    assert "6. Dracula" in captured
    assert "7. Cyberpunk" in captured
    assert "8. Forest" in captured
    assert "9. Royal" in captured
    assert "10. Terminal" in captured
    assert "Current: Matrix" in captured
    assert "Usage:" in captured
    assert "/theme 1-10" in captured
    assert "/theme random" in captured


def test_render_invalid_theme_output(capsys):
    """Verifies that render_invalid_theme prints error message and dynamic list."""
    render_invalid_theme()
    captured = capsys.readouterr().out

    assert "Invalid theme." in captured
    assert "Available themes:" in captured
    assert "1. Classic" in captured
    assert "10. Terminal" in captured
    assert "Use:" in captured
    assert "/theme 1-10" in captured
    assert "/theme random" in captured


def test_print_help_theme_alignment(capsys):
    """Verifies that print_help runs cleanly and includes all categories and /theme command."""
    from netmash.ui.terminal import print_help
    set_active_theme("Cyberpunk", persist=False)
    print_help()
    captured = capsys.readouterr().out

    assert "Interactive Commands" in captured
    assert "General" in captured
    assert "Groups" in captured
    assert "Communication" in captured
    assert "Presence & Notifications" in captured
    assert "Network & Diagnostics" in captured
    assert "Application" in captured
    assert "/theme [1-10|random]" in captured


def test_redraw_screen_renders_all_components(capsys):
    """Verifies that redraw_screen clears terminal, renders banner, header, identity, and notice in active theme."""
    from netmash.identity import NodeIdentity
    from netmash.client.client import NetMashClient
    from netmash.ui.terminal import redraw_screen

    identity = NodeIdentity(node_id="node-test-123", username="TestUser", hostname="laptop-test")
    client = NetMashClient(host="127.0.0.1", port=19000, identity=identity)
    client.server_info = {"host_name": "LAPTOP-TEST", "network_name": "NetMash"}
    client.current_room = "general"

    set_active_theme("Ocean", persist=False)
    redraw_screen(client=client, notice="✓ Theme set to Ocean.")
    captured = capsys.readouterr().out

    assert "NETMASH" in captured
    assert "Connect. Discover. Chat." in captured
    assert "GENERAL" in captured
    assert "LAPTOP-TEST" in captured
    assert "TestUser" in captured
    assert "Theme set to Ocean" in captured


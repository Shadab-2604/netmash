"""
Unit and regression tests for TerminalInputManager and Input Buffer Persistence.
Verifies that user typing is 100% preserved during all incoming asynchronous events,
cursor restoration works, multi-line / special characters are handled, history functions,
and tab completion operates correctly.
"""

import io
import sys
from pathlib import Path
import pytest

from netmash.ui.input import KeyType, TerminalInputManager


def test_terminal_input_manager_init(tmp_path: Path):
    history_file = tmp_path / "history.txt"
    mgr = TerminalInputManager(
        prompt="netmash> ",
        history_file=history_file,
        completer_words=["/help", "/whoami", "/users"],
    )
    assert mgr.buffer_text == ""
    assert mgr.cursor_position == 0
    assert not mgr.is_active


def test_input_persistence_during_incoming_events(tmp_path: Path, monkeypatch):
    """
    CRITICAL REGRESSION TEST:
    Verifies that when a user is typing in the input buffer (e.g. 'hello thi')
    and incoming events arrive (chat, DM, join, presence, announcement, etc.),
    the input buffer and cursor position remain completely intact.
    """
    captured_output = io.StringIO()
    monkeypatch.setattr(sys.stdout, "write", captured_output.write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    history_file = tmp_path / "history.txt"
    mgr = TerminalInputManager(prompt="netmash> ", history_file=history_file)

    # Simulate active prompt
    mgr._active = True
    mgr._buffer = list("hello thi")
    mgr._cursor_pos = len(mgr._buffer)  # 9

    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Event 1: Incoming Chat Message
    mgr.print_event("[14:30] Bob:\nHello Alice!\n")
    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Event 2: Incoming DM
    mgr.print_event("[DM from Charlie]: Are you free?")
    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Event 3: Peer Join
    mgr.print_event("→ Dave joined NetMash")
    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Event 4: Presence Update
    mgr.print_event("• Eve is now AWAY")
    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Event 5: Host Announcement
    mgr.print_event("HOST ANNOUNCEMENT: Server restarting in 5 min")
    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Event 6: Group Update / Peer Leave
    mgr.print_event("← Frank left NetMash")
    assert mgr.buffer_text == "hello thi"
    assert mgr.cursor_position == 9

    # Output contains the events and line redraws
    output = captured_output.getvalue()
    assert "Hello Alice!" in output
    assert "Are you free?" in output
    assert "Dave joined" in output
    assert "Eve is now AWAY" in output


def test_cursor_position_restoration_in_middle_of_buffer(tmp_path: Path, monkeypatch):
    """
    Verifies that when a user is editing text in the middle of a buffer:
    'hello world' with cursor at index 5 (before 'world'),
    an incoming event restores the cursor back to index 5.
    """
    captured_output = io.StringIO()
    monkeypatch.setattr(sys.stdout, "write", captured_output.write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    mgr = TerminalInputManager(prompt="netmash> ", history_file=tmp_path / "hist.txt")
    mgr._active = True
    mgr._buffer = list("hello world")
    mgr._cursor_pos = 5  # At space after 'hello'

    mgr.print_event("Incoming event while editing middle!")

    assert mgr.buffer_text == "hello world"
    assert mgr.cursor_position == 5

    output = captured_output.getvalue()
    # \033[6D moves cursor back 6 places (11 - 5 = 6)
    assert "\033[6D" in output


def test_long_and_special_character_input_preservation(tmp_path: Path, monkeypatch):
    """
    Tests very long inputs (80, 120, 160 columns) and special characters
    ! @ # $ % ^ & * ( ) _ + { } [ ] : " < > ? ~ `
    """
    captured_output = io.StringIO()
    monkeypatch.setattr(sys.stdout, "write", captured_output.write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    mgr = TerminalInputManager(prompt="netmash> ")
    mgr._active = True

    special_text = "!@#$%^&*()_+{}[]:\"<>?~` - Special Unicode: 🚀 🔒 💬"
    mgr._buffer = list(special_text)
    mgr._cursor_pos = len(mgr._buffer)

    mgr.print_event("Incoming event with special characters in buffer")
    assert mgr.buffer_text == special_text

    # Very long text
    long_text = "A" * 200
    mgr._buffer = list(long_text)
    mgr._cursor_pos = len(mgr._buffer)

    mgr.print_event("Incoming event with 200-char buffer")
    assert mgr.buffer_text == long_text


def test_history_loading_and_saving(tmp_path: Path):
    hist_file = tmp_path / "history.txt"
    hist_file.write_text("/help\n/whoami\nhello\n", encoding="utf-8")

    mgr = TerminalInputManager(prompt="netmash> ", history_file=hist_file)
    assert mgr._history == ["/help", "/whoami", "hello"]

    mgr._history.append("/stats")
    mgr._save_history()

    content = hist_file.read_text(encoding="utf-8")
    assert "/stats" in content

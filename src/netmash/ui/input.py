"""
Async Terminal Input and Event Rendering Manager for NetMash.
Provides robust separation between active user input buffer and asynchronous event output,
guaranteeing that partially typed input is never lost, overwritten, or corrupted when
peers send messages, join/leave, change presence, or when any system notification arrives.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


class KeyType(Enum):
    CHAR = auto()
    ENTER = auto()
    BACKSPACE = auto()
    DELETE = auto()
    LEFT = auto()
    RIGHT = auto()
    HOME = auto()
    END = auto()
    UP = auto()
    DOWN = auto()
    TAB = auto()
    CTRL_C = auto()
    CTRL_D = auto()
    IGNORE = auto()


class TerminalInputManager:
    """
    Central Terminal Renderer and Input Manager.
    
    Maintains an independent input state (buffer, cursor position, history)
    and synchronizes terminal rendering so that asynchronous background events
    can safely clear the prompt line, render the incoming event, and restore
    the prompt line and cursor position without destroying user input.

    Supports dynamic prompt callbacks so that prompts immediately and automatically
    reflect the active group/room state (e.g. netmash>developers>).
    """

    def __init__(
        self,
        prompt: Union[str, Callable[[], str]] = "netmash> ",
        history_file: Optional[Path] = None,
        completer_words: Optional[List[str]] = None,
    ) -> None:
        self._prompt: Union[str, Callable[[], str]] = prompt
        self._active_prompt_override: Optional[Union[str, Callable[[], str]]] = None
        self._buffer: List[str] = []
        self._cursor_pos: int = 0
        self._active: bool = False
        self._lock: threading.Lock = threading.Lock()
        self._history_file: Optional[Path] = history_file
        self._history: List[str] = []
        self._history_idx: int = 0
        self._completer_words: List[str] = completer_words or []
        self._temp_saved_line: str = ""
        self._is_password: bool = False
        self._mask: Optional[str] = None

        self._load_history()

    def _load_history(self) -> None:
        """Loads input history from file if available."""
        if self._history_file and self._history_file.exists():
            try:
                with open(self._history_file, "r", encoding="utf-8") as f:
                    lines = [line.rstrip("\r\n") for line in f if line.strip()]
                    self._history = lines[-500:]
            except Exception:
                self._history = []

    def _save_history(self) -> None:
        """Saves input history to file."""
        if self._history_file:
            try:
                with open(self._history_file, "w", encoding="utf-8") as f:
                    for item in self._history[-500:]:
                        f.write(item + "\n")
            except Exception:
                pass

    @property
    def prompt_text(self) -> str:
        """
        Returns the evaluated active prompt string.
        If prompt is a callable, it dynamically evaluates the function in real-time
        to reflect the currently active group/room state.
        """
        with self._lock:
            p = (
                self._active_prompt_override
                if self._active_prompt_override is not None
                else self._prompt
            )
            if callable(p):
                try:
                    return str(p())
                except Exception:
                    return "netmash> "
            return str(p)

    def set_prompt(self, prompt: Union[str, Callable[[], str]]) -> None:
        """Updates the active prompt string or callable."""
        with self._lock:
            self._prompt = prompt
            if self._active:
                self._raw_redraw()

    @property
    def buffer_text(self) -> str:
        """Returns the current partially typed buffer as a string."""
        with self._lock:
            return "".join(self._buffer)

    @property
    def cursor_position(self) -> int:
        """Returns the current cursor index within the buffer."""
        with self._lock:
            return self._cursor_pos

    @property
    def is_active(self) -> bool:
        """Returns True if the input manager is currently prompting the user."""
        return self._active

    def _raw_redraw(self) -> None:
        """
        Internal redraw logic without acquiring lock (assumes caller holds _lock).
        Algorithm:
          1. Return carriage to column 0 and erase line (\\r\\033[2K).
          2. Output evaluated dynamic prompt string and current input buffer text.
          3. Restore cursor position if cursor is not at the end (\\033[<N>D).
          4. Flush stdout.
        """
        # Read evaluated dynamic prompt (e.g. netmash>developers> )
        p = (
            self._active_prompt_override
            if self._active_prompt_override is not None
            else self._prompt
        )
        if callable(p):
            try:
                prompt_str = str(p())
            except Exception:
                prompt_str = "netmash> "
        else:
            prompt_str = str(p)

        if self._mask is not None:
            buf_str = self._mask * len(self._buffer)
        else:
            buf_str = "".join(self._buffer)
        sys.stdout.write(f"\r\033[2K{prompt_str}{buf_str}")
        
        # Calculate backward cursor movement
        offset_from_end = len(self._buffer) - self._cursor_pos
        if offset_from_end > 0:
            sys.stdout.write(f"\033[{offset_from_end}D")
            
        sys.stdout.flush()

    def redraw_input(self) -> None:
        """
        Explicitly triggers a re-render of the prompt, current buffer, and cursor.
        Used after full screen clears or dynamic theme updates.
        """
        with self._lock:
            if self._active:
                self._raw_redraw()
            else:
                p = self._prompt
                prompt_str = str(p()) if callable(p) else str(p)
                sys.stdout.write(f"\r\033[2K{prompt_str}")
                sys.stdout.flush()

    def print_event(self, text: str) -> None:
        """
        Safely renders an incoming asynchronous event.
        
        If the user is currently typing:
          1. Clears the active prompt line.
          2. Prints the incoming event text (with trailing newline).
          3. Re-renders the prompt and exact input buffer.
          4. Restores the exact cursor position.
        """
        with self._lock:
            if not text.endswith("\n"):
                text = text + "\n"

            if not self._active:
                sys.stdout.write(text)
                sys.stdout.flush()
                return

            # Clear current input line
            sys.stdout.write("\r\033[2K")
            # Write incoming event
            sys.stdout.write(text)
            # Re-render active prompt and restored input buffer
            self._raw_redraw()

    def write_line(self, line: str) -> None:
        """Alias for print_event."""
        self.print_event(line)

    def _read_key_windows(self) -> tuple[KeyType, str]:
        """Reads a single keypress on Windows using msvcrt."""
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            # Special/extended key prefix
            ch2 = msvcrt.getwch()
            if ch2 in ("H", "\x48"):
                return KeyType.UP, ""
            elif ch2 in ("P", "\x50"):
                return KeyType.DOWN, ""
            elif ch2 in ("K", "\x4b"):
                return KeyType.LEFT, ""
            elif ch2 in ("M", "\x4d"):
                return KeyType.RIGHT, ""
            elif ch2 in ("G", "\x47"):
                return KeyType.HOME, ""
            elif ch2 in ("O", "\x4f"):
                return KeyType.END, ""
            elif ch2 in ("S", "\x53"):
                return KeyType.DELETE, ""
            return KeyType.IGNORE, ""

        if ch in ("\r", "\n"):
            return KeyType.ENTER, ""
        elif ch in ("\x08", "\x7f"):
            return KeyType.BACKSPACE, ""
        elif ch == "\t":
            return KeyType.TAB, ""
        elif ch == "\x03":
            return KeyType.CTRL_C, ""
        elif ch == "\x04":
            return KeyType.CTRL_D, ""
        elif ord(ch) >= 32:
            return KeyType.CHAR, ch
        return KeyType.IGNORE, ""

    def _read_key_posix(self) -> tuple[KeyType, str]:
        """Reads a single keypress on POSIX using termios and raw mode."""
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Escape sequence
                seq = sys.stdin.read(2)
                if seq == "[A":
                    return KeyType.UP, ""
                elif seq == "[B":
                    return KeyType.DOWN, ""
                elif seq == "[C":
                    return KeyType.RIGHT, ""
                elif seq == "[D":
                    return KeyType.LEFT, ""
                elif seq == "[H" or seq == "OH":
                    return KeyType.HOME, ""
                elif seq == "[F" or seq == "OF":
                    return KeyType.END, ""
                elif seq == "[3":
                    # Delete key sequence e.g. \x1b[3~
                    _ = sys.stdin.read(1)
                    return KeyType.DELETE, ""
                return KeyType.IGNORE, ""
            elif ch in ("\r", "\n"):
                return KeyType.ENTER, ""
            elif ch in ("\x08", "\x7f"):
                return KeyType.BACKSPACE, ""
            elif ch == "\t":
                return KeyType.TAB, ""
            elif ch == "\x03":
                return KeyType.CTRL_C, ""
            elif ch == "\x04":
                return KeyType.CTRL_D, ""
            elif ord(ch) >= 32:
                return KeyType.CHAR, ch
            return KeyType.IGNORE, ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _read_next_key(self) -> tuple[KeyType, str]:
        """Platform-agnostic key reading dispatch."""
        if sys.platform == "win32":
            return self._read_key_windows()
        else:
            return self._read_key_posix()

    async def get_line(
        self,
        prompt: Optional[Union[str, Callable[[], str]]] = None,
        is_password: bool = False,
        mask: Optional[str] = "*",
    ) -> str:
        """
        Asynchronously captures a complete line of input from the user.
        Maintains real-time buffer state, supports arrow keys, backspace, delete,
        history navigation, and tab completion.
        If is_password is True, input characters are masked and not persisted to history.
        """
        # Check if stdin is an interactive TTY
        is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()

        with self._lock:
            self._active_prompt_override = prompt
            self._is_password = is_password
            self._mask = mask if is_password else None
            self._buffer = []
            self._cursor_pos = 0
            self._history_idx = len(self._history)
            self._temp_saved_line = ""
            self._active = True
            if is_tty:
                self._raw_redraw()
            else:
                sys.stdout.write(self.prompt_text)
                sys.stdout.flush()

        # Non-TTY fallback (for tests, pipes, automated scripts)
        if not is_tty:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    raise EOFError()
                line = line.rstrip("\r\n")
                if line and not is_password:
                    self._history.append(line)
                    self._save_history()
                return line
            finally:
                with self._lock:
                    self._active = False
                    self._active_prompt_override = None
                    self._is_password = False
                    self._mask = None

        # Interactive TTY loop
        try:
            while True:
                key_type, val = await asyncio.to_thread(self._read_next_key)

                with self._lock:
                    if key_type == KeyType.CHAR:
                        self._buffer.insert(self._cursor_pos, val)
                        self._cursor_pos += 1
                        self._raw_redraw()

                    elif key_type == KeyType.ENTER:
                        result = "".join(self._buffer)
                        # Move to fresh line
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        if result.strip() and not is_password:
                            self._history.append(result)
                            self._save_history()
                        self._buffer = []
                        self._cursor_pos = 0
                        return result

                    elif key_type == KeyType.BACKSPACE:
                        if self._cursor_pos > 0:
                            self._buffer.pop(self._cursor_pos - 1)
                            self._cursor_pos -= 1
                            self._raw_redraw()

                    elif key_type == KeyType.DELETE:
                        if self._cursor_pos < len(self._buffer):
                            self._buffer.pop(self._cursor_pos)
                            self._raw_redraw()

                    elif key_type == KeyType.LEFT:
                        if self._cursor_pos > 0:
                            self._cursor_pos -= 1
                            self._raw_redraw()

                    elif key_type == KeyType.RIGHT:
                        if self._cursor_pos < len(self._buffer):
                            self._cursor_pos += 1
                            self._raw_redraw()

                    elif key_type == KeyType.HOME:
                        self._cursor_pos = 0
                        self._raw_redraw()

                    elif key_type == KeyType.END:
                        self._cursor_pos = len(self._buffer)
                        self._raw_redraw()

                    elif key_type == KeyType.UP:
                        if self._history and self._history_idx > 0:
                            if self._history_idx == len(self._history):
                                self._temp_saved_line = "".join(self._buffer)
                            self._history_idx -= 1
                            hist_item = self._history[self._history_idx]
                            self._buffer = list(hist_item)
                            self._cursor_pos = len(self._buffer)
                            self._raw_redraw()

                    elif key_type == KeyType.DOWN:
                        if self._history and self._history_idx < len(self._history):
                            self._history_idx += 1
                            if self._history_idx == len(self._history):
                                self._buffer = list(self._temp_saved_line)
                            else:
                                hist_item = self._history[self._history_idx]
                                self._buffer = list(hist_item)
                            self._cursor_pos = len(self._buffer)
                            self._raw_redraw()

                    elif key_type == KeyType.TAB:
                        current_str = "".join(self._buffer[: self._cursor_pos])
                        if current_str.startswith("/"):
                            matches = [
                                w for w in self._completer_words if w.startswith(current_str)
                            ]
                            if len(matches) == 1:
                                completed = matches[0]
                                self._buffer = list(completed)
                                self._cursor_pos = len(self._buffer)
                                self._raw_redraw()
                            elif len(matches) > 1:
                                # Find common prefix
                                prefix = os.path.commonprefix(matches)
                                if len(prefix) > len(current_str):
                                    self._buffer = list(prefix)
                                    self._cursor_pos = len(self._buffer)
                                    self._raw_redraw()

                    elif key_type == KeyType.CTRL_C:
                        self._buffer = []
                        self._cursor_pos = 0
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        raise KeyboardInterrupt()

                    elif key_type == KeyType.CTRL_D:
                        if not self._buffer:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            raise EOFError()

        finally:
            with self._lock:
                self._active = False
                self._active_prompt_override = None

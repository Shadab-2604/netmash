"""
Terminal color management for NetMash.
Provides color palettes, bold/dim styling, and automatic detection
of NO_COLOR environment variable and --no-color flag.
"""

from __future__ import annotations

import os
import sys

_COLOR_ENABLED = True


def init_colors(enable: bool = True) -> None:
    """Initializes color settings. Checks NO_COLOR environment variable and configures UTF-8 encoding."""
    global _COLOR_ENABLED

    # Ensure UTF-8 output encoding on Windows consoles
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not enable or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        _COLOR_ENABLED = False
    else:
        _COLOR_ENABLED = True
        # Enable ANSI colors in Windows CMD/Terminal if possible
        if sys.platform == "win32":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                pass


def is_color_enabled() -> bool:
    return _COLOR_ENABLED


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Palette
    CYAN = "\033[36m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"

    # Bright variants
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_GREEN = "\033[92m"


def cyan(text: str) -> str:
    return f"{Colors.CYAN}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def blue(text: str) -> str:
    return f"{Colors.BLUE}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def green(text: str) -> str:
    return f"{Colors.GREEN}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def yellow(text: str) -> str:
    return f"{Colors.YELLOW}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def red(text: str) -> str:
    return f"{Colors.RED}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def gray(text: str) -> str:
    return f"{Colors.GRAY}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def bold(text: str) -> str:
    return f"{Colors.BOLD}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def dim(text: str) -> str:
    return f"{Colors.DIM}{text}{Colors.RESET}" if _COLOR_ENABLED else text


def bright_cyan(text: str) -> str:
    return f"{Colors.BRIGHT_CYAN}{text}{Colors.RESET}" if _COLOR_ENABLED else text

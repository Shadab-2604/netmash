"""
Centralized Theme Registry and Semantic Styling Engine for NetMash.
Provides 10 built-in themes with semantic style mappings, persistent local client
preferences, random theme selection, and fallback support for non-ANSI terminals.
"""

from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from netmash.config import load_config, save_config

# Global color detection state
_COLOR_ENABLED: bool = True


def init_colors(enable: bool = True) -> None:
    """Initializes color settings. Checks NO_COLOR environment variable and Windows console UTF-8/ANSI."""
    global _COLOR_ENABLED

    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

    if not enable or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        _COLOR_ENABLED = False
    else:
        _COLOR_ENABLED = True


def is_color_enabled() -> bool:
    """Returns True if ANSI color output is enabled."""
    return _COLOR_ENABLED


# Standard ANSI Escape Codes
class ANSI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Standard Colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright Colors
    GRAY = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


@dataclass
class Theme:
    """
    Defines a NetMash semantic theme.
    Maps high-level UI semantic roles to concrete terminal ANSI codes.
    """

    id: int
    name: str
    style_desc: str
    primary_code: str = ANSI.CYAN
    secondary_code: str = ANSI.BLUE
    accent_code: str = ANSI.BRIGHT_CYAN
    success_code: str = ANSI.GREEN
    warning_code: str = ANSI.YELLOW
    error_code: str = ANSI.RED
    muted_code: str = ANSI.GRAY
    prompt_code: str = ANSI.CYAN
    message_code: str = ANSI.WHITE
    system_code: str = ANSI.DIM
    border_code: str = ANSI.GRAY
    header_code: str = ANSI.CYAN

    def _apply(self, code: str, text: str) -> str:
        if not _COLOR_ENABLED or not code:
            return str(text)
        return f"{code}{text}{ANSI.RESET}"

    def primary(self, text: Any) -> str:
        return self._apply(self.primary_code, str(text))

    def secondary(self, text: Any) -> str:
        return self._apply(self.secondary_code, str(text))

    def accent(self, text: Any) -> str:
        return self._apply(self.accent_code, str(text))

    def success(self, text: Any) -> str:
        return self._apply(self.success_code, str(text))

    def warning(self, text: Any) -> str:
        return self._apply(self.warning_code, str(text))

    def error(self, text: Any) -> str:
        return self._apply(self.error_code, str(text))

    def muted(self, text: Any) -> str:
        return self._apply(self.muted_code, str(text))

    def prompt(self, text: Any) -> str:
        return self._apply(self.prompt_code, str(text))

    def message(self, text: Any) -> str:
        return self._apply(self.message_code, str(text))

    def system(self, text: Any) -> str:
        return self._apply(self.system_code, str(text))

    def border(self, text: Any) -> str:
        return self._apply(self.border_code, str(text))

    def header(self, text: Any) -> str:
        return self._apply(f"{ANSI.BOLD}{self.header_code}", str(text))

    def bold(self, text: Any) -> str:
        return self._apply(ANSI.BOLD, str(text))

    def dim(self, text: Any) -> str:
        return self._apply(ANSI.DIM, str(text))


# ============================================================================
# Centralized 10 Built-in Theme Registry
# ============================================================================

THEMES: List[Theme] = [
    # 1. Classic: Clean, professional terminal (Safest default)
    Theme(
        id=1,
        name="Classic",
        style_desc="Professional / Balanced",
        primary_code=ANSI.CYAN,
        secondary_code=ANSI.BLUE,
        accent_code=ANSI.BRIGHT_CYAN,
        success_code=ANSI.GREEN,
        warning_code=ANSI.YELLOW,
        error_code=ANSI.RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.CYAN,
        message_code=ANSI.WHITE,
        system_code=ANSI.DIM,
        border_code=ANSI.GRAY,
        header_code=ANSI.CYAN,
    ),
    # 2. Ocean: Cool blue/cyan terminal
    Theme(
        id=2,
        name="Ocean",
        style_desc="Blue / Cyan",
        primary_code=ANSI.BRIGHT_BLUE,
        secondary_code=ANSI.CYAN,
        accent_code=ANSI.BRIGHT_CYAN,
        success_code=ANSI.CYAN,
        warning_code=ANSI.YELLOW,
        error_code=ANSI.BRIGHT_RED,
        muted_code=ANSI.BLUE,
        prompt_code=ANSI.BRIGHT_CYAN,
        message_code=ANSI.BRIGHT_WHITE,
        system_code=ANSI.CYAN,
        border_code=ANSI.BLUE,
        header_code=ANSI.BRIGHT_BLUE,
    ),
    # 3. Matrix: Cybersecurity-inspired terminal
    Theme(
        id=3,
        name="Matrix",
        style_desc="Green / Dark",
        primary_code=ANSI.BRIGHT_GREEN,
        secondary_code=ANSI.GREEN,
        accent_code=ANSI.BRIGHT_GREEN,
        success_code=ANSI.BRIGHT_GREEN,
        warning_code=ANSI.YELLOW,
        error_code=ANSI.RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.BRIGHT_GREEN,
        message_code=ANSI.GREEN,
        system_code=ANSI.GREEN,
        border_code=ANSI.GREEN,
        header_code=ANSI.BRIGHT_GREEN,
    ),
    # 4. Sunset: Warm orange/red terminal
    Theme(
        id=4,
        name="Sunset",
        style_desc="Orange / Red",
        primary_code=ANSI.YELLOW,
        secondary_code=ANSI.MAGENTA,
        accent_code=ANSI.BRIGHT_RED,
        success_code=ANSI.BRIGHT_GREEN,
        warning_code=ANSI.BRIGHT_YELLOW,
        error_code=ANSI.RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.YELLOW,
        message_code=ANSI.WHITE,
        system_code=ANSI.MAGENTA,
        border_code=ANSI.YELLOW,
        header_code=ANSI.BRIGHT_RED,
    ),
    # 5. Mono: Minimal monochrome terminal
    Theme(
        id=5,
        name="Mono",
        style_desc="White / Gray",
        primary_code=ANSI.WHITE,
        secondary_code=ANSI.GRAY,
        accent_code=ANSI.BRIGHT_WHITE,
        success_code=ANSI.WHITE,
        warning_code=ANSI.WHITE,
        error_code=ANSI.BRIGHT_WHITE,
        muted_code=ANSI.DIM,
        prompt_code=ANSI.WHITE,
        message_code=ANSI.WHITE,
        system_code=ANSI.GRAY,
        border_code=ANSI.GRAY,
        header_code=ANSI.BRIGHT_WHITE,
    ),
    # 6. Dracula: Dark developer-oriented theme
    Theme(
        id=6,
        name="Dracula",
        style_desc="Dark / Purple / Pink accents",
        primary_code=ANSI.MAGENTA,
        secondary_code=ANSI.CYAN,
        accent_code=ANSI.BRIGHT_MAGENTA,
        success_code=ANSI.BRIGHT_GREEN,
        warning_code=ANSI.YELLOW,
        error_code=ANSI.BRIGHT_RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.BRIGHT_MAGENTA,
        message_code=ANSI.WHITE,
        system_code=ANSI.MAGENTA,
        border_code=ANSI.MAGENTA,
        header_code=ANSI.BRIGHT_MAGENTA,
    ),
    # 7. Cyberpunk: Futuristic dark neon terminal
    Theme(
        id=7,
        name="Cyberpunk",
        style_desc="Dark / Neon accents",
        primary_code=ANSI.BRIGHT_YELLOW,
        secondary_code=ANSI.BRIGHT_CYAN,
        accent_code=ANSI.BRIGHT_MAGENTA,
        success_code=ANSI.BRIGHT_GREEN,
        warning_code=ANSI.BRIGHT_YELLOW,
        error_code=ANSI.BRIGHT_RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.BRIGHT_CYAN,
        message_code=ANSI.BRIGHT_WHITE,
        system_code=ANSI.BRIGHT_MAGENTA,
        border_code=ANSI.BRIGHT_YELLOW,
        header_code=ANSI.BRIGHT_CYAN,
    ),
    # 8. Forest: Natural dark green theme
    Theme(
        id=8,
        name="Forest",
        style_desc="Green / Dark",
        primary_code=ANSI.GREEN,
        secondary_code=ANSI.YELLOW,
        accent_code=ANSI.BRIGHT_GREEN,
        success_code=ANSI.BRIGHT_GREEN,
        warning_code=ANSI.YELLOW,
        error_code=ANSI.RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.GREEN,
        message_code=ANSI.WHITE,
        system_code=ANSI.GREEN,
        border_code=ANSI.GREEN,
        header_code=ANSI.BRIGHT_GREEN,
    ),
    # 9. Royal: Deep blue / Gold accents
    Theme(
        id=9,
        name="Royal",
        style_desc="Deep blue / Gold accents",
        primary_code=ANSI.BLUE,
        secondary_code=ANSI.YELLOW,
        accent_code=ANSI.BRIGHT_YELLOW,
        success_code=ANSI.GREEN,
        warning_code=ANSI.BRIGHT_YELLOW,
        error_code=ANSI.RED,
        muted_code=ANSI.GRAY,
        prompt_code=ANSI.BRIGHT_YELLOW,
        message_code=ANSI.WHITE,
        system_code=ANSI.BLUE,
        border_code=ANSI.YELLOW,
        header_code=ANSI.BRIGHT_YELLOW,
    ),
    # 10. Terminal: Old-school hacker/Unix terminal
    Theme(
        id=10,
        name="Terminal",
        style_desc="Black / Green",
        primary_code=ANSI.GREEN,
        secondary_code=ANSI.BRIGHT_GREEN,
        accent_code=ANSI.BRIGHT_GREEN,
        success_code=ANSI.BRIGHT_GREEN,
        warning_code=ANSI.YELLOW,
        error_code=ANSI.RED,
        muted_code=ANSI.DIM,
        prompt_code=ANSI.BRIGHT_GREEN,
        message_code=ANSI.GREEN,
        system_code=ANSI.GREEN,
        border_code=ANSI.GREEN,
        header_code=ANSI.BRIGHT_GREEN,
    ),
]

# Quick lookup mappings
THEME_BY_ID: Dict[int, Theme] = {t.id: t for t in THEMES}
THEME_BY_NAME: Dict[str, Theme] = {t.name.lower(): t for t in THEMES}

# Active runtime theme (defaults to Classic)
_ACTIVE_THEME: Theme = THEMES[0]


def get_all_themes() -> List[Theme]:
    """Returns list of all registered themes."""
    return list(THEMES)


def get_theme_count() -> int:
    """Returns total count of registered themes."""
    return len(THEMES)


def get_theme(identifier: Union[int, str]) -> Optional[Theme]:
    """
    Finds a theme by numerical ID (1-N) or case-insensitive name.
    Returns None if not found.
    """
    if isinstance(identifier, int):
        return THEME_BY_ID.get(identifier)

    str_val = str(identifier).strip()
    if str_val.isdigit():
        return THEME_BY_ID.get(int(str_val))

    return THEME_BY_NAME.get(str_val.lower())


def get_active_theme() -> Theme:
    """Returns currently active theme."""
    global _ACTIVE_THEME
    return _ACTIVE_THEME


def set_active_theme(identifier: Union[int, str], persist: bool = True) -> Optional[Theme]:
    """
    Sets the active theme by numerical ID or name and optionally saves to config.json.
    Returns the newly activated Theme or None if invalid.
    """
    global _ACTIVE_THEME
    theme = get_theme(identifier)
    if theme:
        _ACTIVE_THEME = theme
        if persist:
            save_active_theme(theme.name)
        return theme
    return None


def set_random_theme(persist: bool = True) -> Tuple[Theme, Theme]:
    """
    Selects a random theme from the registry, avoiding the currently active theme if >= 2 themes exist.
    Returns (previous_theme, new_theme).
    """
    global _ACTIVE_THEME
    prev_theme = _ACTIVE_THEME
    candidates = [t for t in THEMES if t.id != prev_theme.id] or THEMES
    new_theme = random.choice(candidates)
    _ACTIVE_THEME = new_theme
    if persist:
        save_active_theme(new_theme.name)
    return prev_theme, new_theme


def load_saved_theme() -> Theme:
    """
    Loads saved theme preference from local config.json, or defaults to Classic.
    """
    global _ACTIVE_THEME
    cfg = load_config()
    saved_name = cfg.get("theme")
    if saved_name:
        theme = get_theme(saved_name)
        if theme:
            _ACTIVE_THEME = theme
            return _ACTIVE_THEME
    _ACTIVE_THEME = THEMES[0]
    return _ACTIVE_THEME


def save_active_theme(theme_name_or_id: Union[int, str]) -> None:
    """
    Saves theme preference to local config.json.
    """
    theme = get_theme(theme_name_or_id)
    if not theme:
        return
    cfg = load_config()
    cfg["theme"] = theme.name
    save_config(cfg)


# ============================================================================
# Semantic Formatter Shortcuts (Proxied to Active Theme)
# ============================================================================

def primary(text: Any) -> str:
    return _ACTIVE_THEME.primary(text)


def secondary(text: Any) -> str:
    return _ACTIVE_THEME.secondary(text)


def accent(text: Any) -> str:
    return _ACTIVE_THEME.accent(text)


def success(text: Any) -> str:
    return _ACTIVE_THEME.success(text)


def warning(text: Any) -> str:
    return _ACTIVE_THEME.warning(text)


def error(text: Any) -> str:
    return _ACTIVE_THEME.error(text)


def muted(text: Any) -> str:
    return _ACTIVE_THEME.muted(text)


def prompt(text: Any) -> str:
    return _ACTIVE_THEME.prompt(text)


def message(text: Any) -> str:
    return _ACTIVE_THEME.message(text)


def system(text: Any) -> str:
    return _ACTIVE_THEME.system(text)


def border(text: Any) -> str:
    return _ACTIVE_THEME.border(text)


def header(text: Any) -> str:
    return _ACTIVE_THEME.header(text)


def bold(text: Any) -> str:
    return _ACTIVE_THEME.bold(text)


def dim(text: Any) -> str:
    return _ACTIVE_THEME.dim(text)

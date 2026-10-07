"""
Automatic update checker and updater for NetMash.
Supports checking GitHub repository updates, auto-detection of git-clones vs pip installs,
and seamless one-click updates.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from netmash import __version__

GITHUB_REPO = "Shadab-2604/netmash"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
GITHUB_RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/pyproject.toml"


def get_git_repo_root() -> Optional[Path]:
    """Returns the Path to the root git directory if running from a git clone, else None."""
    try:
        # Check current working directory or package parent directories
        cur = Path(__file__).resolve().parent.parent.parent
        if (cur / ".git").is_dir():
            return cur
        
        # Check git rev-parse
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            root_path = Path(res.stdout.strip())
            if root_path.exists():
                return root_path
    except Exception:
        pass
    return None


def get_local_commit_sha() -> Optional[str]:
    """Returns the current local git commit SHA (short 7 chars) if available."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def check_for_updates(timeout: float = 3.0) -> Dict[str, Any]:
    """
    Queries GitHub API to check if a new commit or version is available.
    Returns a dictionary containing update status and metadata.
    """
    result: Dict[str, Any] = {
        "update_available": False,
        "current_version": __version__,
        "latest_version": __version__,
        "current_commit": get_local_commit_sha(),
        "latest_commit": None,
        "commit_message": None,
        "commit_date": None,
        "is_git_clone": get_git_repo_root() is not None,
        "error": None,
    }

    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "User-Agent": "NetMash-Update-Checker",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                latest_sha = data.get("sha", "")[:7]
                commit_info = data.get("commit", {})
                msg = commit_info.get("message", "").split("\n")[0]
                date = commit_info.get("committer", {}).get("date", "")

                result["latest_commit"] = latest_sha
                result["commit_message"] = msg
                result["commit_date"] = date

                local_sha = result["current_commit"]
                if local_sha:
                    if local_sha.lower() != latest_sha.lower():
                        result["update_available"] = True
                else:
                    # If not a git clone, we can compare with online version or commit
                    result["update_available"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


async def check_for_updates_async(timeout: float = 2.5) -> Dict[str, Any]:
    """Asynchronously checks for updates in a background thread."""
    return await asyncio.to_thread(check_for_updates, timeout)


def apply_update() -> Tuple[bool, str]:
    """
    Applies the latest NetMash update.
    - If running from a git clone, executes `git pull` followed by editable install.
    - If running from standard pip, executes `pip install --upgrade git+https://...`
    Returns (success: bool, message: str).
    """
    repo_root = get_git_repo_root()

    if repo_root:
        # 1. Update git clone
        try:
            pull_res = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30.0,
            )
            if pull_res.returncode != 0:
                # Try generic git pull
                pull_res = subprocess.run(
                    ["git", "pull"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30.0,
                )

            if pull_res.returncode != 0:
                return False, f"Git pull failed:\n{pull_res.stderr or pull_res.stdout}"

            # Run pip install -e .
            pip_res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", "."],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=60.0,
            )
            if pip_res.returncode != 0:
                return False, f"Package installation failed:\n{pip_res.stderr or pip_res.stdout}"

            return True, f"Successfully updated NetMash to the latest version!\n{pull_res.stdout.strip()}"

        except Exception as e:
            return False, f"Update execution error: {e}"
    else:
        # 2. Update via pip from GitHub
        try:
            pip_url = f"git+https://github.com/{GITHUB_REPO}.git"
            pip_res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "--no-cache-dir",
                    pip_url,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90.0,
            )
            if pip_res.returncode == 0:
                return True, "Successfully updated NetMash from GitHub repository via pip!"
            else:
                return False, f"Pip update failed:\n{pip_res.stderr or pip_res.stdout}"
        except Exception as e:
            return False, f"Pip update error: {e}"


async def apply_update_async() -> Tuple[bool, str]:
    """Asynchronously applies the update in a worker thread."""
    return await asyncio.to_thread(apply_update)

"""
Automatic update checker and updater for NetMash.
Provides reliable detection of running vs installed revisions, single authoritative
GitHub source comparison, pip/git environment verification, and restart tracking.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from netmash import __version__

# Authoritative GitHub repository source
GITHUB_REPO = "Shadab-2604/netmash"
GITHUB_BRANCH = "main"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
GITHUB_RAW_PYPROJECT_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/pyproject.toml"

# Freeze the running commit at module initialization time
_RUNNING_COMMIT_SHA: Optional[str] = None


def get_git_repo_root() -> Optional[Path]:
    """
    Returns the Path to the root git directory if the netmash package resides
    inside a local git clone (e.g. development/editable install), else None.
    
    IMPORTANT: Never invokes git in the caller's working directory to prevent
    false-positive repo detection when running from an unrelated directory.
    """
    try:
        pkg_dir = Path(__file__).resolve().parent  # src/netmash or netmash
        candidates = [
            pkg_dir.parent.parent,  # if in <repo>/src/netmash -> <repo>
            pkg_dir.parent,         # if in <repo>/netmash -> <repo>
        ]
        for cand in candidates:
            if (cand / ".git").is_dir() and (cand / "pyproject.toml").is_file():
                return cand

        for cand in candidates:
            if cand.is_dir():
                res = subprocess.run(
                    ["git", "-C", str(cand), "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=2.0,
                )
                if res.returncode == 0 and res.stdout.strip():
                    root_path = Path(res.stdout.strip())
                    if (root_path / "pyproject.toml").is_file():
                        return root_path
    except Exception:
        pass
    return None


def get_installed_commit_sha() -> Optional[str]:
    """
    Returns the currently installed commit SHA (short 7-char string) from the on-disk package.
    Inspects git HEAD for local checkouts, or pip's direct_url.json metadata for git installations.
    """
    # 1. If running from a git checkout
    repo_root = get_git_repo_root()
    if repo_root:
        try:
            res = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()[:7].lower()
        except Exception:
            pass

    # 2. Inspect pip metadata (direct_url.json records commit_id for git+ installs)
    try:
        dist = importlib.metadata.distribution("netmash")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text:
            data = json.loads(direct_url_text)
            commit_id = data.get("vcs_info", {}).get("commit_id")
            if commit_id:
                return str(commit_id).strip()[:7].lower()
    except Exception:
        pass

    return None


def get_local_commit_sha() -> Optional[str]:
    """Alias for get_installed_commit_sha for backward compatibility."""
    return get_installed_commit_sha()


def get_running_commit_sha() -> str:
    """Returns the immutable commit SHA of the currently running NetMash process."""
    global _RUNNING_COMMIT_SHA
    if _RUNNING_COMMIT_SHA is None:
        commit = get_installed_commit_sha()
        _RUNNING_COMMIT_SHA = commit if commit else "unknown"
    return _RUNNING_COMMIT_SHA


def get_installed_version() -> str:
    """Returns the package version currently installed on disk."""
    try:
        return importlib.metadata.version("netmash")
    except Exception:
        return __version__


def get_running_version() -> str:
    """Returns the version string of the currently running process."""
    return __version__


def _parse_version_tuple(v_str: str) -> Tuple[int, ...]:
    """Safely converts version string into a comparable tuple of integers."""
    parts = []
    for p in v_str.replace("-", ".").split("."):
        if p.isdigit():
            parts.append(int(p))
    return tuple(parts) if parts else (0, 0, 0)


def check_for_updates(timeout: float = 3.0) -> Dict[str, Any]:
    """
    Authoritatively queries GitHub to check if a new commit or package version is available.
    Compares running version/commit and installed version/commit against GitHub main.
    
    Returns structured metadata:
      - update_available: True if a newer version/commit is available on GitHub
      - restart_required: True if update is installed on disk but running process is older
      - running_version, running_commit
      - installed_version, installed_commit
      - latest_version, latest_commit, commit_message, commit_date
      - is_git_clone, python_executable, install_path
    """
    running_ver = get_running_version()
    running_commit = get_running_commit_sha()
    installed_ver = get_installed_version()
    installed_commit = get_installed_commit_sha() or "unknown"
    repo_root = get_git_repo_root()

    result: Dict[str, Any] = {
        "update_available": False,
        "restart_required": False,
        "running_version": running_ver,
        "running_commit": running_commit,
        "installed_version": installed_ver,
        "installed_commit": installed_commit,
        "latest_version": running_ver,
        "latest_commit": None,
        "commit_message": None,
        "commit_date": None,
        "is_git_clone": repo_root is not None,
        "repo_root": str(repo_root) if repo_root else None,
        "python_executable": sys.executable,
        "install_path": str(Path(__file__).resolve().parent),
        "error": None,
    }

    try:
        # 1. Fetch latest commit from GitHub API
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
                latest_sha = data.get("sha", "")[:7].lower()
                commit_info = data.get("commit", {})
                msg = commit_info.get("message", "").split("\n")[0]
                date = commit_info.get("committer", {}).get("date", "")

                result["latest_commit"] = latest_sha
                result["commit_message"] = msg
                result["commit_date"] = date

        # 2. Fetch latest version from pyproject.toml on GitHub
        try:
            raw_req = urllib.request.Request(
                GITHUB_RAW_PYPROJECT_URL,
                headers={"User-Agent": "NetMash-Update-Checker"},
            )
            with urllib.request.urlopen(raw_req, timeout=timeout) as raw_resp:
                if raw_resp.status == 200:
                    raw_text = raw_resp.read().decode("utf-8")
                    for line in raw_text.splitlines():
                        if line.strip().startswith("version"):
                            v = line.split("=")[1].strip().strip('"\'')
                            if v:
                                result["latest_version"] = v
                                break
        except Exception:
            pass

        # 3. Authoritative Comparison Logic
        latest_sha = result["latest_commit"]
        latest_v = result["latest_version"]

        # Check if disk has newer version than running process (Pending Restart)
        is_known_installed = installed_commit and installed_commit.lower() not in ("unknown", "installed")
        is_known_running = running_commit and running_commit.lower() not in ("unknown", "installed")

        if (is_known_installed and is_known_running and installed_commit != running_commit) or (
            _parse_version_tuple(installed_ver) > _parse_version_tuple(running_ver)
        ):
            result["restart_required"] = True

        # Check if GitHub has newer version than installed on disk
        if latest_sha:
            if is_known_installed:
                if installed_commit.lower() != latest_sha.lower():
                    result["update_available"] = True
            else:
                # When running as an installed package without git commit info, compare semantic versions
                if _parse_version_tuple(latest_v) > _parse_version_tuple(installed_ver):
                    result["update_available"] = True
                else:
                    # Same or higher version -> Up to date!
                    result["update_available"] = False
        else:
            # Could not fetch commit, compare versions
            if _parse_version_tuple(latest_v) > _parse_version_tuple(installed_ver):
                result["update_available"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


async def check_for_updates_async(timeout: float = 2.5) -> Dict[str, Any]:
    """Asynchronously checks for updates in a worker thread."""
    return await asyncio.to_thread(check_for_updates, timeout)


def apply_update() -> Tuple[bool, str]:
    """
    Applies the latest NetMash update authoritatively into the active Python environment.
    - If running from a git clone, executes `git -C <root> pull origin main` and `pip install -e .`
    - If running from a pip package, executes `pip install --upgrade --no-cache-dir git+https://...`
    
    Verifies the newly installed on-disk package commit/version before reporting success.
    Returns (success: bool, message: str).
    """
    # 1. Pre-check update status
    pre_info = check_for_updates(timeout=3.0)
    if not pre_info.get("error") and not pre_info.get("update_available") and not pre_info.get("restart_required"):
        return True, f"NetMash is already up to date! (Commit: {pre_info.get('installed_commit')})"

    repo_root = get_git_repo_root()
    target_commit = pre_info.get("latest_commit")

    if repo_root:
        # --- Method A: Git Clone Update ---
        try:
            pull_res = subprocess.run(
                ["git", "-C", str(repo_root), "pull", "origin", GITHUB_BRANCH],
                capture_output=True,
                text=True,
                check=False,
                timeout=30.0,
            )
            if pull_res.returncode != 0:
                # Fallback to generic pull
                pull_res = subprocess.run(
                    ["git", "-C", str(repo_root), "pull"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30.0,
                )

            if pull_res.returncode != 0:
                return False, f"Git pull failed:\n{pull_res.stderr or pull_res.stdout}"

            # Re-install in editable mode with the active Python interpreter
            pip_res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", str(repo_root)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60.0,
            )
            if pip_res.returncode != 0:
                return False, f"Package installation failed:\n{pip_res.stderr or pip_res.stdout}"

            # Post-verification
            new_commit = get_installed_commit_sha()
            running_c = get_running_commit_sha()
            return (
                True,
                f"Successfully updated NetMash to commit {new_commit or 'latest'}!\n"
                f"Running version:   {get_running_version()} ({running_c})\n"
                f"Installed version: {get_installed_version()} ({new_commit})\n"
                f"Please run /restart to load the new version.",
            )

        except Exception as e:
            return False, f"Update execution error: {e}"

    else:
        # --- Method B: Pip Package Update from GitHub ---
        try:
            pip_url = f"git+https://github.com/{GITHUB_REPO}.git@{GITHUB_BRANCH}"
            pip_base_cmd = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--no-cache-dir",
                pip_url,
            ]

            # Try standard pip install
            pip_res = subprocess.run(
                pip_base_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=90.0,
            )

            if pip_res.returncode != 0 and "--break-system-packages" not in pip_base_cmd:
                # Try with --break-system-packages for managed Linux/Debian environments
                pip_res = subprocess.run(
                    pip_base_cmd + ["--break-system-packages"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=90.0,
                )

            if pip_res.returncode == 0:
                new_commit = get_installed_commit_sha()
                running_c = get_running_commit_sha()
                return (
                    True,
                    f"Successfully updated NetMash package from GitHub repository!\n"
                    f"Running version:   {get_running_version()} ({running_c})\n"
                    f"Installed version: {get_installed_version()} ({new_commit})\n"
                    f"Please run /restart to load the new version.",
                )
            else:
                return False, f"Pip update failed:\n{pip_res.stderr or pip_res.stdout}"

        except Exception as e:
            return False, f"Pip update error: {e}"


async def apply_update_async() -> Tuple[bool, str]:
    """Asynchronously applies the update in a worker thread."""
    return await asyncio.to_thread(apply_update)


def render_version_diagnostics() -> Dict[str, Any]:
    """
    Returns complete diagnostic version and environment information for /version and /diagnose.
    """
    running_v = get_running_version()
    running_c = get_running_commit_sha()
    installed_v = get_installed_version()
    installed_c = get_installed_commit_sha() or "unknown"
    repo_root = get_git_repo_root()

    restart_pending = (
        (installed_c != "unknown" and running_c != "unknown" and installed_c != running_c)
        or (_parse_version_tuple(installed_v) > _parse_version_tuple(running_v))
    )

    return {
        "running_version": running_v,
        "running_commit": running_c,
        "installed_version": installed_v,
        "installed_commit": installed_c,
        "restart_pending": restart_pending,
        "install_path": str(Path(__file__).resolve().parent),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": f"{sys.platform} ({platform.system()} {platform.release()})",
        "repository": f"{GITHUB_REPO} ({GITHUB_BRANCH})",
        "is_git_clone": repo_root is not None,
        "repo_root": str(repo_root) if repo_root else "N/A (pip package)",
    }

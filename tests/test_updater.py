"""
Unit and integration tests for NetMash updater functions, version diagnostics,
and update verification logic.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import json

from netmash.updater import (
    apply_update,
    check_for_updates,
    get_git_repo_root,
    get_installed_commit_sha,
    get_installed_version,
    get_local_commit_sha,
    get_running_commit_sha,
    get_running_version,
    render_version_diagnostics,
)


def test_updater_git_repo_detection():
    root = get_git_repo_root()
    assert root is not None
    assert (root / "pyproject.toml").exists()


def test_updater_local_commit_sha():
    sha = get_local_commit_sha()
    assert sha is not None
    assert len(sha) >= 7


def test_updater_running_commit_and_version():
    running_sha = get_running_commit_sha()
    assert running_sha is not None
    assert len(running_sha) >= 7 or running_sha == "unknown"

    running_v = get_running_version()
    assert running_v == "1.1.0"

    installed_v = get_installed_version()
    assert installed_v is not None


def test_updater_render_version_diagnostics():
    diag = render_version_diagnostics()
    assert "running_version" in diag
    assert "running_commit" in diag
    assert "installed_version" in diag
    assert "installed_commit" in diag
    assert "python_executable" in diag
    assert "platform" in diag
    assert "repository" in diag
    assert diag["is_git_clone"] is True


def test_updater_check_structure():
    res = check_for_updates(timeout=3.0)
    assert "update_available" in res
    assert "restart_required" in res
    assert "running_version" in res
    assert "installed_version" in res
    assert "is_git_clone" in res


def test_updater_up_to_date_when_commits_match():
    current_sha = get_local_commit_sha() or "6e8fa95"
    mock_commit_data = json.dumps({
        "sha": current_sha + "000000000000000000000000000000000",
        "commit": {
            "message": "Latest commit message\nSecond line",
            "committer": {"date": "2026-10-07T12:00:00Z"},
        },
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_commit_data
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = check_for_updates(timeout=1.0)
        assert res["latest_commit"] == current_sha[:7].lower()
        # Should be up to date since commits match!
        assert res["update_available"] is False


def test_updater_update_available_when_commits_differ():
    mock_commit_data = json.dumps({
        "sha": "fffffff00000000000000000000000000",
        "commit": {
            "message": "New feature commit",
            "committer": {"date": "2026-10-08T12:00:00Z"},
        },
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_commit_data
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = check_for_updates(timeout=1.0)
        assert res["latest_commit"] == "fffffff"
        assert res["update_available"] is True


def test_apply_update_already_current():
    current_sha = get_local_commit_sha() or "6e8fa95"
    mock_commit_data = json.dumps({
        "sha": current_sha + "000000000000000000000000000000000",
        "commit": {
            "message": "Latest commit",
            "committer": {"date": "2026-10-07T12:00:00Z"},
        },
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_commit_data
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        success, msg = apply_update()
        assert success is True
        assert "already up to date" in msg.lower()

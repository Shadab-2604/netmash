"""
Unit tests for NetMash updater functions and git resolution.
"""

from netmash.updater import get_git_repo_root, get_local_commit_sha, check_for_updates


def test_updater_git_repo_detection():
    root = get_git_repo_root()
    # In this workspace, git repo root should be detected
    assert root is not None
    assert (root / "pyproject.toml").exists()


def test_updater_local_commit_sha():
    sha = get_local_commit_sha()
    assert sha is not None
    assert len(sha) >= 7


def test_updater_check_structure():
    # Test that check_for_updates returns the expected schema
    res = check_for_updates(timeout=3.0)
    assert "update_available" in res
    assert "current_version" in res
    assert "latest_version" in res
    assert "is_git_clone" in res
    assert res["is_git_clone"] is True

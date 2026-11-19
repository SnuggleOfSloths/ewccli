#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2026 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Tests for EWC Hub backends (git_clone_item ref checkout)."""

import subprocess

from pathlib import Path

import pytest

import ewccli.commands.hub.hub_backends as hub_backends
from ewccli.commands.hub.hub_backends import git_clone_item


@pytest.fixture
def local_repo(tmp_path):
    """Create a local git repo with a tag and a later commit on main.

    Layout:
        tag 1.0.0 -> f.txt contains "v1"
        HEAD (main) -> f.txt contains "v2-later-commit"
    """
    repo = tmp_path / "itemrepo"
    repo.mkdir()

    def sh(cmd: str) -> None:
        result = subprocess.run(
            cmd, shell=True, cwd=repo, capture_output=True, text=True
        )
        assert result.returncode == 0, f"{cmd} failed: {result.stderr}"

    sh("git init -q -b main .")
    sh("git config user.email test@example.com")
    sh("git config user.name test")

    (repo / "f.txt").write_text("v1")
    sh("git add .")
    sh('git commit -qm "v1"')
    sh("git tag 1.0.0")

    (repo / "f.txt").write_text("v2-later-commit")
    sh("git add .")
    sh('git commit -qm "v2"')

    return repo


@pytest.fixture(autouse=True)
def skip_http_accessibility_check(monkeypatch):
    """The accessibility check performs an HTTP GET; not applicable to local repos."""
    monkeypatch.setattr(hub_backends, "check_github_repo_accessible", lambda s: True)


def _content(out_dir: Path) -> str:
    return (out_dir / "itemrepo" / "f.txt").read_text()


def test_fresh_clone_checks_out_ref(local_repo, tmp_path):
    """A fresh clone must be checked out at the requested ref, not HEAD."""
    out = tmp_path / "out"

    rc, msg = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        ref="1.0.0",
    )

    assert rc == 0, msg
    assert _content(out) == "v1"


def test_existing_clone_still_checks_out_ref(local_repo, tmp_path):
    """Even when the clone is skipped, the repo must be brought to the ref.

    This is the core of the issue: without --force the clone is skipped, but
    different users deploying the same item version must run the same code.
    """
    out = tmp_path / "out"

    # First run: clone at ref
    rc, _ = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        ref="1.0.0",
    )
    assert rc == 0

    # Simulate new commits landing on main after the clone.
    # The clone does not inherit the source repo's local git config, and CI
    # runners may have no global identity, so pass it inline.
    repo = out / "itemrepo"
    (repo / "f.txt").write_text("v3-even-later")
    subprocess.run(
        "git add . && git -c user.email=test@example.com"
        " -c user.name=test commit -qm 'v3'",
        shell=True,
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )

    # Second run without force: clone is skipped, but ref is re-checked-out
    rc, msg = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        ref="1.0.0",
    )

    assert rc == 0, msg
    assert _content(out) == "v1"


def test_unknown_ref_fails_with_clear_message(local_repo, tmp_path):
    """A ref that matches no tag/branch/commit must fail with a clear error."""
    out = tmp_path / "out"

    rc, msg = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        ref="9.9.9",
    )

    assert rc != 0
    assert "9.9.9" in msg
    assert "tag, branch or commit" in msg


def test_no_ref_keeps_previous_behaviour(local_repo, tmp_path):
    """Without a ref, the function only clones (backwards compatible)."""
    out = tmp_path / "out"

    rc, _ = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
    )

    assert rc == 0
    # HEAD of main is the latest commit
    assert _content(out) == "v2-later-commit"


def test_force_reclones_and_checks_out_ref(local_repo, tmp_path):
    """--force deletes the clone, re-clones and still checks out the ref."""
    out = tmp_path / "out"

    rc, _ = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        ref="1.0.0",
    )
    assert rc == 0

    rc, msg = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        force=True,
        ref="1.0.0",
    )

    assert rc == 0, msg
    assert _content(out) == "v1"


def test_force_on_missing_clone_does_not_crash(local_repo, tmp_path):
    """--force with no existing clone must not raise (rmtree guard)."""
    out = tmp_path / "out"

    rc, msg = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        force=True,
        ref="1.0.0",
    )

    assert rc == 0, msg
    assert _content(out) == "v1"


def test_dry_run_skips_everything(local_repo, tmp_path):
    """Dry run must not clone or checkout."""
    out = tmp_path / "out"

    rc, msg = git_clone_item(
        source=f"file://{local_repo}",
        repo_name="itemrepo",
        command_path=str(out),
        dry_run=True,
        ref="1.0.0",
    )

    assert rc == 0
    assert "Dry run" in msg
    assert not (out / "itemrepo").exists()

@pytest.mark.parametrize("repo_name", ["", ".", "..", "../victim", "/victim", "a/b", "a\\b"])
def test_invalid_repo_name_has_no_side_effects(tmp_path, monkeypatch, repo_name):
    out = tmp_path / "out"
    monkeypatch.setattr(
        hub_backends, "_clone_repository", lambda **kwargs: pytest.fail("clone called")
    )
    rc, _ = git_clone_item("unused", repo_name, str(out), force=True)
    assert rc != 0
    assert not out.exists()


@pytest.mark.parametrize("escape", ["traversal", "parent_symlink", "repo_symlink", "root"])
def test_force_rejects_output_escape(tmp_path, monkeypatch, escape):
    root = tmp_path / "outputs"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    marker = victim / "keep.txt"
    marker.write_text("unrelated data")
    command_path = root / "item-1"
    repo_name = "victim"
    if escape == "traversal":
        command_path = root / "item-1" / ".." / ".."
    elif escape == "parent_symlink":
        command_path.symlink_to(tmp_path, target_is_directory=True)
    elif escape == "repo_symlink":
        command_path.mkdir()
        (command_path / repo_name).symlink_to(victim, target_is_directory=True)
    else:
        command_path = root.parent
        repo_name = root.name
    monkeypatch.setattr(
        hub_backends, "check_github_repo_accessible",
        lambda source: pytest.fail("network check called"),
    )
    rc, _ = git_clone_item(
        "unused", repo_name, str(command_path), force=True, output_root=root
    )
    assert rc != 0
    assert marker.read_text() == "unrelated data"
    assert root.is_dir()

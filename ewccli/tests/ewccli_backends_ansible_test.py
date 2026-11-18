"""Regression tests for the role install subprocess boundary."""

import json
import os
import sys

import pytest

from ewccli.backends.ansible.backend_ansible import AnsibleBackend
from ewccli.utils import run_command_from_host


@pytest.mark.parametrize("exit_code", [0, 7])
def test_role_install_preserves_requirements_argument(tmp_path, monkeypatch, exit_code):
    """Shell syntax in a filename must reach Galaxy literally, even on failure."""
    monkeypatch.chdir(tmp_path)
    executable = tmp_path / "ansible-galaxy"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
        "print('installed')\n"
        "print('install failed', file=sys.stderr)\n"
        f"sys.exit({exit_code})\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    requirements_path = str(
        tmp_path / "roles with 'quotes'; touch injected; $(touch substituted) #.yml"
    )

    result, message = AnsibleBackend().install_ansible_roles(requirements_path)

    assert result == exit_code
    assert ("installed" if exit_code == 0 else "install failed") in message
    assert json.loads((tmp_path / "arguments.json").read_text()) == [
        "role", "install", "-r", requirements_path, "--force"
    ]
    assert not (tmp_path / "injected").exists()
    assert not (tmp_path / "substituted").exists()


def test_role_install_dry_run_does_not_execute(monkeypatch):
    """Dry runs must return without starting a subprocess."""
    def unexpected_run(*args, **kwargs):
        pytest.fail("dry run started a subprocess")

    monkeypatch.setattr("ewccli.utils.subprocess.run", unexpected_run)
    assert AnsibleBackend().install_ansible_roles("roles.yml", dry_run=True) == (
        0, "Dry run. No actions."
    )


def test_existing_shell_commands_remain_supported():
    """Existing callers rely on the helper interpreting shell expressions."""
    result, message = run_command_from_host(
        "shell compatibility", ["printf first && printf second"]
    )
    assert result == 0
    assert "firstsecond" in message

#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2026 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Regression tests for argument boundaries at the Ansible Runner boundary."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ansible_runner.config.runner import RunnerConfig

from ewccli.backends.ansible.backend_ansible import AnsibleBackend


@pytest.mark.parametrize(
    "inputs",
    [
        None,
        {"message": "ordinary", "count": 3, "enabled": True},
        {"message": "O'Brien"},
        {"message": "' --ssh-common-args=ProxyCommand=unexpected '"},
        {"message": "quotes '\" and \\ backslashes\nwith whitespace", "nested": [1, None]},
    ],
)
def test_runner_preserves_argument_boundaries(tmp_path, monkeypatch, inputs):
    """Item data must remain one JSON argument after Runner parses its args file."""
    cmdline = [
        "ansible-playbook",
        "-i",
        str(tmp_path / "inventory with spaces.ini"),
        "-u",
        "test-user",
        "--private-key",
        str(tmp_path / "key with ' quote"),
        str(tmp_path / "playbook with spaces.yml"),
    ]
    extra_vars = json.dumps(inputs) if inputs is not None else None
    expected = cmdline + (["--extra-vars", extra_vars] if extra_vars else [])
    thread = SimpleNamespace(join=Mock())

    def run_async(**kwargs):
        # Exercise the installed, pinned Runner parser without starting Ansible
        # or making an SSH connection.
        config = RunnerConfig(private_data_dir=kwargs["private_data_dir"])
        config.prepare_command()
        assert config.command == expected
        if inputs is not None:
            assert json.loads(config.command[-1]) == inputs
        return thread, SimpleNamespace(rc=7)

    monkeypatch.setattr(
        "ewccli.backends.ansible.backend_ansible.ansible_runner.run_async", run_async
    )
    assert AnsibleBackend().run_ansible_live(
        working_directory_path=str(tmp_path), cmdline=cmdline, extra_vars=extra_vars
    ) == 7
    thread.join.assert_called_once_with()
    assert cmdline == expected[:len(cmdline)]
    assert not (tmp_path / "args").exists()

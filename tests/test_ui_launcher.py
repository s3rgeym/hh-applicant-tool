from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import start  # noqa: E402


def test_cli_menu_uses_existing_operation_names():
    commands = [command for command, _ in start.CLI_COMMANDS]
    assert "apply-vacancies" in commands
    assert "authorize" in commands
    assert "list-resumes" in commands
    assert "whoami" in commands
    assert "update-resumes" in commands

    assert "get-resumes" not in commands
    assert "get-negotiations" not in commands
    assert "update-resume" not in commands
    assert "reply-employers" not in commands

from __future__ import annotations

from pathlib import Path

import pytest

from hh_applicant_tool.ui.profiles import (
    DEFAULT_PROFILE_ID,
    ProfileValidationError,
    ProfilesManager,
)
from hh_applicant_tool.utils.config import Config


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Tool:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.profile_id = DEFAULT_PROFILE_ID
        self.saved_token = False
        self.saved_cookies = False

    def save_token(self) -> None:
        self.saved_token = True

    def save_cookies(self) -> None:
        self.saved_cookies = True


def test_list_profiles_discovers_directories_and_saved_token(tmp_path):
    tool = _Tool(tmp_path)
    manager = ProfilesManager(tool)

    (tmp_path / "work").mkdir()
    (tmp_path / ".second").mkdir()
    Config(tmp_path / "work" / "config.json").save(
        token={"access_token": "token"}
    )

    profiles = manager.list_profiles()
    by_id = {profile["id"]: profile for profile in profiles}

    assert list(by_id) == [".", ".second", "work"]
    assert by_id["."]["active"] is True
    assert by_id["work"]["has_token"] is True
    assert by_id[".second"]["has_token"] is False


def test_create_and_switch_profile_clears_profile_scoped_state(tmp_path):
    tool = _Tool(tmp_path)
    manager = ProfilesManager(tool)
    manager.create_profile("work")

    db = _Closable()
    session = _Closable()
    tool.__dict__["db"] = db
    tool.__dict__["session"] = session
    tool.__dict__["config"] = object()
    tool.__dict__["storage"] = object()
    tool.__dict__["api_client"] = object()

    profile_id = manager.switch_profile("work")

    assert profile_id == "work"
    assert tool.profile_id == "work"
    assert tool.saved_token is True
    assert tool.saved_cookies is True
    assert db.closed is True
    assert session.closed is True
    for name in ("db", "session", "config", "storage", "api_client"):
        assert name not in tool.__dict__


def test_switch_rejects_unknown_profile(tmp_path):
    manager = ProfilesManager(_Tool(tmp_path))

    with pytest.raises(ProfileValidationError, match="не найден"):
        manager.switch_profile("missing")


@pytest.mark.parametrize(
    "profile_id",
    ["../escape", "nested/path", "nested\\path", "", "..", "a" * 65],
)
def test_profile_id_rejects_unsafe_values(tmp_path, profile_id):
    manager = ProfilesManager(_Tool(tmp_path))

    with pytest.raises(ProfileValidationError):
        manager.create_profile(profile_id)


def test_unicode_and_dot_prefixed_profile_ids_are_supported(tmp_path):
    manager = ProfilesManager(_Tool(tmp_path))

    assert manager.create_profile(".work") == ".work"
    assert manager.create_profile("работа") == "работа"


def test_delete_non_active_profile_removes_directory(tmp_path):
    tool = _Tool(tmp_path)
    manager = ProfilesManager(tool)
    manager.create_profile("old")
    Config(tmp_path / "old" / "config.json").save(test=True)

    manager.delete_profile("old")

    assert not (tmp_path / "old").exists()


def test_delete_active_or_default_profile_is_blocked(tmp_path):
    tool = _Tool(tmp_path)
    manager = ProfilesManager(tool)
    manager.create_profile("work")
    manager.switch_profile("work")

    with pytest.raises(ProfileValidationError, match="Сначала переключитесь"):
        manager.delete_profile("work")

    manager.switch_profile(".")
    with pytest.raises(ProfileValidationError, match="удалить нельзя"):
        manager.delete_profile(".")

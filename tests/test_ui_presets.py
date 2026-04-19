"""Тесты для PresetsManager — управления пресетами параметров поиска.

PresetsManager сохраняет/загружает наборы параметров поиска вакансий
(пресеты) в SQLite через SettingsRepository. Это позволяет пользователю
не вводить ~30 параметров заново при каждом запуске.
"""

from __future__ import annotations

import sqlite3

import pytest

from hh_applicant_tool.storage import StorageFacade
from hh_applicant_tool.ui.presets import (
    MAX_NAME_LEN,
    MAX_PARAMS_BYTES,
    PresetsManager,
    PresetValidationError,
)


@pytest.fixture
def storage():
    """In-memory SQLite для изоляции тестов."""
    conn = sqlite3.connect(":memory:")
    return StorageFacade(conn)


@pytest.fixture
def presets(storage):
    return PresetsManager(storage.settings)


class TestSaveAndLoad:
    def test_save_and_load_simple(self, presets):
        params = {"search": "Python developer", "salary": 200000}
        presets.save("my_preset", params)
        loaded = presets.load("my_preset")
        assert loaded == params

    def test_save_and_load_complex(self, presets):
        """Пресет с вложенными типами — списки, None, bool."""
        params = {
            "search": "Go разработчик",
            "area": ["1", "2"],
            "salary": 150000,
            "use_ai": True,
            "ai_filter": "light",
            "dry_run": False,
        }
        presets.save("complex", params)
        assert presets.load("complex") == params

    def test_load_nonexistent_returns_none(self, presets):
        assert presets.load("несуществующий") is None

    def test_overwrite_preset(self, presets):
        presets.save("x", {"search": "old"})
        presets.save("x", {"search": "new"})
        assert presets.load("x") == {"search": "new"}


class TestListAndDelete:
    def test_list_empty(self, presets):
        assert presets.list_names() == []

    def test_list_after_save(self, presets):
        presets.save("alpha", {"search": "a"})
        presets.save("beta", {"search": "b"})
        names = presets.list_names()
        assert set(names) == {"alpha", "beta"}

    def test_delete(self, presets):
        presets.save("tmp", {"search": "x"})
        presets.delete("tmp")
        assert presets.load("tmp") is None
        assert "tmp" not in presets.list_names()

    def test_delete_nonexistent_no_error(self, presets):
        """Удаление несуществующего пресета не должно падать."""
        presets.delete("ghost")


class TestLastUsed:
    def test_save_and_load_last_used(self, presets):
        params = {"search": "Go developer", "salary": 300000}
        presets.save_last_used(params)
        assert presets.load_last_used() == params

    def test_load_last_used_when_empty(self, presets):
        assert presets.load_last_used() is None

    def test_last_used_independent_of_named_presets(self, presets):
        """last_used не появляется в list_names()."""
        presets.save_last_used({"search": "test"})
        assert presets.list_names() == []


class TestValidation:
    def test_rejects_empty_name(self, presets):
        with pytest.raises(PresetValidationError):
            presets.save("", {"search": "x"})

    def test_rejects_whitespace_only_name(self, presets):
        with pytest.raises(PresetValidationError):
            presets.save("   ", {"search": "x"})

    def test_rejects_non_string_name(self, presets):
        with pytest.raises(PresetValidationError):
            presets.save(123, {"search": "x"})  # type: ignore[arg-type]

    def test_rejects_name_with_colon(self, presets):
        """Двоеточие резервировано для внутреннего префикса ключей."""
        with pytest.raises(PresetValidationError):
            presets.save("pre:set", {"search": "x"})

    def test_rejects_name_with_control_chars(self, presets):
        with pytest.raises(PresetValidationError):
            presets.save("bad\x00name", {"search": "x"})

    def test_rejects_too_long_name(self, presets):
        with pytest.raises(PresetValidationError):
            presets.save("a" * (MAX_NAME_LEN + 1), {"search": "x"})

    def test_accepts_name_at_max_length(self, presets):
        name = "a" * MAX_NAME_LEN
        presets.save(name, {"search": "x"})
        assert name in presets.list_names()

    def test_accepts_cyrillic_name(self, presets):
        presets.save("Мой поиск", {"search": "x"})
        assert "Мой поиск" in presets.list_names()

    def test_trims_whitespace_in_name(self, presets):
        presets.save("  pad  ", {"search": "x"})
        assert "pad" in presets.list_names()
        assert presets.load("pad") == {"search": "x"}

    def test_rejects_non_dict_params(self, presets):
        with pytest.raises(PresetValidationError):
            presets.save("p", "not a dict")  # type: ignore[arg-type]

    def test_rejects_oversized_params(self, presets):
        big = {"huge": "x" * (MAX_PARAMS_BYTES + 1)}
        with pytest.raises(PresetValidationError):
            presets.save("p", big)

    def test_save_last_used_rejects_oversized(self, presets):
        big = {"huge": "x" * (MAX_PARAMS_BYTES + 1)}
        with pytest.raises(PresetValidationError):
            presets.save_last_used(big)

    def test_load_nonexistent_invalid_name_returns_none(self, presets):
        assert presets.load("") is None
        assert presets.load("a:b") is None

    def test_delete_invalid_name_noop(self, presets):
        presets.delete("")
        presets.delete("a:b")

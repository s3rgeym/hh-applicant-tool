"""Тесты для Api — Python↔JS моста в UI.

Api оборачивает HHApplicantTool и предоставляет методы, вызываемые
из JavaScript через pywebview.api.*. Каждый метод возвращает
сериализуемый dict/list/str, который pywebview передаёт в JS как Promise.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from hh_applicant_tool.storage import StorageFacade
from hh_applicant_tool.ui.api import Api


class MockConfig(dict):
    """Мок Config — dict с методом save(), как настоящий Config."""

    def save(self, **kwargs):
        self.update(kwargs)


@pytest.fixture
def mock_tool():
    """Мок HHApplicantTool с реальным StorageFacade (in-memory SQLite)."""
    tool = MagicMock()
    tool.config = MockConfig({
        "client_id": "test_id",
        "client_secret": "secret_123",
        "token": {"access_token": "tok_abc", "refresh_token": "ref_xyz"},
        "proxy_url": "socks5://user:pass@localhost:1080",
        "openai_cover_letter": {
            "api_key": "sk-test-00000000000000000000",
            "base_url": "https://api.openai.com",
            "model": "gpt-4",
        },
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "user": "me@example.com",
            "password": "smtp-secret-pass",
        },
    })
    tool.get_resumes.return_value = [
        {"id": "res1", "title": "Python Dev", "status": {"name": "published"}},
        {"id": "res2", "title": "Go Dev", "status": {"name": "blocked"}},
    ]
    tool.get_me.return_value = {
        "first_name": "Иван",
        "last_name": "Петров",
        "email": "test@example.com",
    }
    # Реальный storage для тестирования пресетов через Api
    conn = sqlite3.connect(":memory:")
    tool.storage = StorageFacade(conn)
    return tool


@pytest.fixture
def api(mock_tool):
    return Api(mock_tool)


class TestGetStatus:
    def test_authorized(self, api):
        status = api.get_status()
        assert status["authorized"] is True
        assert status["user"]["first_name"] == "Иван"

    def test_unauthorized_when_get_me_fails(self, api, mock_tool):
        mock_tool.get_me.side_effect = Exception("no token")
        status = api.get_status()
        assert status["authorized"] is False
        assert status["user"] is None


class TestGetResumes:
    def test_returns_list(self, api):
        resumes = api.get_resumes()
        assert len(resumes) == 2
        assert resumes[0]["id"] == "res1"
        assert resumes[1]["title"] == "Go Dev"

    def test_returns_empty_on_error(self, api, mock_tool):
        mock_tool.get_resumes.side_effect = Exception("network error")
        assert api.get_resumes() == []


class TestConfig:
    def test_get_config_masks_top_level_secrets(self, api):
        """client_secret, token, proxy_url замаскированы на top-level."""
        config = api.get_config()
        assert config["client_secret"] == "***"
        assert config["token"] == "***"
        assert config["proxy_url"] == "***"
        # Публичные ключи видны
        assert config["client_id"] == "test_id"

    def test_get_config_masks_nested_secrets(self, api):
        """Вложенные api_key, password маскируются рекурсивно."""
        config = api.get_config()
        assert config["openai_cover_letter"]["api_key"] == "***"
        # Несекретные поля внутри вложенного dict остаются видны
        assert config["openai_cover_letter"]["base_url"] == "https://api.openai.com"
        assert config["openai_cover_letter"]["model"] == "gpt-4"
        assert config["smtp"]["password"] == "***"
        assert config["smtp"]["host"] == "smtp.example.com"
        assert config["smtp"]["user"] == "me@example.com"

    def test_save_config_ignores_top_level_masked_keys(self, api, mock_tool):
        """Нельзя перезаписать client_secret и token через save_config."""
        original_secret = mock_tool.config["client_secret"]
        original_token = mock_tool.config["token"]
        api.save_config({
            "client_id": "new_id",
            "client_secret": "hacked",
            "token": {"access_token": "stolen"},
        })
        assert mock_tool.config["client_secret"] == original_secret
        assert mock_tool.config["token"] == original_token
        # Несекретное поле обновилось
        assert mock_tool.config["client_id"] == "new_id"

    def test_save_config_strips_mask_value(self, api, mock_tool):
        """Значение "***" отбрасывается — нельзя перезаписать секрет маской."""
        original_proxy = mock_tool.config["proxy_url"]
        api.save_config({"proxy_url": "***"})
        assert mock_tool.config["proxy_url"] == original_proxy

    def test_save_config_strips_nested_mask(self, api, mock_tool):
        captured = {}
        mock_tool.config.save = lambda **kw: captured.update(kw)
        api.save_config({
            "openai_cover_letter": {
                "api_key": "***",
                "model": "gpt-4-turbo",
            }
        })
        # api_key="***" stripped — existing key preserved via merge, model updated
        assert captured["openai_cover_letter"]["model"] == "gpt-4-turbo"
        assert captured["openai_cover_letter"]["api_key"] == "sk-test-00000000000000000000"

    def test_save_config_preserves_omitted_nested_secret(self, api, mock_tool):
        api.save_config({
            "openai_cover_letter": {
                "model": "gpt-4.1",
            }
        })
        assert mock_tool.config["openai_cover_letter"]["api_key"] == "sk-test-00000000000000000000"
        assert mock_tool.config["openai_cover_letter"]["model"] == "gpt-4.1"

    def test_save_config_preserves_value_types(self, api, mock_tool):
        api.save_config({
            "smtp": {
                "port": 2525,
                "ssl": True,
            }
        })
        assert mock_tool.config["smtp"]["port"] == 2525
        assert mock_tool.config["smtp"]["ssl"] is True

    def test_save_config_returns_ok(self, api):
        result = api.save_config({"client_id": "x"})
        assert result["status"] == "ok"

    def test_save_config_returns_error_on_failure(self, api, mock_tool):
        mock_tool.config.save = MagicMock(side_effect=IOError("permission denied"))
        result = api.save_config({"client_id": "x"})
        assert result["status"] == "error"


class TestPresetsMethods:
    """Проверяем что Api корректно проксирует вызовы в PresetsManager."""

    def test_save_and_list(self, api):
        result = api.save_preset(
            "my_search", {"search": "python", "salary": 200000}
        )
        assert result == {"status": "ok"}
        names = api.list_presets()
        assert "my_search" in names

    def test_load_preset(self, api):
        api.save_preset("p1", {"search": "go"})
        loaded = api.load_preset("p1")
        assert loaded == {"search": "go"}

    def test_delete_preset(self, api):
        api.save_preset("del_me", {"search": "x"})
        api.delete_preset("del_me")
        assert "del_me" not in api.list_presets()

    def test_last_used_initially_none(self, api):
        assert api.get_last_used_params() is None

    def test_save_and_get_last_used(self, api):
        params = {"search": "rust", "area": ["1"]}
        api.save_last_used_params(params)
        assert api.get_last_used_params() == params

    def test_save_preset_rejects_empty_name(self, api):
        result = api.save_preset("", {"search": "x"})
        assert result["status"] == "error"
        assert "message" in result

    def test_save_preset_rejects_name_with_colon(self, api):
        result = api.save_preset("a:b", {"search": "x"})
        assert result["status"] == "error"

    def test_save_preset_rejects_oversized_params(self, api):
        big = {"x": "a" * (65 * 1024)}
        result = api.save_preset("big", big)
        assert result["status"] == "error"

    def test_save_last_used_swallows_invalid(self, api):
        """save_last_used не должен падать при невалидных данных."""
        big = {"x": "a" * (65 * 1024)}
        api.save_last_used_params(big)
        # last_used остался пустым, исключение не поднялось
        assert api.get_last_used_params() is None


class TestErrorMessages:
    """Клиентский код не должен получать внутренние детали исключений."""

    def test_refresh_negotiations_generic_message(self, api, mock_tool):
        mock_tool.get_negotiations.side_effect = Exception(
            "internal path /etc/secret leaked"
        )
        result = api.refresh_negotiations("active")
        assert result["status"] == "error"
        assert "/etc/secret" not in result["message"]
        assert "leaked" not in result["message"]

    def test_apply_vacancies_generic_message_on_failure(self, api, mock_tool):
        """При внутренней ошибке наружу идёт generic-сообщение, не str(e)."""
        # Форсим ошибку через невалидные argv, которые вызовут SystemExit
        # внутри argparse → Exception путь в apply_vacancies
        mock_tool.get_resumes.return_value = []
        # Невалидный параметр вызовет ошибку argparse / Namespace
        result = api.apply_vacancies({"nonexistent_flag_xyz": "leak /root/.ssh"})
        # Либо отработал, либо упал с generic message
        if result["status"] == "error":
            assert "/root/.ssh" not in result.get("message", "")


class TestApplyVacancies:
    """Тесты интеграции apply_vacancies через Api."""

    def test_params_to_argv_simple(self, api):
        """Конвертация dict → CLI argv."""
        argv = api._params_to_argv({"search": "python", "salary": 200000})
        assert "--search" in argv
        assert "python" in argv
        assert "--salary" in argv
        assert "200000" in argv

    def test_params_to_argv_bool_true(self, api):
        argv = api._params_to_argv({"dry_run": True})
        assert "--dry-run" in argv

    def test_params_to_argv_bool_false_skipped(self, api):
        argv = api._params_to_argv({"dry_run": False})
        assert "--dry-run" not in argv

    def test_params_to_argv_none_skipped(self, api):
        argv = api._params_to_argv({"salary": None})
        assert argv == []

    def test_params_to_argv_list(self, api):
        argv = api._params_to_argv({"area": ["1", "2"]})
        # nargs="+" expects: --area 1 2 (single flag, multiple values)
        assert argv.count("--area") == 1
        assert argv == ["--area", "1", "2"]

    def test_params_to_argv_empty_list_skipped(self, api):
        argv = api._params_to_argv({"area": []})
        assert argv == []

    def test_apply_saves_last_used(self, api, mock_tool):
        """apply_vacancies должен сохранять параметры как last_used."""
        # Подменяем run чтобы не выполнять реальную операцию
        mock_tool.get_resumes.return_value = []
        params = {"search": "python", "dry_run": True}
        # Вызов apply_vacancies (может упасть на реальной операции —
        # нам важно что last_used сохраняется ДО выполнения)
        api.apply_vacancies(params)
        assert api.get_last_used_params() == params

    def test_apply_returns_dict_with_status(self, api, mock_tool):
        """apply_vacancies всегда возвращает dict с ключом status."""
        result = api.apply_vacancies({"search": "test", "dry_run": True})
        assert "status" in result

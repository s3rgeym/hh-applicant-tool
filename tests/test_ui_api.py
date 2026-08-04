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


class TestRefreshNegotiations:
    """Синхронизация откликов с hh.ru через refresh_negotiations."""

    def test_saves_api_items_to_db(self, api, mock_tool):
        """Отклики hh.ru (raw dict'ы) сохраняются в БД, возвращается count.

        Структура item'ов повторяет ответ hh.ru /negotiations
        (api.datatypes.Negotiation): NegotiationModel.from_api берёт id, chat_id,
        state.id, vacancy.id, vacancy.employer.id, resume.id.
        """
        item1 = {
            "id": "1234567890",
            "state": {"id": "active", "name": "Активный"},
            "created_at": "2026-08-02T10:00:00+03:00",
            "updated_at": "2026-08-02T12:00:00+03:00",
            "resume": {
                "id": "res1",
                "title": "Python Developer",
                "url": "https://hh.ru/resume/res1",
                "alternate_url": "https://hh.ru/resume/res1",
            },
            "viewed_by_opponent": False,
            "has_updates": False,
            "messages_url": "https://hh.ru/messages/1234567890",
            "url": "https://hh.ru/negotiations/1234567890",
            "counters": {"messages": 1, "unread_messages": 0},
            "chat_states": {"response_reminder_state": {"allowed": False}},
            "source": "https://hh.ru/vacancy/111",
            "chat_id": 987654321,
            "messaging_status": "ok",
            "decline_allowed": True,
            "read": True,
            "has_new_messages": False,
            "applicant_question_state": False,
            "hidden": False,
            "vacancy": {
                "id": "111",
                "premium": False,
                "name": "Python разработчик",
                "department": None,
                "has_test": False,
                "response_letter_required": False,
                "area": {"id": "1", "name": "Москва"},
                "salary": None,
                "salary_range": None,
                "type": {"id": "open", "name": "Открытая"},
                "address": None,
                "response_url": None,
                "sort_point_distance": None,
                "published_at": "2026-07-30T10:00:00+03:00",
                "created_at": "2026-07-30T10:00:00+03:00",
                "archived": False,
                "apply_alternate_url": (
                    "https://hh.ru/applicant/vacancy_response?vacancyId=111"
                ),
                "show_contacts": False,
                "benefits": [],
                "insider_interview": None,
                "url": "https://hh.ru/vacancy/111",
                "alternate_url": "https://hh.ru/vacancy/111",
                "professional_roles": [{"id": "96", "name": "Программист"}],
                "employer": {
                    "id": "777",
                    "name": "ООО Ромашка",
                    "url": "https://hh.ru/employer/777",
                    "alternate_url": "https://hh.ru/employer/777",
                    "logo_urls": None,
                    "vacancies_url": "https://hh.ru/employer/777/vacancies",
                    "accredited_it_employer": False,
                    "trusted": False,
                },
                "show_logo_in_search": None,
            },
            "tags": [],
        }
        item2 = {
            "id": "2233445566",
            "state": {"id": "invitation", "name": "Приглашение"},
            "created_at": "2026-08-01T10:00:00+03:00",
            "updated_at": "2026-08-01T11:00:00+03:00",
            "resume": {
                "id": "res2",
                "title": "Go Developer",
                "url": "https://hh.ru/resume/res2",
                "alternate_url": "https://hh.ru/resume/res2",
            },
            "viewed_by_opponent": True,
            "has_updates": True,
            "messages_url": "https://hh.ru/messages/2233445566",
            "url": "https://hh.ru/negotiations/2233445566",
            "counters": {"messages": 3, "unread_messages": 1},
            "chat_states": {"response_reminder_state": {"allowed": True}},
            "source": "https://hh.ru/vacancy/222",
            "chat_id": 1122334455,
            "messaging_status": "ok",
            "decline_allowed": False,
            "read": False,
            "has_new_messages": True,
            "applicant_question_state": False,
            "hidden": False,
            "vacancy": {
                "id": "222",
                "premium": True,
                "name": "Go разработчик",
                "department": None,
                "has_test": True,
                "response_letter_required": False,
                "area": {"id": "2", "name": "Санкт-Петербург"},
                "salary": {
                    "from": 200000,
                    "to": 300000,
                    "currency": "RUR",
                    "gross": True,
                },
                "salary_range": None,
                "type": {"id": "open", "name": "Открытая"},
                "address": None,
                "response_url": None,
                "sort_point_distance": None,
                "published_at": "2026-07-29T10:00:00+03:00",
                "created_at": "2026-07-29T10:00:00+03:00",
                "archived": False,
                "apply_alternate_url": (
                    "https://hh.ru/applicant/vacancy_response?vacancyId=222"
                ),
                "show_contacts": False,
                "benefits": [],
                "insider_interview": None,
                "url": "https://hh.ru/vacancy/222",
                "alternate_url": "https://hh.ru/vacancy/222",
                "professional_roles": [{"id": "96", "name": "Программист"}],
                "employer": {
                    "id": "888",
                    "name": "ООО ТехноГо",
                    "url": "https://hh.ru/employer/888",
                    "alternate_url": "https://hh.ru/employer/888",
                    "logo_urls": None,
                    "vacancies_url": "https://hh.ru/employer/888/vacancies",
                    "accredited_it_employer": True,
                    "trusted": True,
                },
                "show_logo_in_search": None,
            },
            "tags": [],
        }
        mock_tool.get_negotiations.return_value = [item1, item2]

        result = api.refresh_negotiations()

        assert result == {"status": "ok", "count": 2}
        rows = api.get_negotiations_from_db()
        assert len(rows) == 2
        # Порядок из get_negotiations_from_db: ORDER BY created_at DESC,
        # у item1 created_at позже — он первый
        assert rows[0]["state"] == "active"
        assert rows[0]["vacancy_id"] == int(item1["vacancy"]["id"])
        assert rows[1]["state"] == "invitation"
        assert rows[1]["vacancy_id"] == int(item2["vacancy"]["id"])

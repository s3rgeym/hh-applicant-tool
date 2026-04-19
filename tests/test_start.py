"""Тесты для start.py — лаунчера приложения.

Проверяем логику определения первого запуска (has_token),
вычисления пути config.json и автоустановки зависимостей.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# start.py лежит в корне репо, а не в пакете — добавляем в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import start  # noqa: E402


class TestConfigBase:
    """Тесты вычисления базового пути конфига по платформе."""

    @patch("start.platform.system", return_value="Windows")
    @patch.dict("os.environ", {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"})
    def test_windows(self, _mock):
        result = start._config_base()
        assert str(result) == "C:\\Users\\test\\AppData\\Roaming"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Path.home() может падать без HOME на Windows",
    )
    @patch("start.platform.system", return_value="Linux")
    @patch.dict("os.environ", {}, clear=True)
    def test_linux_default(self, _mock):
        result = start._config_base()
        assert ".config" in str(result)

    @patch("start.platform.system", return_value="Linux")
    @patch.dict("os.environ", {"XDG_CONFIG_HOME": "/custom/config"})
    def test_linux_xdg(self, _mock):
        result = start._config_base()
        # На Windows Path("/custom/config") → "\\custom\\config"
        assert result == Path("/custom/config")

    @patch("start.platform.system", return_value="Darwin")
    def test_macos(self, _mock):
        result = start._config_base()
        assert "Application Support" in str(result)


class TestHasToken:
    """Тесты определения первого запуска по наличию токена."""

    def test_no_config_file(self, tmp_path):
        with patch("start.get_config_json", return_value=tmp_path / "nope.json"):
            assert start.has_token() is False

    def test_empty_config(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text("{}", encoding="utf-8")
        with patch("start.get_config_json", return_value=cfg):
            assert start.has_token() is False

    def test_config_without_token(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text('{"client_id": "abc"}', encoding="utf-8")
        with patch("start.get_config_json", return_value=cfg):
            assert start.has_token() is False

    def test_config_with_token(self, tmp_path):
        cfg = tmp_path / "config.json"
        data = {"client_id": "abc", "token": {"access_token": "xyz"}}
        cfg.write_text(json.dumps(data), encoding="utf-8")
        with patch("start.get_config_json", return_value=cfg):
            assert start.has_token() is True

    def test_config_with_empty_token(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text('{"token": {}}', encoding="utf-8")
        with patch("start.get_config_json", return_value=cfg):
            # Пустой dict — falsy → первый запуск
            assert start.has_token() is False

    def test_broken_json(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text("not json!!!", encoding="utf-8")
        with patch("start.get_config_json", return_value=cfg):
            assert start.has_token() is False


class TestGetConfigJson:
    """Тесты формирования полного пути до config.json."""

    @patch("start._config_base", return_value=Path("/base"))
    @patch.dict("os.environ", {}, clear=True)
    def test_default_profile(self, _mock):
        result = start.get_config_json()
        assert result == Path("/base/hh-applicant-tool/./config.json")

    @patch("start._config_base", return_value=Path("/base"))
    @patch.dict("os.environ", {"HH_PROFILE_ID": ".work"})
    def test_custom_profile(self, _mock):
        result = start.get_config_json()
        assert result == Path("/base/hh-applicant-tool/.work/config.json")


class TestIsPackageInstalled:
    """Тесты проверки наличия пакета."""

    def test_hh_package_is_installed(self):
        # В тестовом окружении пакет должен быть установлен
        assert start._is_installed("hh_applicant_tool") is True


class TestFindCompatiblePython:
    """Тесты поиска совместимой версии Python."""

    @patch("start.platform.system", return_value="Linux")
    def test_linux_returns_none(self, _mock):
        assert start._find_compatible_python() is None

    @patch("start.platform.system", return_value="Windows")
    @patch("start.subprocess.run")
    def test_finds_3_13(self, mock_run, _mock_sys):
        mock_run.return_value = type("R", (), {"returncode": 0})()
        result = start._find_compatible_python()
        assert result == "-3.13"

    @patch("start.platform.system", return_value="Windows")
    @patch("start.subprocess.run", side_effect=FileNotFoundError)
    def test_no_py_launcher(self, _mock_run, _mock_sys):
        assert start._find_compatible_python() is None


class TestInstallCompatiblePython:
    """Тесты автоустановки Python через winget."""

    @patch("start.platform.system", return_value="Linux")
    def test_linux_returns_false(self, _mock):
        assert start._install_compatible_python() is False

    @patch("start.platform.system", return_value="Windows")
    @patch("start.subprocess.run")
    def test_no_winget(self, mock_run, _mock_sys):
        mock_run.side_effect = FileNotFoundError
        assert start._install_compatible_python() is False

    @patch("start.platform.system", return_value="Windows")
    @patch("start.subprocess.run")
    def test_winget_install_success(self, mock_run, _mock_sys):
        ok = type("R", (), {"returncode": 0, "check_returncode": lambda self: None})()
        mock_run.return_value = ok
        assert start._install_compatible_python() is True


class TestMaybeRelaunch:
    """Тесты автоперезапуска на совместимой версии."""

    @patch("start.sys.version_info", (3, 13, 0))
    def test_compatible_version_no_relaunch(self):
        start._maybe_relaunch()

    @patch("start.sys.version_info", (3, 14, 0))
    @patch("start._find_compatible_python", return_value="-3.13")
    @patch("start.subprocess.run")
    def test_relaunch_on_new_python(self, mock_run, _mock_find):
        mock_run.return_value = type("R", (), {"returncode": 0})()
        with pytest.raises(SystemExit) as exc:
            start._maybe_relaunch()
        assert exc.value.code == 0

    @patch("start.sys.version_info", (3, 14, 0))
    @patch("start._find_compatible_python", return_value=None)
    @patch("start._install_compatible_python", return_value=False)
    def test_no_compatible_python_continues(self, _i, _f):
        # Не падает — продолжает без UI
        start._maybe_relaunch()

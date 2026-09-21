from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..constants import CONFIG_DIR, CONFIG_FILENAME
from ..utils.config import Config

if TYPE_CHECKING:
    from ..main import HHApplicantTool

DEFAULT_PROFILE_ID = "."
_PROFILE_ID_RE = re.compile(r"^[\w.-]{1,64}$", re.UNICODE)
_PROFILE_CACHED_PROPERTIES = (
    "config_path",
    "config",
    "log_file",
    "cookies_file",
    "db_path",
    "db",
    "storage",
    "session",
    "openai_session",
    "api_client",
    "xsrf_token",
    "smtp",
)


class ProfileValidationError(ValueError):
    pass


class ProfilesManager:
    """Manage isolated hh-applicant-tool profiles used by the UI."""

    def __init__(self, tool: HHApplicantTool):
        self._tool = tool

    @property
    def root(self) -> Path:
        configured = getattr(self._tool, "config_dir", None)
        if not isinstance(configured, (str, os.PathLike)):
            configured = None
        return Path(configured or os.getenv("CONFIG_DIR", CONFIG_DIR)).expanduser().resolve()

    @property
    def active_profile_id(self) -> str:
        profile_id = getattr(self._tool, "profile_id", None)
        if not isinstance(profile_id, str) or not profile_id:
            profile_id = os.getenv("HH_PROFILE_ID", DEFAULT_PROFILE_ID)
        return profile_id or DEFAULT_PROFILE_ID

    @staticmethod
    def normalize_profile_id(profile_id: str) -> str:
        if not isinstance(profile_id, str):
            raise ProfileValidationError("Имя профиля должно быть строкой")

        profile_id = profile_id.strip()
        if profile_id == DEFAULT_PROFILE_ID:
            return profile_id
        if not profile_id or profile_id == ".." or not _PROFILE_ID_RE.fullmatch(profile_id):
            raise ProfileValidationError(
                "Имя профиля может содержать только буквы, цифры, '.', '_' и '-'"
            )
        return profile_id

    def profile_path(self, profile_id: str) -> Path:
        profile_id = self.normalize_profile_id(profile_id)
        root = self.root
        if profile_id == DEFAULT_PROFILE_ID:
            return root

        path = (root / profile_id).resolve()
        if path.parent != root:
            raise ProfileValidationError("Недопустимый путь профиля")
        return path

    @staticmethod
    def _has_token(path: Path) -> bool:
        config_path = path / CONFIG_FILENAME
        if not config_path.exists():
            return False
        try:
            token = Config(config_path).get("token") or {}
            return bool(token.get("access_token") or token.get("refresh_token"))
        except (OSError, ValueError, TypeError):
            return False

    def list_profiles(self) -> list[dict[str, Any]]:
        root = self.root
        active = self.active_profile_id
        profile_ids = {DEFAULT_PROFILE_ID, active}

        if root.exists():
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                try:
                    profile_ids.add(self.normalize_profile_id(child.name))
                except ProfileValidationError:
                    continue

        ordered = [DEFAULT_PROFILE_ID] + sorted(
            p for p in profile_ids if p != DEFAULT_PROFILE_ID
        )
        return [
            {
                "id": profile_id,
                "name": "Основной" if profile_id == DEFAULT_PROFILE_ID else profile_id,
                "active": profile_id == active,
                "has_token": self._has_token(self.profile_path(profile_id)),
            }
            for profile_id in ordered
        ]

    def create_profile(self, profile_id: str) -> str:
        profile_id = self.normalize_profile_id(profile_id)
        if profile_id == DEFAULT_PROFILE_ID:
            raise ProfileValidationError("Основной профиль уже существует")

        path = self.profile_path(profile_id)
        if path.exists():
            raise ProfileValidationError(f"Профиль '{profile_id}' уже существует")

        path.mkdir(parents=True)
        return profile_id

    def switch_profile(self, profile_id: str) -> str:
        profile_id = self.normalize_profile_id(profile_id)
        path = self.profile_path(profile_id)
        if profile_id != DEFAULT_PROFILE_ID and not path.is_dir():
            raise ProfileValidationError(f"Профиль '{profile_id}' не найден")

        self._dispose_profile_state()
        self._tool.profile_id = profile_id
        path.mkdir(parents=True, exist_ok=True)
        return profile_id

    def delete_profile(self, profile_id: str) -> None:
        profile_id = self.normalize_profile_id(profile_id)
        if profile_id == DEFAULT_PROFILE_ID:
            raise ProfileValidationError("Основной профиль удалить нельзя")
        if profile_id == self.active_profile_id:
            raise ProfileValidationError("Сначала переключитесь на другой профиль")

        path = self.profile_path(profile_id)
        if not path.is_dir():
            raise ProfileValidationError(f"Профиль '{profile_id}' не найден")
        shutil.rmtree(path)

    def _dispose_profile_state(self) -> None:
        state = getattr(self._tool, "__dict__", {})

        if state.get("api_client") is not None:
            save_token = getattr(self._tool, "save_token", None)
            if callable(save_token):
                try:
                    save_token()
                except Exception:
                    pass

        if state.get("session") is not None:
            save_cookies = getattr(self._tool, "save_cookies", None)
            if callable(save_cookies):
                try:
                    save_cookies()
                except Exception:
                    pass

        db = state.get("db")
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

        for name in ("session", "openai_session"):
            session = state.get(name)
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

        for name in _PROFILE_CACHED_PROPERTIES:
            state.pop(name, None)

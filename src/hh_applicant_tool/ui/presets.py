from __future__ import annotations

import json
from typing import Any

from ..storage.repositories.settings import SettingsRepository

PRESET_PREFIX = "_ui_preset:"
LAST_USED_KEY = "_ui_last_used_params"

MAX_NAME_LEN = 100
MAX_PARAMS_BYTES = 64 * 1024


class PresetValidationError(ValueError):
    pass


def _validate_name(name: Any) -> str:
    if not isinstance(name, str):
        raise PresetValidationError("Имя пресета должно быть строкой")
    normalized = name.strip()
    if not normalized:
        raise PresetValidationError("Имя пресета не может быть пустым")
    if len(normalized) > MAX_NAME_LEN:
        raise PresetValidationError(
            f"Имя пресета длиннее {MAX_NAME_LEN} символов"
        )
    if not normalized.isprintable() or ":" in normalized:
        raise PresetValidationError(
            "Имя пресета содержит недопустимые символы"
        )
    return normalized


def _validate_params(params: Any) -> None:
    if not isinstance(params, dict):
        raise PresetValidationError("Параметры должны быть объектом")
    size = len(json.dumps(params, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PARAMS_BYTES:
        raise PresetValidationError(
            f"Размер параметров превышает {MAX_PARAMS_BYTES} байт"
        )


class PresetsManager:
    def __init__(self, settings: SettingsRepository):
        self._settings = settings

    def save(self, name: str, params: dict[str, Any]) -> None:
        normalized = _validate_name(name)
        _validate_params(params)
        self._settings.set_value(f"{PRESET_PREFIX}{normalized}", params)

    def load(self, name: str) -> dict[str, Any] | None:
        try:
            normalized = _validate_name(name)
        except PresetValidationError:
            return None
        return self._settings.get_value(f"{PRESET_PREFIX}{normalized}")

    def delete(self, name: str) -> None:
        try:
            normalized = _validate_name(name)
        except PresetValidationError:
            return
        self._settings.delete_value(f"{PRESET_PREFIX}{normalized}")

    def list_names(self) -> list[str]:
        prefix_len = len(PRESET_PREFIX)
        return [
            key[prefix_len:]
            for key in self._settings.list_keys()
            if key.startswith(PRESET_PREFIX)
        ]

    def save_last_used(self, params: dict[str, Any]) -> None:
        _validate_params(params)
        self._settings.set_value(LAST_USED_KEY, params)

    def load_last_used(self) -> dict[str, Any] | None:
        return self._settings.get_value(LAST_USED_KEY)

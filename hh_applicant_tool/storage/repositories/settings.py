from typing import TypeVar

from ..models.setting import SettingModel
from .base import BaseRepository

Default = TypeVar("Default")


class SettingsRepository(BaseRepository):
    pkey: str = "key"
    model = SettingModel

    def get_key(self, key: str, /, default: Default = None) -> str | Default:
        setting = self.get(key)
        return setting.value if setting else default

    def set_value(self, key: str, value: str) -> None:
        setting = self.model(key=key, value=value)
        self.save(setting)

    def delete_value(self, key: str, /, commit: bool | None = None) -> None:
        setting = self.get(key)
        if setting:
            self.delete(setting, commit=commit)

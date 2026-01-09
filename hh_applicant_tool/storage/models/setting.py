from .base import BaseModel, mapped


class SettingModel(BaseModel):
    key: str
    value: str = mapped(store_json=True)

from .base import BaseModel, mapped


class EmployerModel(BaseModel):
    id: int
    name: str
    type: str | None = None
    description: str | None = None
    site_url: str | None = None
    alternate_url: str | None = None
    area_id: int = mapped(src="area.id", default=None)
    area_name: str = mapped(src="area.name", default=None)

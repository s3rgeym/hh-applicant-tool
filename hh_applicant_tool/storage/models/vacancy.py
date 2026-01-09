from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class VacancyModel(BaseModel):
    id: int
    name: str
    alternate_url: str
    area_id: int = mapped(path="area.id")
    area_name: str = mapped(path="area.name")
    salary_from: int = mapped(path="salary.from", default=None)
    salary_to: int = mapped(path="salary.to", default=None)
    currency: str = mapped(path="salary.currency", default="RUR")
    gross: bool = mapped(path="salary.gross", default=False)

    remote: bool = mapped(
        path="schedule.id",
        transform=lambda v: v == "remote",
        default=False,
    )

    experience: str = mapped(path="experience.id", default=None)
    professional_roles: list[dict] = mapped(
        store_json=True, default_factory=list
    )

    created_at: datetime | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        self.salary_from = self.salary_from or self.salary_to or 0
        self.salary_to = self.salary_to or self.salary_from or 0

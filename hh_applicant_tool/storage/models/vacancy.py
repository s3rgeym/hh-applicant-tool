from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class VacancyModel(BaseModel):
    id: int
    name: str
    alternate_url: str
    area_id: int = mapped(src="area.id")
    area_name: str = mapped(src="area.name")
    salary_from: int = mapped(src="salary.from", default=None)
    salary_to: int = mapped(src="salary.to", default=None)
    currency: str = mapped(src="salary.currency", default=None)
    gross: bool = mapped(src="salary.gross", default=False)

    remote: bool = mapped(
        src="schedule.id",
        parse_src=lambda v: v == "remote",
        default=False,
    )

    experience: str = mapped(src="experience.id", default=None)
    professional_roles: list[dict] = mapped(as_json=True, default_factory=list)

    created_at: datetime | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        self.salary_from = self.salary_from or self.salary_to or 0
        self.salary_to = self.salary_to or self.salary_from or 0

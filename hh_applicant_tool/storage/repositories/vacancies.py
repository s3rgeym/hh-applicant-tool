from __future__ import annotations

from ..models.vacancy import VacancyModel
from .base import BaseRepository


class VacanciesRepository(BaseRepository):
    model = VacancyModel

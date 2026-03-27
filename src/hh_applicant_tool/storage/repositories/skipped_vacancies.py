from __future__ import annotations

from ..models.skipped_vacancy import SkippedVacancyModel
from .base import BaseRepository


class SkippedVacanciesRepository(BaseRepository):   
    __table__ = "skipped_vacancies"
    model = SkippedVacancyModel
    conflict_columns = ("resume_id", "vacancy_id")

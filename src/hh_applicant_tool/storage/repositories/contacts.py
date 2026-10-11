from __future__ import annotations

import logging

from ..models.contacts import VacancyContactsModel
from .base import BaseRepository

logger = logging.getLogger("hh-applicant-tool")


class VacancyContactsRepository(BaseRepository):
    __table__ = "vacancy_contacts"
    model = VacancyContactsModel
    conflict_columns = ("vacancy_id", "email")

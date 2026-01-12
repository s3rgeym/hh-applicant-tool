from __future__ import annotations

import logging

from ..models.contacts import VacancyContactsModel
from .base import BaseRepository

logger = logging.getLogger(__package__)


class VacancyContactsRepository(BaseRepository):
    __table__ = "vacancy_contacts"
    model = VacancyContactsModel
    conflict_columns = ("vacancy_id", "email")

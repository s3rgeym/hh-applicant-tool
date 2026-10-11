from __future__ import annotations

import logging

from ..models.contacts import VacancyContactsModel
from .base import BaseRepository

logger = logging.getLogger(__name__.split(".")[0])


class VacancyContactsRepository(BaseRepository):
    __table__ = "vacancy_contacts"
    model = VacancyContactsModel
    conflict_columns = ("vacancy_id", "email")

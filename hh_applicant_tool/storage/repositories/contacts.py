from __future__ import annotations

import logging

from ..models.contact import EmployerContactModel
from .base import BaseRepository

logger = logging.getLogger(__package__)


class EmployerContactsRepository(BaseRepository):
    model = EmployerContactModel

    def save(self, contact: EmployerContactModel) -> None:
        # logger.debug(contact)
        super().save(
            contact,
            conflict_columns=["employer_id", "email"],
        )

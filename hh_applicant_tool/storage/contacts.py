from __future__ import annotations

import logging
from typing import Any

from .base import BaseRepository

logger = logging.getLogger(__package__)


class EmployerContactsRepository(BaseRepository):
    table = "employer_contacts"

    def save(self, employer_id: int, contacts: dict[str, Any]) -> None:
        phones = contacts.get("phones", [])

        data = {
            "employer_id": employer_id,
            "name": contacts.get("name"),
            "email": contacts.get("email"),
            "phone_numbers": ",".join(
                [p.get("formatted") for p in phones if p.get("number")],
            ),
        }

        sql = """
        INSERT OR IGNORE INTO employer_contacts
            (employer_id, name, email, phone_numbers)
        VALUES
            (:employer_id, :name, :email, :phone_numbers)
        """

        logger.debug(sql)
        self.conn.execute(sql, data)
        self.conn.commit()

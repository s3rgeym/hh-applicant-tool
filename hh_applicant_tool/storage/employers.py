from __future__ import annotations

from typing import Any

from .base import BaseRepository


class EmployersRepository(BaseRepository):
    table = "employers"

    def save(self, employer: dict[str, Any]) -> None:
        data = {
            "id": int(employer["id"]),
            "name": employer.get("name"),
            "type": employer.get("type"),
            "description": employer.get("description"),
            "site_url": employer.get("site_url"),
            "area_id": int(employer.get("area", {}).get("id", 0)),
            "area_name": employer.get("area", {}).get("name"),
            "alternate_url": employer.get("alternate_url"),
        }

        self.upsert_by_id(self.table, data)

from __future__ import annotations

from typing import Any

from ..utils import parse_invalid_datetime
from .base import BaseRepository


class VacanciesRepository(BaseRepository):
    table = "vacancies"

    def save(self, vacancy: dict[str, Any]) -> None:
        salary = vacancy.get("salary") or {}

        data = {
            "id": int(vacancy["id"]),
            "name": vacancy.get("name"),
            "area_id": int(vacancy["area"]["id"]) if vacancy.get("area") else None,
            "area_name": vacancy["area"]["name"] if vacancy.get("area") else None,
            "salary_from": salary.get("from") or salary.get("to"),
            "salary_to": salary.get("to") or salary.get("from"),
            "currency": salary.get("currency"),
            "gross": salary.get("gross"),
            "published_at": parse_invalid_datetime(vacancy["published_at"])
            if "published_at" in vacancy
            else None,
            "created_at": parse_invalid_datetime(vacancy["created_at"])
            if "created_at" in vacancy
            else None,
            "remote": vacancy.get("schedule", {}).get("id") == "remote",
            "expirence": vacancy.get("experience", {}).get("name"),
            "alternate_url": vacancy.get("alternate_url"),
        }

        self.upsert_by_id(self.table, data)

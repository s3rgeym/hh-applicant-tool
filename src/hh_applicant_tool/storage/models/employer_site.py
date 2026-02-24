from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class EmployerSiteModel(BaseModel):
    employer_id: str | int
    site_url: str
    ip_address: str | None = None
    title: str | None = None
    description: str | None = None
    generator: str | None = None
    server_name: str | None = None
    powered_by: str | None = None

    # Трансформируем список в строку через запятую перед сохранением
    emails: str | list[str] = mapped(
        transform=lambda v: ",".join(v) if isinstance(v, list) else v,
        default="",
    )
    subdomains: str | list[str] = mapped(
        transform=lambda v: ",".join(v) if isinstance(v, list) else v,
        default="",
    )

    created_at: datetime | None = None
    updated_at: datetime | None = None

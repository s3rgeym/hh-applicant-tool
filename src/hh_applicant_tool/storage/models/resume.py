from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class ResumeModel(BaseModel):
    id: str
    title: str
    url: str
    alternate_url: str
    status_id: str = mapped(path="status.id")
    status_name: str = mapped(path="status.name")
    can_publish_or_update: bool = False
    total_views: int = mapped(path="counters.total_views", default=0)
    new_views: int = mapped(path="counters.new_views", default=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None

from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class ResumeModel(BaseModel):
    id: str
    title: str
    url: str
    alternate_url: str
    status_id: str = mapped(src="status.id")
    status_name: str = mapped(src="status.name")
    can_publish_or_update: bool = False
    total_views: int = mapped(src="counters.total_views", default=0)
    new_views: int = mapped(src="counters.new_views", default=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None

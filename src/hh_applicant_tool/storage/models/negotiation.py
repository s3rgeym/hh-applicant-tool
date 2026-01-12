from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class NegotiationModel(BaseModel):
    id: int
    chat_id: int
    state: str = mapped(path="state.id")
    vacancy_id: int = mapped(path="vacancy.id")
    employer_id: int = mapped(path="vacancy.employer.id", default=None)
    resume_id: str = mapped(path="resume.id")
    created_at: datetime | None = None
    updated_at: datetime | None = None

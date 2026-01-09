from __future__ import annotations

from datetime import datetime

from .base import BaseModel, mapped


class NegotiationModel(BaseModel):
    id: int
    chat_id: int
    state: str = mapped(src="state.id")
    vacancy_id: int = mapped(src="vacancy.id")
    employer_id: int = mapped(src="vacancy.employer.id", default=None)
    resume_id: str = mapped(src="resume.id")
    created_at: datetime | None = None
    updated_at: datetime | None = None

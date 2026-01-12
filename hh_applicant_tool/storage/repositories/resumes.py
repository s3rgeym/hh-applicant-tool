from __future__ import annotations

from ..models.resume import ResumeModel
from .base import BaseRepository


class ResumesRepository(BaseRepository):
    __table__ = "resumes"
    model = ResumeModel

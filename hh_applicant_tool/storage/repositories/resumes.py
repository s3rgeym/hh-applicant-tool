from __future__ import annotations

import sqlite3

from ..models.resume import ResumeModel
from .base import BaseRepository


class ResumesRepository(BaseRepository):
    """Репозиторий для хранения резюме."""

    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn)
        self.model = ResumeModel

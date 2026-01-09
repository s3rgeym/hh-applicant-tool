from __future__ import annotations

from typing import Iterator

from ..models.employer import EmployerModel
from .base import BaseRepository


class EmployersRepository(BaseRepository):
    model = EmployerModel

    def find(self, **kwargs) -> Iterator[EmployerModel]:
        return super().find(**kwargs)

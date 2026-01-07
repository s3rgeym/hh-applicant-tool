from __future__ import annotations

import sqlite3

from .contacts import EmployerContactsRepository
from .employers import EmployersRepository
from .vacancies import VacanciesRepository


class StorageFacade:
    """Единая точка доступа к persistence-слою."""

    def __init__(self, conn: sqlite3.Connection):
        self.employers = EmployersRepository(conn)
        self.vacancies = VacanciesRepository(conn)
        self.contacts = EmployerContactsRepository(conn)

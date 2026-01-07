from __future__ import annotations

import sqlite3

from .contacts import EmployerContactsRepository
from .employers import EmployersRepository
from .init_db import init_db
from .vacancies import VacanciesRepository


class StorageFacade:
    """Единая точка доступа к persistence-слою."""

    def __init__(self, conn: sqlite3.Connection):
        init_db(conn)
        self.employers = EmployersRepository(conn)
        self.vacancies = VacanciesRepository(conn)
        self.contacts = EmployerContactsRepository(conn)

from __future__ import annotations

import sqlite3

from .repositories.contacts import EmployerContactsRepository
from .repositories.employers import EmployersRepository
from .repositories.negotiations import NegotiationRepository
from .repositories.resumes import ResumesRepository
from .repositories.settings import SettingsRepository
from .repositories.vacancies import VacanciesRepository
from .utils import init_db


class StorageFacade:
    """Единая точка доступа к persistence-слою."""

    def __init__(self, conn: sqlite3.Connection):
        init_db(conn)
        self.employers = EmployersRepository(conn)
        self.vacancies = VacanciesRepository(conn)
        self.employer_contacts = EmployerContactsRepository(conn)
        self.negotiations = NegotiationRepository(conn)
        self.settings = SettingsRepository(conn)
        self.resumes = ResumesRepository(conn)

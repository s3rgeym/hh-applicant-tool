from __future__ import annotations

import sqlite3

from .repositories.contacts import VacancyContactsRepository
from .repositories.employer_sites import EmployerSitesRepository
from .repositories.employers import EmployersRepository
from .repositories.negotiations import NegotiationRepository
from .repositories.resumes import ResumesRepository
from .repositories.settings import SettingsRepository
from .repositories.skipped_vacancies import SkippedVacanciesRepository
from .repositories.vacancies import VacanciesRepository
from .utils import init_db


class StorageFacade:
    """Единая точка доступа к persistence-слою."""

    def __init__(self, conn: sqlite3.Connection):
        init_db(conn)
        self.employer_sites = EmployerSitesRepository(conn)
        self.employers = EmployersRepository(conn)
        self.negotiations = NegotiationRepository(conn)
        self.resumes = ResumesRepository(conn)
        self.settings = SettingsRepository(conn)
        self.skipped_vacancies = SkippedVacanciesRepository(conn)
        self.vacancies = VacanciesRepository(conn)
        self.vacancy_contacts = VacancyContactsRepository(conn)

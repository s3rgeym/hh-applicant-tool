from __future__ import annotations

from ..models.employer_site import EmployerSiteModel
from .base import BaseRepository


class EmployerSitesRepository(BaseRepository):
    __table__ = "employer_sites"
    model = EmployerSiteModel
    conflict_columns = ("employer_id", "site_url")

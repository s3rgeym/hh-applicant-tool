from __future__ import annotations

from logging import getLogger

from ..models.negotiation import NegotiationModel
from .base import BaseRepository

logger = getLogger("hh-applicant-tool")


class NegotiationRepository(BaseRepository):
    __table__ = "negotiations"
    model = NegotiationModel

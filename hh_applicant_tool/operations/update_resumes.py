# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api import ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import PaginatedItems
from ..utils import print_err, shorten

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Обновить все резюме"""

    __aliases__ = ["update"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> None:
        resumes: PaginatedItems = applicant_tool.get_resumes()
        for resume in resumes["items"]:
            try:
                res = applicant_tool.api_client.post(
                    f"/resumes/{resume['id']}/publish",
                )
                assert res == {}
                print("✅ Обновлено", shorten(resume["title"]))
            except ApiError as ex:
                print_err("❗", ex)

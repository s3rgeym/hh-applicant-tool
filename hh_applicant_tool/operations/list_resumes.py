from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from prettytable import PrettyTable

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import PaginatedItems
from ..utils import shorten

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Список резюме"""

    __aliases__ = ("list", "ls")

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> None:
        resumes: PaginatedItems = applicant_tool.get_resumes()
        t = PrettyTable(field_names=["ID", "Название", "Статус"], align="l", valign="t")
        t.add_rows(
            [
                (
                    x["id"],
                    shorten(x["title"]),
                    x["status"]["name"].title(),
                )
                for x in resumes["items"]
            ]
        )
        print(t)

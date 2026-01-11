from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from prettytable import PrettyTable

from ..datatypes import PaginatedItems
from ..main import BaseNamespace, BaseOperation
from ..utils.string import shorten

if TYPE_CHECKING:
    from .. import datatypes
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Список резюме"""

    __aliases__ = ("ls-resumes", "resumes")

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> None:
        resumes: PaginatedItems[datatypes.Resume] = tool.get_resumes()
        storage = tool.storage
        for resume in resumes["items"]:
            storage.resumes.save(resume)

        t = PrettyTable(
            field_names=["ID", "Название", "Статус"], align="l", valign="t"
        )
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
        print(f"\nНайдено резюме: {resumes['found']}")

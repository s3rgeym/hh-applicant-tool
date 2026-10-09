from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api.datatypes import PaginatedItems
from ..tool import BaseNamespace, BaseOperation
from ..utils.string import shorten
from ..utils.table import print_table

if TYPE_CHECKING:
    from ..api import datatypes
    from ..tool import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Список резюме"""

    __aliases__ = ("ls-resumes", "resumes")

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        resumes: PaginatedItems[datatypes.Resume] = tool.get_resumes()
        logger.debug(resumes)
        tool.storage.resumes.save_batch(resumes)

        print_table(
            ["ID", "Название", "Статус"],
            [
                (
                    x["id"],
                    shorten(x["title"]),
                    x["status"]["name"].title(),
                )
                for x in resumes
            ],
        )

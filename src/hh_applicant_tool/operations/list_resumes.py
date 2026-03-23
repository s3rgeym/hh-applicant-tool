from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api.datatypes import PaginatedItems
from ..main import BaseNamespace, BaseOperation
from ..utils.string import shorten
from ..utils.ui import console, make_table

if TYPE_CHECKING:
    from ..api import datatypes
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Список резюме"""

    __aliases__ = ("ls-resumes", "resumes")
    __category__: str = "Резюме"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> None:
        resumes: PaginatedItems[datatypes.Resume] = tool.get_resumes()
        logger.debug(resumes)
        tool.storage.resumes.save_batch(resumes)

        t = make_table("ID", "Название", "Статус", title="Резюме")
        for x in resumes:
            status = ((x.get("status") or {}).get("name") or "—").title()
            status_style = (
                "[hh.ok]" if "публик" in status.lower()
                else "[hh.muted]"
            )
            t.add_row(
                f"[hh.id]{x['id']}[/]",
                shorten(x.get("title") or ""),
                f"{status_style}{status}[/]",
            )
        console.print(t)

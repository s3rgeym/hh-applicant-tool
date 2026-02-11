# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from hh_applicant_tool.api.errors import ApiError

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Проверка браузерной сессии, полученной при авторизации"""

    __aliases__: list[str] = []

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        # parser
        ...

    def run(self, tool: HHApplicantTool) -> None:
        r = tool.session.get("https://stary-oskol.hh.ru/applicant/settings")
        print(r.status_code)

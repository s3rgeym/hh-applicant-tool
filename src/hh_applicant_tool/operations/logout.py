# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from hh_applicant_tool.api.errors import ApiError

from ..tool import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger("hh-applicant-tool")


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выход из профиля"""

    __aliases__: list[str] = ["exit"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool, args: BaseNamespace) -> None:
        try:
            tool.api_client.delete("/oauth/token")
        finally:
            tool.session.cookies.clear()

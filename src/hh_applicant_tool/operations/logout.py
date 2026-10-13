# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..tool import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger("hh-applicant-tool")


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выходит из профиля и удаляет токены, а так же очищает куки"""

    __aliases__: list[str] = ["exit"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool, args: BaseNamespace) -> None:
        tool.logout()

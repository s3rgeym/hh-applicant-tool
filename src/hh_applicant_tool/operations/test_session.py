# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
import re
from typing import TYPE_CHECKING

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
        r = tool.session.get("https://hh.ru")

        if m := re.search(r'^\s+login: "([^"]+)', r.text, re.MULTILINE):
            print("Вы вошли как", m.group(1))
        else:
            logger.warning("Вы не авторизованы!")

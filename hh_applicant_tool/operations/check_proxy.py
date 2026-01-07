# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Проверить прокси"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> None:
        session = applicant_tool.session
        assert session.proxies, "Прокси не заданы"
        print(session.get("https://icanhazip.com").text)

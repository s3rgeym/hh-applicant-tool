from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api import ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..utils import print_err

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Получает новый access_token."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> None:
        applicant_tool.api_client.refresh_access_token()
        print("✅ Токен обновлен!")

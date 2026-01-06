from __future__ import annotations

import argparse
import logging
import sys
from runpy import run_module
from typing import TYPE_CHECKING

from ..main import BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Operation(BaseOperation):
    """Удалит Chromium и другие зависимости"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> None:
        sys.argv = ["playwright", "uninstall", "chromium"]
        run_module("playwright", run_name="__main__")

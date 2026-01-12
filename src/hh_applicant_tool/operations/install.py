from __future__ import annotations

import argparse
import logging
import sys
from runpy import run_module
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Установит Chromium и другие зависимости"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> None:
        orig_argv = sys.argv
        sys.argv = ["playwright", "install", "chromium"]
        try:
            run_module("playwright", run_name="__main__")
        finally:
            sys.argv = orig_argv

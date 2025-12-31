import argparse
import logging
import sys
from runpy import run_module
from typing import Any

from ..main import BaseOperation

logger = logging.getLogger(__package__)


class Operation(BaseOperation):
    """Удалит Chromium"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, *args: Any, **kwargs: Any) -> None:
        sys.argv = ["playwright", "uninstall", "chromium"]
        run_module("playwright", run_name="__main__")

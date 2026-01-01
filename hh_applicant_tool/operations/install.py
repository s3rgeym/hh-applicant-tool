import argparse
import logging
import sys
from runpy import run_module
from typing import Any

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Установит Chromium и другие зависимости"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, *args: Any, **kwargs: Any) -> None:
        sys.argv = ["playwright", "install", "chromium"]
        run_module("playwright", run_name="__main__")

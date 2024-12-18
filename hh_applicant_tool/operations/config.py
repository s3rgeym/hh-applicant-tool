import argparse
import logging
import os
import subprocess

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)

EDITOR = os.getenv("EDITOR", "nano")


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Редактировать конфигурационный файл"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace) -> None:
        config_path = str(args.config._config_path)
        subprocess.call([EDITOR, config_path])

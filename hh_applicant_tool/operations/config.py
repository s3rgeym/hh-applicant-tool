import argparse
import logging
import os
import subprocess

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)

EDITOR = os.getenv("EDITOR", "nano")


class Namespace(BaseNamespace):
    print: bool


class Operation(BaseOperation):
    """Редактировать конфигурационный файл или показать путь до него"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-p",
            "--print",
            type=bool,
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Напечатать путь и выйти",
        )

    def run(self, args: Namespace) -> None:
        config_path = str(args.config._config_path)
        if args.print:
            print(config_path)
        else:
            subprocess.call([EDITOR, config_path])

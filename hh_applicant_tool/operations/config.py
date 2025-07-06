import argparse
import logging
import os
import subprocess
from typing import Any

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)

EDITOR = os.getenv("EDITOR", "nano")


class Namespace(BaseNamespace):
    show_path: bool
    key: str


def get_value(data: dict[str, Any], path: str) -> Any:
    for key in path.split("."):
        if key not in data:
            return None
        data = data[key]
    return data


class Operation(BaseOperation):
    """Операции с конфигурационным файлом"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-p",
            "--show-path",
            "--path",
            type=bool,
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Вывести полный путь к конфигу",
        )
        parser.add_argument("-k", "--key", help="Вывести отдельное значение из конфига")

    def run(self, args: Namespace, *_) -> None:
        if args.key:
            print(get_value(args.config, args.key))
            return
        config_path = str(args.config._config_path)
        if args.show_path:
            print(config_path)
        else:
            subprocess.call([EDITOR, config_path])

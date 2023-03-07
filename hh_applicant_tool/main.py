from __future__ import annotations

import argparse
import dataclasses
import logging
from abc import ABCMeta, abstractmethod
from importlib import import_module
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Sequence

from .color_log import ColorHandler
from .utils import Config

DEFAULT_CONFIG_PATH = (
    Path(getenv("XDG_CONFIG_PATH", Path.home() / ".config"))
    / __package__.replace("_", "-")
    / "config.json"
)

logger = logging.getLogger(__package__)


class BaseOperation(metaclass=ABCMeta):
    def add_parser_arguments(self, parser: argparse.ArgumentParser) -> None:
        ...

    @abstractmethod
    def run(self, args: argparse.Namespace) -> None | int:
        ...


OPERATIONS = "operations"


class Namespace(argparse.Namespace):
    config: Config
    verbosity: int


class HHApplicantTool:
    """Утилита для автоматизации действий соискателя на сайте hh.ru.
    Описание, исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>.
    """

    def parse_args(self, argv: Sequence[str] | None) -> Namespace:
        self._parser = parser = argparse.ArgumentParser(
            description=self.__doc__,
        )
        parser.add_argument(
            "-c",
            "--config",
            help="config path",
            type=Config,
            default=Config(DEFAULT_CONFIG_PATH),
        )
        parser.add_argument(
            "-v",
            "--verbosity",
            help="increase verbosity",
            action="count",
            default=0,
        )
        subparsers = parser.add_subparsers(help="commands")
        package_dir = Path(__file__).resolve().parent / OPERATIONS
        for _, module_name, _ in iter_modules([str(package_dir)]):
            mod = import_module(f"{__package__}.{OPERATIONS}.{module_name}")
            op: BaseOperation = mod.Operation()
            op_parser = subparsers.add_parser(
                module_name.replace("_", "-"), description=op.__doc__
            )
            op_parser.set_defaults(run=op.run)
            op.add_parser_arguments(op_parser)
        parser.set_defaults(run=None)
        return parser.parse_args(argv)

    def run(self, argv: Sequence[str] | None) -> None | int:
        args = self.parse_args(argv)
        log_level = max(logging.DEBUG, logging.WARNING - args.verbosity * 10)
        logger.setLevel(log_level)
        handler = ColorHandler()
        # [C] Critical Error Occurred
        handler.setFormatter(logging.Formatter("[%(levelname).1s] %(message)s"))
        logger.addHandler(handler)
        if args.run:
            try:
                return args.run(args)
            except Exception as e:
                logger.exception(e)
                return 1
        self._parser.print_help()
        return 2


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool().run(argv)

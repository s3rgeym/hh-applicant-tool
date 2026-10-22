from __future__ import annotations

import argparse
import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from ..tool import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger(__name__.split(".")[0])


class Namespace(BaseNamespace):
    key: str | None
    value: str | None
    edit: bool
    delete: str | None
    show_path: bool


def parse_scalar(value: str) -> bool | int | float | str | None:
    match value.lower():
        case "null" | "none" | "nil":
            return None
        case "true":
            return True
        case "false":
            return False
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


class Operation(BaseOperation):
    """
    Операции с конфигурационным файлом.
    По умолчанию выводит содержимое конфига.

    config openai.defaul.model          вывести значение
    config openai.default.model gpt-4o  установить значение
    config -d openai.model              удалить ключ
    """

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser
        parser.add_argument(
            "key",
            nargs="?",
            help="Ключ конфига, например openai.model",
        )
        parser.add_argument(
            "value",
            nargs="?",
            help="Новое значение (если не указано, значение ключа выводится)",
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-e",
            "--edit",
            action="store_true",
            help="Открыть конфигурационный файл в редакторе",
        )
        group.add_argument(
            "-d",
            "--delete",
            "--unset",
            metavar="KEY",
            help="Удалить ключ из конфига",
        )
        group.add_argument(
            "-p",
            "--show-path",
            "--path",
            action="store_true",
            help="Вывести полный путь к конфигу",
        )

    def run(self, applicant_tool: HHApplicantTool, args: Namespace) -> None:
        config = applicant_tool.config

        if args.key and (args.edit or args.delete or args.show_path):
            logger.error("Ключ нельзя сочетать с -e, -d и -p.")
            return 1

        if args.key:
            if args.value is None:
                value = config.get_value(args.key)
                if value is not None:
                    print(value)
            else:
                config.set_value(
                    args.key, parse_scalar(args.value), create=True
                )
                config.save()
                logger.info(
                    "Значение '%s' для ключа '%s' сохранено.",
                    args.value,
                    args.key,
                )
            return

        if args.delete:
            if config.delete_value(args.delete, prune=True):
                config.save()
                logger.info("Ключ '%s' удален из конфига.", args.delete)
            else:
                logger.warning("Ключ '%s' не найден в конфиге.", args.delete)
            return

        if args.show_path:
            print(config.path)
            return

        if args.edit:
            self._open_editor(config.path)
            return

        self.parser.print_help()
        return 2

    def _open_editor(self, filepath: Path) -> None:
        """Открывает файл в редакторе по умолчанию в зависимости от ОС."""
        match platform.system():
            case "Windows":
                os.startfile(filepath)
            case "Darwin":  # macOS
                subprocess.run(["open", filepath], check=True)
            case _:  # Linux и остальные (аналог else)
                editor = os.getenv("EDITOR", "xdg-open")
                subprocess.run([editor, filepath], check=True)

from __future__ import annotations

import argparse
import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..tool import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger("hh-applicant-tool")


class Namespace(BaseNamespace):
    key: str | None
    value: str | None
    edit: bool
    delete: str | None
    show_path: bool


def get_value(data: dict[str, Any], path: str) -> Any:
    for key in path.split("."):
        try:
            data = data.get(key)
        except AttributeError:
            return None
    return data


def set_value(data: dict[str, Any], path: str, value: Any) -> None:
    """Устанавливает значение во вложенном словаре по ключу в виде строки."""
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def del_value(data: dict[str, Any], path: str) -> bool:
    """Удаляет значение из вложенного словаря по ключу в виде строки."""
    keys = path.split(".")
    for key in keys[:-1]:
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]

    try:
        del data[keys[-1]]
        return True
    except (KeyError, TypeError):
        return False


def parse_scalar(value: str) -> bool | int | float | str | None:
    match value.lower():
        case "null":
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

    config                              показать весь конфиг
    config openai.defaul.model          вывести значение
    config openai.default.model gpt-4o  установить значение
    config -d openai.model              удалить ключ
    """

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
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
            return

        if args.key:
            if args.value is None:
                value = get_value(config, args.key)
                if value is not None:
                    print(value)
            else:
                set_value(config, args.key, parse_scalar(args.value))
                config.save()
                logger.info(
                    "Значение '%s' для ключа '%s' сохранено.",
                    args.value,
                    args.key,
                )
            return

        if args.delete:
            if del_value(config, args.delete):
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

        # Default action: show content
        print(config.path.read_text(encoding="utf-8"))

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

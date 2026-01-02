import argparse
import json
import logging
import os
import platform
import subprocess
from typing import Any

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    show_path: bool
    key: str
    set: list[str]
    edit: bool
    unset: str


def get_value(data: dict[str, Any], path: str) -> Any:
    for key in path.split("."):
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


def set_value(data: dict[str, Any], path: str, value: Any) -> None:
    """Устанавливает значение во вложенном словаре по ключу в виде строки."""
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def del_value(data: dict[str, Any], path: str) -> None:
    """Удаляет значение из вложенного словаря по ключу в виде строки."""
    keys = path.split(".")
    for key in keys[:-1]:
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]

    try:
        del data[keys[-1]]
        return True
    except KeyError:
        return False


def parse_scalar(value: str) -> bool | int | float | str:
    if value == "null":
        return None
    if value in ["true", "false"]:
        return "t" in value
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


class Operation(BaseOperation):
    """
    Операции с конфигурационным файлом.
    По умолчанию выводит содержимое конфига.
    """

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-p",
            "--show-path",
            "--path",
            action="store_true",
            help="Вывести полный путь к конфигу",
        )
        group.add_argument(
            "-e",
            "--edit",
            action="store_true",
            help="Открыть конфигурационный файл в редакторе",
        )
        group.add_argument("-k", "--key", help="Вывести отдельное значение из конфига")
        group.add_argument(
            "-s",
            "--set",
            nargs=2,
            metavar=("KEY", "VALUE"),
            help="Установить значение в конфиг, например, --set openai.model gpt-4o",
        )
        group.add_argument(
            "-u", "--unset", metavar="KEY", help="Удалить ключ из конфига"
        )

    def run(self, args: Namespace, *_) -> None:
        if args.set:
            key, value = args.set
            set_value(args.config, key, parse_scalar(value))
            args.config.save()
            logger.info("Значение '%s' для ключа '%s' сохранено.", value, key)
            return

        if args.unset:
            key = args.unset
            if del_value(args.config, key):
                args.config.save()
                logger.info("Ключ '%s' удален из конфига.", key)
            else:
                logger.warning("Ключ '%s' не найден в конфиге.", key)
            return

        if args.key:
            value = get_value(args.config, args.key)
            if value is not None:
                print(value)
            return

        config_path = str(args.config._config_path)
        if args.show_path:
            print(config_path)
            return

        if args.edit:
            self._open_editor(config_path)
            return

        # Default action: show content
        print(json.dumps(args.config, indent=2, ensure_ascii=False))

    def _open_editor(self, filepath: str) -> None:
        """Открывает файл в редакторе по умолчанию в зависимости от ОС."""
        match platform.system():
            case "Windows":
                os.startfile(filepath)
            case "Darwin":  # macOS
                subprocess.run(["open", filepath], check=True)
            case _:  # Linux и остальные (аналог else)
                editor = os.getenv("EDITOR", "xdg-open")
                subprocess.run([editor, filepath], check=True)

import argparse
import ast
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
    view: bool
    unset: str


def get_value(data: dict[str, Any], path: str) -> Any:
    for key in path.split("."):
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
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
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return False  # Key path does not exist

    final_key = keys[-1]
    if isinstance(data, dict) and final_key in data:
        del data[final_key]
        return True
    return False


class Operation(BaseOperation):
    """Операции с конфигурационным файлом"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-p",
            "--show-path",
            "--path",
            action="store_true",
            help="Вывести полный путь к конфигу",
        )
        group.add_argument("-k", "--key", help="Вывести отдельное значение из конфига")
        group.add_argument(
            "-s",
            "--set",
            nargs=2,
            metavar=("KEY", "VALUE"),
            help="Установить значение в конфиге (например, --set openai.model gpt-4o)",
        )
        group.add_argument(
            "-u", "--unset", metavar="KEY", help="Удалить ключ из конфига"
        )
        group.add_argument(
            "-V",
            "--view",
            action="store_true",
            help="Вывести содержимое конфига в консоль",
        )

    def run(self, args: Namespace, *_) -> None:
        if args.view:
            print(json.dumps(args.config, indent=2, ensure_ascii=False))
            return

        if args.set:
            key, value_str = args.set
            try:
                # Пытаемся преобразовать значение в Python-объект (число, bool, etc)
                value = ast.literal_eval(value_str)
            except (ValueError, SyntaxError):
                # Если не получилось, оставляем как есть (строка)
                value = value_str

            set_value(args.config, key, value)
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
        else:
            self._open_editor(config_path)

    def _open_editor(self, filepath: str) -> None:
        """Открывает файл в редакторе по умолчанию в зависимости от ОС."""
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(filepath)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", filepath], check=True)
            else:  # Linux and other Unix-like
                editor = os.getenv("EDITOR")
                if editor:
                    subprocess.run([editor, filepath], check=True)
                else:
                    subprocess.run(["xdg-open", filepath], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("Не удалось открыть редактор. Ошибка: %s", e)
            logger.info("Пожалуйста, откройте файл вручную: %s", filepath)

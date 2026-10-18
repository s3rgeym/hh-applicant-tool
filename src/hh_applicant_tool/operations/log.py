from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from ..tool import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger(__name__.split(".")[0])


class Namespace(BaseNamespace):
    follow: bool


class Operation(BaseOperation):
    """Просмотр и очистка лог-файла"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-f",
            "--follow",
            action="store_true",
            help="Следить за файлом (режим follow, аналог less +F)",
        )
        group.add_argument(
            "--clear",
            action="store_true",
            help="Очистить логи",
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        log_path = tool.log_file

        if not os.path.exists(log_path):
            logger.error("Файл лога не найден: %s", log_path)
            return 1

        if args.clear:
            try:
                # Обрезаем файл, не удаляя его: открытые хендлеры логгера
                # продолжат писать в тот же inode
                with open(log_path, "w", encoding="utf-8"):
                    pass
            except OSError as ex:
                logger.error("Не удалось очистить лог: %s", ex)
                return 1
            logger.info("Лог очищен")
            return None

        if sys.platform == "win32":
            os.startfile(log_path)
            return

        pager = os.getenv("PAGER", "less")
        if not shutil.which(pager):
            logger.error("Не найден просмотрщик '%s'", pager)
            if pager == "less":
                logger.error(
                    'Попробуйте установить less: "sudo apt install less" или "sudo yum install less"'
                )
            return 1

        cmd = [pager]

        if pager == "less":
            # -R позволяет отображать цвета (ANSI codes)
            # -S отключает перенос строк (удобно для логов)
            cmd.extend(["-R", "-S"])
            if args.follow:
                # В less режим слежения включается через команду +F
                cmd.append("+F")

        cmd.append(str(log_path))

        try:
            # Запускаем процесс. check=False, так как выход из pager
            # по Ctrl+C может вернуть ненулевой код.
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            logger.error("Не удалось запустить просмотрщик '%s'", pager)
            return 1
        except KeyboardInterrupt:
            # Обработка прерывания, чтобы не выводить traceback в консоль
            pass

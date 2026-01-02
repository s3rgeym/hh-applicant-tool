# -*- coding: utf-8 -*-
# mypy: disable-error-code=disable-error-code
#
# MyPy не может найти этот модуль, но это нормально
# так как опционально и может быть не установлен
import argparse
import logging
import os
import shutil
import subprocess
import sys

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    follow: bool


class Operation(BaseOperation):
    """Просмотр файла-лога"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        # Изменено на -F для соответствия стандарту less/tail
        parser.add_argument(
            "-f",
            "--follow",
            action="store_true",
            help="Следить за файлом (режим follow, аналог less +F)",
        )

    def run(self, args: Namespace, _, __) -> None:
        log_path = args.log_file

        if not os.path.exists(log_path):
            logger.error("Файл лога не найден: %s", log_path)
            return 1

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

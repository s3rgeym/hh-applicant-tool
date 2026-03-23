from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Установит Chromium и другие зависимости"""

    __category__: str = "Утилиты"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, applicant_tool: HHApplicantTool) -> int | None:
        import subprocess

        from ..utils.ui import err, info, ok

        # Шаг 1: pip install playwright (если не установлен)
        try:
            import playwright  # noqa: F401
            info("playwright уже установлен, пропускаем pip install")
        except ImportError:
            info("Устанавливаю playwright...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                check=False,
            )
            if result.returncode != 0:
                err("Не удалось установить playwright через pip.")
                return 1
            ok("playwright установлен.")

        # Шаг 2: playwright install chromium
        info("Устанавливаю Chromium...")
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
        )
        if result.returncode != 0:
            err("Не удалось установить Chromium.")
            return 1

        ok("Chromium установлен. Теперь можно авторизоваться:\n\n  hh-applicant-tool authorize")

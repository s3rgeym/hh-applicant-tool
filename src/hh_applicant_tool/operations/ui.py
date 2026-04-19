from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    debug: bool


class Operation(BaseOperation):
    """Запуск локального веб-интерфейса.

    Открывает нативное окно с HTML-интерфейсом для управления
    инструментом без использования командной строки.

    Требует установки: pip install 'hh-applicant-tool[ui]'
    """

    def setup_parser(self, parser):
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Включить DevTools в окне (для разработки)",
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None | int:
        try:
            import webview  # noqa: F401
        except ImportError:
            logger.error(
                "pywebview не установлен. Установите командой:\n\n"
                "  pip install 'hh-applicant-tool[ui]'\n\n"
                "или:\n\n"
                "  poetry install -E ui"
            )
            return 1

        from ..ui import create_window

        create_window(tool, debug=args.debug)

from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation
from ..utils.ui import err, info, ok, warn

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Обновляет access_token и refresh_token в случае необходимости."""

    __aliases__ = ["refresh"]
    __category__: str = "Авторизация"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> None:
        if tool.api_client.is_access_expired:
            tool.api_client.refresh_access_token()
            if not tool.save_token():
                warn("Токен не был обновлен!")
                return 1
            ok("Токен успешно обновлен.")
        else:
            info("Токен не истек, обновление не требуется.")
            return 2

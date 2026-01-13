from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Получает новый access_token."""

    __aliases__ = ["refresh"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> None:
        if tool.api_client.is_access_expired:
            tool.api_client.refresh_access_token()
            if not tool.save_token():
                print("⚠️ Токен не был обновлен!")
                return 1
            print("✅ Токен успешно обновлен.")
        else:
            logger.debug("Токен валиден, игнорируем обновление.")
            print("ℹ️ Токен не истек, обновление не требуется.")

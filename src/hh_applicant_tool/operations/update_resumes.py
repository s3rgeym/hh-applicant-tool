# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api import ApiError, datatypes
from ..main import BaseNamespace, BaseOperation
from ..utils.string import shorten

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Обновить все резюме"""

    __aliases__ = ["update"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> None:
        resumes: list[datatypes.Resume] = tool.get_resumes()
        # Там вызов API меняет поля
        tool.storage.resumes.save_batch(resumes)

        for resume in resumes:
            if not resume.get("can_publish_or_update"):
                logger.warning(f"Не могу обновить: {resume['alternate_url']}")
                continue
            try:
                r = tool.api_client.post(
                    f"/resumes/{resume['id']}/publish",
                )
                assert {} == r
                print(
                    "✅ Обновлено",
                    resume["alternate_url"],
                    "-",
                    shorten(resume["title"]),
                )
            except ApiError as ex:
                logger.error(f"Ошибка при обновлении резюме: {ex}")

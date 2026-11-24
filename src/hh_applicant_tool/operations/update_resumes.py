# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from hh_applicant_tool.utils.log import logger

from ..api import ApiError, datatypes
from ..tool import BaseNamespace, BaseOperation
from ..utils.string import shorten

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Обновить все резюме"""

    __aliases__: list[str] = []

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool, args: BaseNamespace) -> None:
        resumes: list[datatypes.Resume] = tool.get_resumes()
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

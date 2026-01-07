from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api.errors import ApiError
from ..main import BaseNamespace, BaseOperation
from ..types import NegotiationState

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    older_than: int
    blacklist_discard: bool
    cleanup: bool
    dry_run: bool


class Operation(BaseOperation):
    """Чистит отклики"""

    __aliases__ = ["clean-negotians", "clean"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-b",
            "--blacklist-discard",
            action=argparse.BooleanOptionalAction,
            help="Блокировать работодателя за отказ",
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            help="Тестовый запуск без реального удаления",
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        self.applicant_tool = applicant_tool
        self.args = applicant_tool.args
        self.cleanup()

    def cleanup(self) -> None:
        for negotiation in self.applicant_tool.get_negotiations():
            state_id: NegotiationState = negotiation["state"]["id"]
            if contacts := negotiation["vacancy"].get("contacts"):
                logger.info("Найдены контакты: %r", contacts)
            if state_id != "discard":
                continue
            try:
                if not self.args.dry_run:
                    self.applicant_tool.api_client.delete(
                        f"/negotiations/active/{negotiation['id']}",
                        with_decline_message=True,
                    )

                vacancy = negotiation["vacancy"]
                print(
                    "🗑️ Отменили отклик на вакансию:",
                    vacancy["name"],
                    vacancy["alternate_url"],
                )

                employer = vacancy.get("employer", {})
                if (employer_id := employer.get("id")) and self.args.blacklist_discard:
                    if not self.args.dry_run:
                        self.applicant_tool.api_client.put(
                            f"/employers/blacklisted/{employer_id}"
                        )

                    print(
                        "🚫 Работодатель заблокирован:",
                        employer["name"],
                        employer["alternate_url"],
                    )
            except ApiError as err:
                logger.error(err)

        print("✅ Отклики удалены.")

from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api.errors import ApiError
from ..datatypes import NegotiationStateId
from ..main import BaseNamespace, BaseOperation
from ..storage.models.negotiation import NegotiationModel

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    cleanup: bool
    blacklist_discard: bool
    dry_run: bool


class Operation(BaseOperation):
    """Синхронизирует отклики с локальной базой и опционально удаляет отказы."""

    __aliases__ = ["sync-negotians", "sync"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--cleanup",
            "--clean",
            action=argparse.BooleanOptionalAction,
            help="Удалить отклики с отказами",
        )
        parser.add_argument(
            "-b",
            "--blacklist-discard",
            "--blacklist",
            action=argparse.BooleanOptionalAction,
            help="Блокировать работодателя за отказ",
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            help="Тестовый запуск без реального удаления",
        )

    def run(self, tool: HHApplicantTool) -> None:
        self.tool = tool
        self.args = tool.args
        self._sync()

    def _sync(self) -> None:
        storage = self.tool.storage
        for negotiation in self.tool.get_negotiations():
            storage.negotiations.save(
                NegotiationModel.from_api(negotiation),
            )
            # if vacancy := negotiation.get("vacancy"):
            #     storage.vacancies.save(VacancyModel.from_api(vacancy))
            #     if employer := vacancy.get("employer"):
            #         storage.employers.save(EmployerModel.from_api(employer))
            #     if vacancy.get("contacts"):
            #         storage.contacts.save(EmployerContactModel.from_api(vacancy))

            state_id: NegotiationStateId = negotiation["state"]["id"]
            if not self.args.cleanup:
                continue
            if state_id != "discard":
                continue
            try:
                if not self.args.dry_run:
                    self.tool.api_client.delete(
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
                if (
                    employer_id := employer.get("id")
                ) and self.args.blacklist_discard:
                    if not self.args.dry_run:
                        self.tool.api_client.put(
                            f"/employers/blacklisted/{employer_id}"
                        )

                    print(
                        "🚫 Работодатель заблокирован:",
                        employer["name"],
                        employer["alternate_url"],
                    )
            except ApiError as err:
                logger.error(err)

        print("✅ Синхронизация завершена.")

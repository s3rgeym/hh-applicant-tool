from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api.errors import ApiError
from ..datatypes import NegotiationStateId
from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    cleanup: bool
    blacklist_discard: bool
    dry_run: bool


class Operation(BaseOperation):
    """Проверяет и синхронизирует отклики с локальной базой и опционально удаляет отказы."""

    __aliases__ = ["sync-negotiations"]

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
            vacancy = negotiation["vacancy"]
            employer = vacancy.get("employer", {})
            employer_id = employer.get("id")

            # Если работодателя блокируют, то он превращается в null
            # ХХ позволяет скрывать компанию, когда id нет, а вместо имени "Крупная российская компания"
            # sqlite3.IntegrityError: NOT NULL constraint failed: negotiations.employer_id
            if employer_id:
                storage.negotiations.save(negotiation)

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

                print(
                    "🗑️ Отменили отклик на вакансию:",
                    vacancy["name"],
                    vacancy["alternate_url"],
                )

                if (
                    employer_id
                    and employer_id not in self.args.blacklist_discard
                ):
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

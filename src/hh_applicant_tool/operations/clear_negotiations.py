from __future__ import annotations

import argparse
import datetime as dt
import logging
from typing import TYPE_CHECKING

import requests

from ..api.errors import ApiError
from ..main import BaseNamespace, BaseOperation
from ..utils.date import parse_api_datetime

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    cleanup: bool
    blacklist_discard: bool
    older_than: int
    dry_run: bool
    delete_chat: bool
    block_ats: bool


class Operation(BaseOperation):
    """Удалить отказы и/или старые отклики. Опционально так же удаляет чаты и блокирует работодателей. Из-за особенностей API эту команду иногда нужно вызывать больше одного раза."""

    __aliases__ = ["clear-negotiations", "delete-negotiations"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-b",
            "--blacklist-discard",
            "--blacklist",
            action=argparse.BooleanOptionalAction,
            help="Блокировать работодателя за отказ",
        )
        parser.add_argument(
            "-o",
            "--older-than",
            type=int,
            help="Удаляет любые отклики старше N дней",
        )
        parser.add_argument(
            "-d",
            "--delete-chat",
            action="store_true",
            help="Удалить так же чат",
        )
        parser.add_argument(
            "--block-ats", action="store_true", help="Блокировать ATS"
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            action="store_true",
            help="Тестовый запуск без реального удаления",
        )

    def run(self, tool: HHApplicantTool) -> None:
        self.tool = tool
        self.args = tool.args
        self.clear()

    def delete_chat(self, topic: int | str) -> bool:
        """Чат можно удалить только через веб-версию"""
        headers = {
            "X-Hhtmfrom": "main",
            "X-Hhtmsource": "negotiation_list",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": self.tool.xsrf_token,
            "Refrerer": "https://hh.ru/applicant/negotiations?hhtmFrom=main&hhtmFromLabel=header",
        }

        payload = {
            "topic": topic,
            "query": "?hhtmFrom=main&hhtmFromLabel=header",
            "substate": "HIDE",
        }

        try:
            r = self.tool.session.post(
                "https://hh.ru/applicant/negotiations/trash",
                payload,
                headers=headers,
            )
            r.raise_for_status()
            return True
        except requests.RequestException as ex:
            logger.error(ex)
            return False

    def clear(self) -> None:
        blacklisted = set(self.tool.get_blacklisted())
        for negotiation in self.tool.get_negotiations():
            vacancy = negotiation["vacancy"]

            # Если работодателя блокируют, то он превращается в null
            # ХХ позволяет скрывать компанию, когда id нет, а вместо имени "Крупная российская компания"
            # sqlite3.IntegrityError: NOT NULL constraint failed: negotiations.employer_id
            # try:
            #     storage.negotiations.save(negotiation)
            # except RepositoryError as e:
            #     logger.exception(e)

            # print(negotiation)
            # raise RuntimeError()

            if self.args.older_than:
                updated_at = parse_api_datetime(negotiation["updated_at"])
                # А хз какую временную зону сайт возвращает
                days_passed = (
                    dt.datetime.now(updated_at.tzinfo) - updated_at
                ).days
                logger.debug(f"{days_passed = }")
                if days_passed <= self.args.older_than:
                    continue
            elif negotiation["state"]["id"] != "discard":
                continue

            try:
                logger.debug(
                    "Пробуем отменить отклик на %s", vacancy["alternate_url"]
                )

                if not self.args.dry_run:
                    self.tool.api_client.delete(
                        f"/negotiations/active/{negotiation['id']}",
                        with_decline_message=negotiation["state"]["id"]
                        != "discard",
                    )

                    print(
                        "❌ Отменили отклик на вакансию:",
                        vacancy["alternate_url"],
                        vacancy["name"],
                    )

                if self.args.delete_chat:
                    logger.debug(
                        "Пробуем удалить чат с откликом на вакансию %s",
                        vacancy["alternate_url"],
                    )

                    if not self.args.dry_run:
                        if self.delete_chat(negotiation["id"]):
                            print(f"❌ Удалили чат #{negotiation['id']}")

                d = parse_api_datetime(
                    negotiation["updated_at"]
                ) - parse_api_datetime(negotiation["created_at"])

                logger.debug("Ответ на отклик пришел через %d сек.", d.seconds)

                ats_detected = d.seconds <= 16 * 60

                if ats_detected:
                    logger.info(
                        "Признаки использования ATS компанией: %s (%s)",
                        vacancy["employer"]["name"],
                        vacancy["employer"]["alternate_url"],
                    )

                employer = vacancy.get("employer", {})
                employer_id = employer.get("id")

                if (
                    (
                        self.args.blacklist_discard
                        or (self.args.block_ats and ats_detected)
                    )
                    and employer
                    and employer_id
                    and employer_id not in blacklisted
                ):
                    logger.debug(
                        "Пробуем заблокировать работодателя %s %s",
                        employer["alternate_url"],
                        employer["name"],
                    )

                    if not self.args.dry_run:
                        self.tool.api_client.put(
                            f"/employers/blacklisted/{employer_id}"
                        )
                        blacklisted.add(employer_id)

                        print(
                            "💀 Работодатель заблокирован:",
                            employer["alternate_url"],
                            employer["name"],
                        )
            except ApiError as err:
                logger.error(err)

        print("✅ Удаление откликов завершено.")

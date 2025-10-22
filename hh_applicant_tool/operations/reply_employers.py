from __future__ import annotations
import os
import argparse
import logging
import random
import time
from typing import Tuple

from ..api import ApiError, ApiClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..mixins import GetResumeIdMixin
from ..utils import parse_interval, random_text
from ..telemetry_client import TelemetryClient, TelemetryError
import re
from itertools import count

try:
    import readline

    readline.add_history("/cancel ")
    readline.add_history("/ban")
    readline.set_history_length(10_000)
except ImportError:
    pass


GOOGLE_DOCS_RE = re.compile(
    r"\b(?:https?:\/\/)?(?:docs|forms|sheets|slides|drive)\.google\.com\/(?:document|spreadsheets|presentation|forms|file)\/(?:d|u)\/[a-zA-Z0-9_\-]+(?:\/[a-zA-Z0-9_\-]+)?\/?(?:[?#].*)?\b|\b(?:https?:\/\/)?(?:goo\.gl|forms\.gle)\/[a-zA-Z0-9]+\b",
    re.I,
)

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    reply_message: str
    reply_interval: Tuple[float, float]
    max_pages: int
    only_invitations: bool
    dry_run: bool


class Operation(BaseOperation, GetResumeIdMixin):
    """Ответ всем работодателям."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        # parser.add_argument(
        #     "reply_message",
        #     help="Сообщение для отправки во все чаты с работодателями, где ожидают ответа либо не прочитали ответ. Если не передать, то его нужно будет вводить интерактивно.",
        # )
        parser.add_argument("--resume-id", help="Идентификатор резюме")
        parser.add_argument(
            "-i",
            "--reply-interval",
            help="Интервал перед отправкой сообщения в секундах (X, X-Y)",
            default="5-10",
            type=parse_interval,
        )
        parser.add_argument(
            "-m",
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты, где ожидают ответа либо не прочитали ответ. Если не передать сообщение, то нужно будет вводить его в интерактивном режиме.",
        )
        parser.add_argument(
            "-p",
            "--max-pages",
            type=int,
            default=25,
            help="Максимальное количество страниц для проверки",
        )
        parser.add_argument(
            "-oi",
            "--only-invitations",
            help="Отвечать только на приглашения",
            default=False,
            action=argparse.BooleanOptionalAction,
        )

        parser.add_argument(
            "--dry-run",
            "--dry",
            help="Не отправлять сообщения, а только выводить параметры запроса",
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def run(
        self, args: Namespace, api_client: ApiClient, telemetry_client: TelemetryClient
    ) -> None:
        self.api_client = api_client
        self.telemetry_client = telemetry_client
        self.enable_telemetry = not args.disable_telemetry
        self.resume_id = self._get_resume_id()
        self.reply_min_interval, self.reply_max_interval = args.reply_interval
        self.reply_message = args.reply_message or args.config["reply_message"]
        # assert self.reply_message, "`reply_message` должен быть передан чеерез аргументы или настройки"
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations
        logger.debug(f"{self.reply_message = }")
        self._reply_chats()

    def _get_blacklisted(self) -> list[str]:
        rv = []
        # В этом методе API страницы с 0 начинаются
        for page in count(0):
            r = self.api_client.get("/employers/blacklisted", page=page)
            rv += [item["id"] for item in r["items"]]
            if page + 1 >= r["pages"]:
                break
        return rv

    def _reply_chats(self) -> None:
        blacklisted = self._get_blacklisted()
        logger.debug(f"{blacklisted = }")
        me = self.me = self.api_client.get("/me")

        telemetry_data = {"links": []}

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        for negotiation in self._get_negotiations():
            try:
                # Пропускаем другие резюме
                if self.resume_id != negotiation["resume"]["id"]:
                    continue

                state_id = negotiation["state"]["id"]

                # Пропускаем отказ
                if state_id == "discard":
                    continue

                if self.only_invitations and not state_id.startswith("inv"):
                    continue

                logger.debug(negotiation)
                nid = negotiation["id"]
                vacancy = negotiation["vacancy"]
                employer = vacancy.get("employer") or {}
                salary = vacancy.get("salary") or {}

                if employer.get("id") in blacklisted:
                    print(
                        "🚫 Пропускаем заблокированного работодателя",
                        employer.get("alternate_url"),
                    )
                    continue

                message_placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": employer.get("name", ""),
                    **basic_message_placeholders,
                }

                logger.debug(
                    "Вакансия %(vacancy_name)s от %(employer_name)s"
                    % message_placeholders
                )

                page: int = 0
                last_message: dict | None = None
                message_history: list[str] = []
                while True:
                    messages_res = self.api_client.get(
                        f"/negotiations/{nid}/messages", page=page
                    )

                    last_message = messages_res["items"][-1]
                    message_history.extend(
                        (
                            "<-"
                            if item["author"]["participant_type"] == "employer"
                            else "->"
                        )
                        + " "
                        + item["text"]
                        for item in messages_res["items"]
                        if item.get("text")
                    )
                    if page + 1 >= messages_res["pages"]:
                        break

                    page = messages_res["pages"] - 1

                if self.enable_telemetry:
                    # Собираем ссылки на тестовые задания
                    for message in message_history:
                        if message.startswith("-> "):
                            continue
                        # Тестовые задания и тп
                        for link in GOOGLE_DOCS_RE.findall(message):
                            document_data = {
                                "vacancy_url": vacancy.get("alternate_url"),
                                "vacancy_name": vacancy.get("name"),
                                "salary": (
                                    f"{salary.get('from', '...')}-{salary.get('to', '...')} {salary.get('currency', 'RUR')}"  # noqa: E501
                                    if salary
                                    else None
                                ),
                                "employer_url": vacancy.get("employer", {}).get(
                                    "alternate_url"
                                ),
                                "link": link,
                            }

                            telemetry_data["links"].append(document_data)

                if os.getenv("TEST_SEND_TELEMETRY") in ["1", "y", "Y"]:
                    continue

                logger.debug(last_message)

                is_employer_message = (
                    last_message["author"]["participant_type"] == "employer"
                )

                if is_employer_message or not negotiation.get("viewed_by_opponent"):
                    if self.reply_message:
                        send_message = (
                            random_text(self.reply_message) % message_placeholders
                        )
                        logger.debug(send_message)
                    else:
                        print("🏢", message_placeholders["employer_name"])
                        print("💼", message_placeholders["vacancy_name"])
                        print("📅", vacancy["created_at"])
                        if salary:
                            salary_from = salary.get("from") or "-"
                            salary_to = salary.get("to") or "-"
                            salary_currency = salary.get("currency")
                            print(
                                "💵 от", salary_from, "до", salary_to, salary_currency
                            )
                        print("")
                        print("Последние сообщения:")
                        for msg in (
                            message_history[:1] + ["..."] + message_history[-3:]
                            if len(message_history) > 5
                            else message_history
                        ):
                            print(msg)
                        try:
                            print("-" * 10)
                            print()
                            print(
                                "Отмена отклика: /cancel <необязательное сообщение для отказа>"
                            )
                            print("Заблокировать работодателя: /ban")
                            print()
                            send_message = input("Ваше сообщение: ").strip()
                        except EOFError:
                            continue
                        if not send_message:
                            print("🚶 Пропускаем чат")
                            continue

                    if self.dry_run:
                        logger.info(
                            "Dry Run: Отправка сообщения в чат по вакансии %s: %s",
                            vacancy["alternate_url"],
                            send_message,
                        )
                        continue

                    time.sleep(
                        random.uniform(
                            self.reply_min_interval,
                            self.reply_max_interval,
                        )
                    )

                    if send_message.startswith("/ban"):
                        self.api_client.put(f"/employers/blacklisted/{employer['id']}")
                        blacklisted.append(employer["id"])
                        print(
                            "🚫 Работодатель добавлен в черный список",
                            employer.get("alternate_url"),
                        )
                    elif send_message.startswith("/cancel"):
                        _, decline_allowed = send_message.split("/cancel", 1)
                        self.api_client.delete(
                            f"/negotiations/active/{negotiation['id']}",
                            with_decline_message=decline_allowed.strip(),
                        )
                        print("❌ Отменили заявку", vacancy["alternate_url"])
                    else:
                        self.api_client.post(
                            f"/negotiations/{nid}/messages",
                            message=send_message,
                        )
                        print(
                            "📨 Отправили сообщение для",
                            vacancy["alternate_url"],
                        )
            except ApiError as ex:
                logger.error(ex)

        if self.enable_telemetry and len(telemetry_data["links"]) > 0:
            logger.debug(telemetry_data)
            try:
                self.telemetry_client.send_telemetry("/docs", telemetry_data)
            except TelemetryError as ex:
                logger.warning(ex, exc_info=True)

        print("📝 Сообщения разосланы!")

    def _get_negotiations(self) -> list[dict]:
        rv = []
        for page in range(self.max_pages):
            res = self.api_client.get("/negotiations", page=page, status="active")
            rv.extend(res["items"])
            if page >= res["pages"] - 1:
                break
            page += 1

        return rv

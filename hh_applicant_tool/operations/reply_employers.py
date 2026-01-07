from __future__ import annotations

import argparse
import logging
import random
import re
from typing import TYPE_CHECKING

from ..api import ApiError
from ..main import BaseNamespace, BaseOperation
from ..utils import rand_text

if TYPE_CHECKING:
    from ..main import HHApplicantTool


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
    max_pages: int
    only_invitations: bool
    dry_run: bool


class Operation(BaseOperation):
    """Ответ всем работодателям."""

    __aliases__ = ["reply"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        # parser.add_argument(
        #     "reply_message",
        #     help="Сообщение для отправки во все чаты с работодателями, где ожидают ответа либо не прочитали ответ. Если не передать, то его нужно будет вводить интерактивно.",  # noqa: E501
        # )
        parser.add_argument("--resume-id", help="Идентификатор резюме")
        parser.add_argument(
            "-m",
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты, где ожидают ответа либо не прочитали ответ. Если не передать сообщение, то нужно будет вводить его в интерактивном режиме.",  # noqa: E501
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

    def run(self, applicant_tool: HHApplicantTool) -> None:
        args = applicant_tool.args
        self.applicant_tool = applicant_tool
        self.api_client = applicant_tool.api_client
        self.resume_id = applicant_tool.first_resume_id()
        self.reply_message = args.reply_message or applicant_tool.config.get(
            "reply_message"
        )
        # assert self.reply_message, "`reply_message` должен быть передан через аргументы или настройки"  # noqa: E501
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations
        logger.debug(f"{self.reply_message = }")
        self.reply_chats()

    def reply_chats(self) -> None:
        blacklisted = self.applicant_tool.get_blacklisted()
        logger.debug(f"{blacklisted = }")
        me = self.me = self.applicant_tool.get_me()

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        for negotiation in self.applicant_tool.get_negotiations():
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

                logger.debug(last_message)

                is_employer_message = (
                    last_message["author"]["participant_type"] == "employer"
                )

                if is_employer_message or not negotiation.get("viewed_by_opponent"):
                    if self.reply_message:
                        send_message = (
                            rand_text(self.reply_message) % message_placeholders
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
                            delay=random.uniform(1, 3),
                        )
                        print(
                            "📨 Отправили сообщение для",
                            vacancy["alternate_url"],
                        )
            except ApiError as ex:
                logger.error(ex)

        print("📝 Сообщения разосланы!")

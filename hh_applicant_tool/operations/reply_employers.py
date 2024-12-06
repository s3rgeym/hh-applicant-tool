import argparse
import logging
import random
import time
from typing import Tuple

from ..api import ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..main import get_api
from ..mixins import GetResumeIdMixin
from ..utils import parse_interval, random_text

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
            help="Отправить сообщение во все чаты, где ожидают ответа либо не прочитали ответ. Еслм не передать сообщение, то нужно будет вводить его в интерактивном режиме.",
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

    def run(self, args: Namespace) -> None:
        self.api = get_api(args)
        self.resume_id = self._get_resume_id()
        self.reply_min_interval, self.reply_max_interval = args.reply_interval
        self.reply_message = args.reply_message or args.config["reply_message"]
        # assert self.reply_message, "`reply_message` должен быть передан чеерез аргументы или настройки"
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations
        logger.debug(f"{self.reply_message = }")
        self._reply_chats()

    def _reply_chats(self) -> None:
        me = self.me = self.api.get("/me")

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
                salary = vacancy.get("salary") or {}

                message_placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": vacancy.get("employer", {}).get("name", ""),
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
                    messages_res = self.api.get(
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
                        message = random_text(self.reply_message) % message_placeholders
                        logger.debug(message)
                    else:
                        print("🏢", message_placeholders["employer_name"])
                        print("💼", message_placeholders["vacancy_name"])
                        print("📅", vacancy["created_at"])
                        if salary:
                            salary_from = salary.get("from")or "-"
                            salary_to = salary.get("to")or "-"
                            salary_currency = salary.get("currency")
                            print("💵 от", salary_from, "до", salary_to, salary_currency)
                        print("")
                        print("Последние сообщения:")
                        for msg in (
                            message_history[:1] + ["..."] + message_history[-3:]
                            if len(message_history) > 5
                            else message_history
                        ):
                            print(msg)
                        print("-" * 10)
                        message = input("Ваше сообщение: ").strip()
                        if not message:
                            print("🚶 Пропускаем чат")
                            continue

                    if self.dry_run:
                        logger.info(
                            "Dry Run: Отправка сообщения в чат по вакансии %s: %s",
                            vacancy["alternate_url"],
                            message,
                        )
                        continue

                    time.sleep(
                        random.uniform(
                            self.reply_min_interval,
                            self.reply_max_interval,
                        )
                    )
                    self.api.post(
                        f"/negotiations/{nid}/messages",
                        message=message,
                    )
                    print(
                        "📨 Отправили сообщение для",
                        vacancy["alternate_url"],
                    )
            except ApiError as ex:
                logger.error(ex)

        print("📝 Сообщения разосланы!")

    def _get_negotiations(self) -> list[dict]:
        rv = []
        for page in range(self.max_pages):
            res = self.api.get("/negotiations", page=page, status="active")
            rv.extend(res["items"])
            if page >= res["pages"] - 1:
                break
            page += 1

        return rv

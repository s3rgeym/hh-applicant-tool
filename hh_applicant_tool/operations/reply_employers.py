import argparse
import logging
import random
import time
from typing import Tuple

from ..api import ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace, get_api
from ..utils import parse_interval, random_text
from ..mixins import GetResumeIdMixin

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    reply_message: str
    reply_interval: Tuple[float, float]
    max_pages: int
    dry_run: bool


class Operation(BaseOperation, GetResumeIdMixin):
    """Ответ всем работодателям."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "reply_message",
            help="Сообщение для отправки во все чаты с работодателями, где ожидают ответа либо не прочитали ответ",
        )
        parser.add_argument('--resume-id', help="Идентификатор резюме")
        parser.add_argument(
            "--reply-interval",
            help="Интервал перед отправкой сообщения в секундах (X, X-Y)",
            default="5-10",
            type=parse_interval,
        )
        parser.add_argument(
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты, где ожидают ответа либо не прочитали ответ",
        )
        parser.add_argument('--max-pages', type=int, default=25, help='Максимальное количество страниц для проверки')
        parser.add_argument(
            "--dry-run",
            help="Не отправлять сообщения, а только выводить параметры запроса",
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def run(self, args: Namespace) -> None:
        self.api = get_api(args)
        self.resume_id = self._get_resume_id()
        self.reply_min_interval, self.reply_max_interval = args.reply_interval
        self.reply_message = args.reply_message
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        logger.debug(f'{self.reply_message = }')
        self._reply_chats()

    def _reply_chats(self) -> None:
        me =self.me= self.api.get("/me")

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        for negotiation in self._get_negotiations():
            try:
                # Пропускаем другие резюме
                if self.resume_id != negotiation['resume']['id']:
                    continue

                nid = negotiation["id"]
                vacancy = negotiation["vacancy"]

                message_placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": vacancy.get("employer", {}).get(
                        "name", ""
                    ),
                    **basic_message_placeholders,
                }

                logger.debug(
                    "Вакансия %(vacancy_name)s от %(employer_name)s"
                    % message_placeholders
                )

                page: int = 0
                last_message: dict | None = None
                while True:
                    messages_res = self.api.get(
                        f"/negotiations/{nid}/messages", page=page
                    )
                    last_message = messages_res["items"][-1]
                    if page + 1 >= messages_res["pages"]:
                        break

                    page = messages_res["pages"] - 1

                logger.debug(last_message["text"])

                if last_message["author"][
                    "participant_type"
                ] == "employer" or not negotiation.get(
                    "viewed_by_opponent"
                ):
                    message = (
                        random_text(self.reply_message)
                        % message_placeholders
                    )
                    logger.debug(message)

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
            res = self.api.get("/negotiations", page=page, status='active')
            rv.extend(res["items"])
            if page >= res["pages"] - 1:
                break
            page += 1

        return rv

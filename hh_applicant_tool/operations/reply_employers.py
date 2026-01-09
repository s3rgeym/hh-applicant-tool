from __future__ import annotations

import argparse
import logging
import random
from typing import TYPE_CHECKING

from .. import datatypes
from ..ai.base import AIError
from ..api import ApiError
from ..main import BaseNamespace, BaseOperation
from ..utils.dateutil import parse_api_datetime
from ..utils.string import rand_text

if TYPE_CHECKING:
    from ..main import HHApplicantTool


try:
    import readline

    readline.add_history("/cancel ")
    readline.add_history("/ban")
    readline.set_history_length(10_000)
except ImportError:
    pass


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    reply_message: str
    max_pages: int
    only_invitations: bool
    dry_run: bool
    use_ai: bool
    first_prompt: str
    prompt: str


class Operation(BaseOperation):
    """Ответ всем работодателям."""

    __aliases__ = ["reply-chats", "reply-all"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентификатор резюме")
        parser.add_argument(
            "-m",
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты. Если не передать сообщение, то нужно будет вводить его в интерактивном режиме.",  # noqa: E501
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
        parser.add_argument(
            "--use-ai",
            "--ai",
            help="Использовать AI для автоматической генерации ответов",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--first-prompt",
            help="Начальный промпт чата для AI",
            default="Ты — соискатель на HeadHunter. Отвечай вежливо и кратко.",
        )
        parser.add_argument(
            "--prompt",
            help="Промпт для генерации сообщения",
            default="Напиши короткий ответ работодателю на основе истории переписки.",
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        args: Namespace = applicant_tool.args
        self.applicant_tool = applicant_tool
        self.api_client = applicant_tool.api_client
        self.resume_id = applicant_tool.first_resume_id()
        self.reply_message = args.reply_message or applicant_tool.config.get(
            "reply_message"
        )
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations

        self.pre_prompt = args.prompt
        self.openai_chat = (
            applicant_tool.get_openai_chat(args.first_prompt)
            if args.use_ai
            else None
        )

        logger.debug(f"{self.reply_message = }")
        self.reply_chats()

    def reply_chats(self) -> None:
        blacklisted = self.applicant_tool.get_blacklisted()
        logger.debug(f"{blacklisted = }")
        me: datatypes.User = self.applicant_tool.get_me()

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        for negotiation in self.applicant_tool.get_negotiations():
            try:
                self.applicant_tool.storage.negotiations.save(negotiation)

                if self.resume_id != negotiation["resume"]["id"]:
                    continue

                state_id = negotiation["state"]["id"]
                if state_id == "discard":
                    continue

                if self.only_invitations and not state_id.startswith("inv"):
                    continue

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
                    messages_res: datatypes.PaginatedItems[
                        datatypes.Message
                    ] = self.api_client.get(
                        f"/negotiations/{nid}/messages", page=page
                    )
                    if not messages_res["items"]:
                        break

                    last_message = messages_res["items"][-1]
                    for message in messages_res["items"]:
                        if not message.get("text"):
                            continue
                        author = (
                            "Работодатель"
                            if message["author"]["participant_type"]
                            == "employer"
                            else "Я"
                        )
                        message_date = parse_api_datetime(
                            message.get("created_at")
                        ).isoformat()
                        message_history.append(
                            f"[ {message_date} ] {author}: {message['text']}"
                        )

                    if page + 1 >= messages_res["pages"]:
                        break
                    page = messages_res["pages"] - 1

                if not last_message:
                    continue

                is_employer_message = (
                    last_message["author"]["participant_type"] == "employer"
                )

                if is_employer_message or not negotiation.get(
                    "viewed_by_opponent"
                ):
                    send_message = ""
                    if self.reply_message:
                        send_message = (
                            rand_text(self.reply_message) % message_placeholders
                        )
                        logger.debug(f"Template message: {send_message}")
                    elif self.openai_chat:
                        try:
                            ai_query = (
                                f"Вакансия: {message_placeholders['vacancy_name']}\n"
                                f"История переписки:\n"
                                + "\n".join(message_history[-10:])
                                + f"\n\nИнструкция: {self.pre_prompt}"
                            )
                            send_message = self.openai_chat.send_message(
                                ai_query
                            )
                            logger.debug(f"AI message: {send_message}")
                        except AIError as ex:
                            logger.warning(
                                f"Ошибка OpenAI для чата {nid}: {ex}"
                            )
                            continue
                    else:
                        print(
                            "\n🏢",
                            message_placeholders["employer_name"],
                            "| 💼",
                            message_placeholders["vacancy_name"],
                        )
                        if salary:
                            print(
                                "💵 от",
                                salary.get("from") or salary.get("to") or 0,
                                "до",
                                salary.get("to") or salary.get("from") or 0,
                                salary.get("currency", "RUR"),
                            )

                        print("\nПоследние сообщения чата:")
                        print()
                        for msg in (
                            message_history[-5:]
                            if len(message_history) > 5
                            else message_history
                        ):
                            print(msg)

                        try:
                            print("-" * 10)
                            print(
                                "Команды: /ban, /cancel <опционально сообщение для отмены>"
                            )
                            send_message = input("Ваше сообщение: ").strip()
                        except EOFError:
                            continue

                        if not send_message:
                            print("🚶 Пропускаем чат")
                            continue

                        if send_message.startswith("/ban"):
                            self.applicant_tool.storage.employers.save(employer)
                            self.api_client.put(
                                f"/employers/blacklisted/{employer['id']}"
                            )
                            blacklisted.append(employer["id"])
                            print(
                                "🚫 Работодатель в ЧС",
                                employer.get("alternate_url"),
                            )
                            continue
                        elif send_message.startswith("/cancel"):
                            _, decline_msg = send_message.split("/cancel", 1)
                            self.api_client.delete(
                                f"/negotiations/active/{nid}",
                                with_decline_message=decline_msg.strip(),
                            )
                            print("❌ Отмена заявки", vacancy["alternate_url"])
                            continue

                    # Финальная отправка текста
                    if self.dry_run:
                        logger.debug(
                            "dry-run: отклик на",
                            vacancy["alternate_url"],
                            send_message,
                        )
                        continue

                    self.api_client.post(
                        f"/negotiations/{nid}/messages",
                        message=send_message,
                        delay=random.uniform(1, 3),
                    )
                    print(f"📨 Отправлено для {vacancy['alternate_url']}")

            except ApiError as ex:
                logger.error(ex)

        print("📝 Сообщения разосланы!")

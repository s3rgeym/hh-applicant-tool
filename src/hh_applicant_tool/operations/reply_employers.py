from __future__ import annotations

import argparse
import logging
import random
import re
from datetime import datetime
from typing import TYPE_CHECKING

from ..ai.base import AIError
from ..api import ApiError, datatypes
from ..main import BaseNamespace, BaseOperation
from ..utils.date import parse_api_datetime
from ..utils.string import rand_text, unescape_string

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
    system_prompt: str
    message_prompt: str
    period: int
    only_bots: bool


class Operation(BaseOperation):
    """Ответ всем работодателям."""

    __aliases__ = ["reply-empls", "reply-chats", "reall"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--resume-id",
            help="Идентификатор резюме. Если не указан, то просматриваем чаты для всех резюме",
        )
        parser.add_argument(
            "-m",
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты. Если не передать сообщение, то нужно будет вводить его в интерактивном режиме.",  # noqa: E501
        )
        parser.add_argument(
            "--period",
            type=int,
            help="Игнорировать отклики, которые не обновлялись больше N дней",
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
            "--system-prompt",
            "--ai-system",
            help="Системный промпт для AI",
            default="Ты — соискатель на HeadHunter. Отвечай вежливо и кратко.",
        )
        parser.add_argument(
            "--message-prompt",
            "--prompt",
            help="Промпт для генерации сообщения",
            default="Напиши короткий ответ работодателю на основе истории переписки.",
        )
        parser.add_argument(
            "--only-bots",
            "--bots-only",
            help=(
                "Автоматически отвечать только на сообщения от ботов/автоматических "
                "систем работодателя (HH.ru не передаёт признак бота в API, поэтому "
                "определяем по тексту: подпись «ИИ-помощник» и другие маркеры, а при "
                "их отсутствии — через AI). Сообщения, похожие на написанные живым "
                "человеком, пропускаются без отправки — на них стоит ответить "
                "самостоятельно."
            ),
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        self.tool = tool
        self.api_client = tool.api_client
        #self.resume_id = tool.first_resume_id() #вместо id первого резюме берем id из аргументов
        self.resume_id = args.resume_id
        self.reply_message = args.reply_message or tool.config.get(
            "reply_message"
        )
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations

        self.message_prompt = args.message_prompt
        self.cover_letter_ai = (
            tool.get_cover_letter_ai(args.system_prompt)
            if args.use_ai
            else None
        )
        self.period = args.period
        self.only_bots = args.only_bots

        logger.debug(f"{self.reply_message = }")
        return self.reply_employers()

    def _clean_ai_message(self, message: str) -> str:
        message = message.strip()
        message = re.sub(r"^```\w*\n?|\n?```$", "", message).strip()
        if len(message) >= 2 and message[0] in "«\"" and message[-1] in "»\"":
            message = message[1:-1].strip()
        return message

    # Сообщения, которые требуют, чтобы соискатель САМ что-то сделал (заполнить
    # форму/анкету, пройти тест/ассесмент, перейти по внешней ссылке на тестовую
    # платформу и т.п.), нельзя обрабатывать автоответом: бот не может выполнить
    # это действие, а формальное «спасибо, заполню» скрывает сообщение из очереди
    # ручной обработки и берёт на себя обязательства от лица живого соискателя.
    # Такие чаты пропускаем и явно показываем — на них нужно ответить вручную.
    _MANUAL_ACTION_RE = re.compile(
        r"тестов\w*\s+задани\w*|пробн\w*\s+задани\w*|\bтест[-\s]?задани\w*|"
        r"\bанкет\w*|\bопросник\w*|\bассес+мент\w*|"
        r"google\s*форм\w*|гугл[-\s]?форм\w*|"
        r"заполни\w*[^.\n]{0,30}?(?:форм\w*|анкет\w*)|"
        r"пройди\w*[^.\n]{0,30}?(?:тест\w*|ассес+мент\w*|опрос\w*)|"
        r"\bassessment\b|\bquestionnaire\b|google\s*form|"
        r"fill\s+(?:out\s+)?(?:the\s+)?form|test\s+task|take[-\s]?home|"
        r"forms\.gle|docs\.google\.com/forms|forms\.office\.com|"
        r"forms\.yandex|typeform|surveymonkey|forms\.app",
        re.IGNORECASE,
    )
    _ANY_LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)
    # Ссылки на сам hh.ru (в т.ч. на вакансию/отклик) — не внешнее действие.
    _HH_HOST_RE = re.compile(r"hh\.ru|headhunter|hhcdn", re.IGNORECASE)

    def _requires_manual_action(self, text: str) -> str | None:
        """Причина, по которой на сообщение нужно ответить вручную, либо None."""
        if not text:
            return None
        if m := self._MANUAL_ACTION_RE.search(text):
            return f"похоже на форму/тест/задание ({m.group(0)!r})"
        # Любая внешняя (не hh.ru) ссылка — сигнал, что работодатель просит
        # куда-то перейти и что-то сделать (форма, тест-платформа, календарь).
        for lm in self._ANY_LINK_RE.finditer(text):
            url = lm.group(0)
            if not self._HH_HOST_RE.search(url):
                return f"внешняя ссылка ({url})"
        return None

    # HH.ru не передаёт в API признак того, что сообщение отправлено ботом
    # (author содержит только participant_type: employer/applicant) — даже
    # сообщения, которые сами представляются AI-ассистентом рекрутера,
    # выглядят в API идентично сообщениям живого человека. Если бот сам
    # называет себя в тексте ("Бот", "чат-бот", конкретное имя сервиса и
    # т.п.) — ловим это без траты запроса к AI; иначе оцениваем через AI.
    #
    # Штатный автоответчик hh.ru всегда подписывается «ИИ-помощник» (см.
    # https://github.com/s3rgeym/hh-ai-responder) — это самый надёжный
    # детерминированный признак бота, ловим его в первую очередь.
    _BOT_TEXT_MARKERS_RE = re.compile(
        r"\bбот\b|чат-?бот|(?:ии|ai)[-\s]?(?:помощник|ассистент)|"
        r"автоматическ\w*\s+(систем\w*|ассистент\w*|помощник\w*)|"
        r"робот[-\s]?помощник|гигарекрутер|giga\s*recruiter",
        re.IGNORECASE,
    )

    def _is_bot_message(
        self, vacancy_name: str, message_history: list[str]
    ) -> bool:
        if not message_history:
            return False

        history_text = "\n".join(message_history)

        if self._BOT_TEXT_MARKERS_RE.search(history_text):
            return True

        if not self.cover_letter_ai:
            return False

        # Передаём именно историю переписки, а не только последнее сообщение:
        # изолированная реплика вроде "Когда вы готовы выйти на работу?" сама
        # по себе неотличима от бота, но в контексте развёрнутого диалога с
        # уточняющими вопросами по конкретным деталям резюме — явный признак
        # живого человека.
        prompt = (
            "Определи по истории переписки: работодатель в этом чате HeadHunter — "
            "это автоматическая система/бот (скриптовый опросник, авто-ассистент "
            "рекрутера, шаблонные сообщения без учёта конкретных предыдущих ответов "
            "соискателя) или живой человек лично? Если работодатель реагирует по "
            "существу на конкретные детали из предыдущих ответов соискателя — это "
            "признак живого человека, а не бота.\n\n"
            f"Вакансия: {vacancy_name}\n"
            f"История переписки:\n{history_text}\n\n"
            'Ответь строго JSON без пояснений: {"is_bot": true} или {"is_bot": false}.'
        )
        try:
            response = self.cover_letter_ai.complete(prompt).strip()
        except AIError as ex:
            logger.warning(f"Ошибка классификации бот/человек: {ex}")
            return False

        response = re.sub(r"^```\w*\n?|\n?```$", "", response).strip()
        match = re.search(
            r'"is_bot"\s*:\s*(true|false)', response, re.IGNORECASE
        )
        if not match:
            logger.warning(
                f"Не удалось распарсить классификацию бот/человек: {response!r}"
            )
            return False
        return match.group(1).lower() == "true"

    def reply_employers(self):
        blacklist = set(self.tool.get_blacklisted())
        me: datatypes.User = self.tool.get_me()
        resumes = self.tool.get_resumes()
        resumes = (
            list(filter(lambda x: x["id"] == self.resume_id, resumes))
            if self.resume_id is not None # добавляем проверку на пустоту
            else resumes
        )
        resumes = list(
            filter(
                lambda resume: resume["status"]["id"] == "published", resumes
            )
        )
        if not resumes:
            logger.error("Нет опубликованных резюме")
            return 1
        return self._reply_chats(user=me, resumes=resumes, blacklist=blacklist)

    def _reply_chats(
        self,
        user: datatypes.User,
        resumes: list[datatypes.Resume],
        blacklist: set[str],
    ) -> None:
        resume_map = {r["id"]: r for r in resumes}

        base_placeholders = {
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": user.get("email") or "",
            "phone": user.get("phone") or "",
        }

        for negotiation in self.tool.get_negotiations():
            try:
                # try:
                #     self.tool.storage.negotiations.save(negotiation)
                # except RepositoryError as e:
                #     logger.exception(e)

                if "resume" not in negotiation:
                    continue

                if not (
                    resume := resume_map.get(negotiation["resume"].get("id"))
                ):
                    continue

                updated_at = parse_api_datetime(negotiation["updated_at"])

                # Пропуск откликов, которые не обновлялись более N дней (при просмотре они обновляются вроде)
                if (
                    self.period
                    and (datetime.now(updated_at.tzinfo) - updated_at).days
                    > self.period
                ):
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

                if employer.get("id") in blacklist:
                    print(
                        "🚫 Пропускаем заблокированного работодателя",
                        employer.get("alternate_url"),
                    )
                    continue

                placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": employer.get("name", ""),
                    "resume_title": resume.get("title") or "",
                    **base_placeholders,
                }

                logger.debug(
                    "Вакансия %(vacancy_name)s от %(employer_name)s"
                    % placeholders
                )

                page: int = 0
                last_message: datatypes.Message | None = None
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
                        ).strftime("%d.%m.%Y %H:%M:%S")

                        message_history.append(
                            f"[ {message_date} ] {author}: {message['text']}"
                        )

                    if page + 1 >= messages_res["pages"]:
                        break
                    page += 1

                if not last_message:
                    continue

                is_employer_message = (
                    last_message["author"]["participant_type"] == "employer"
                )

                # Раньше здесь также стояло "or not negotiation.get('viewed_by_opponent')",
                # из-за чего бот слал повторное сообщение в каждый непрочитанный
                # работодателем чат при каждом запуске — пока сообщение оставалось
                # непрочитанным, оно дублировалось на каждом прогоне cron.
                if is_employer_message:
                    # Не автоотвечаем на сообщения, требующие личного действия
                    # соискателя (форма/тест/ассесмент/внешняя ссылка) — их
                    # пропускаем и показываем, чтобы ответить вручную. Проверка
                    # только для автоматических режимов (шаблон/AI); в интерактиве
                    # соискатель и так видит сообщение и решает сам.
                    if self.reply_message or self.cover_letter_ai:
                        manual_reason = self._requires_manual_action(
                            last_message.get("text") or ""
                        )
                        if manual_reason:
                            logger.info(
                                "Требуется личное действие соискателя (%s), "
                                "пропускаем автоответ: %s",
                                manual_reason,
                                vacancy["alternate_url"],
                            )
                            print(
                                "⚠️  ОТВЕТЬТЕ ВРУЧНУЮ —",
                                manual_reason + ":",
                                vacancy["alternate_url"],
                            )
                            continue
                    send_message = ""
                    if self.reply_message:
                        send_message = (
                            rand_text(self.reply_message) % placeholders
                        )
                        logger.debug(f"Template message: {send_message}")
                    elif self.cover_letter_ai:
                        if self.only_bots and not self._is_bot_message(
                            placeholders["vacancy_name"],
                            message_history[-10:],
                        ):
                            logger.info(
                                "Похоже на сообщение от человека, пропускаем "
                                "автоответ: %s",
                                vacancy["alternate_url"],
                            )
                            print(
                                "👤 Похоже на сообщение от живого человека, "
                                "ответьте вручную:",
                                vacancy["alternate_url"],
                            )
                            continue
                        try:
                            ai_query = (
                                f"Вакансия: {placeholders['vacancy_name']}\n"
                                f"История переписки:\n"
                                + "\n".join(message_history[-10:])
                                + f"\n\nИнструкция: {self.message_prompt}"
                            )
                            send_message = self._clean_ai_message(
                                unescape_string(
                                    self.cover_letter_ai.complete(ai_query)
                                )
                            )
                            logger.debug(f"AI message: {send_message}")
                        except AIError as ex:
                            logger.warning(
                                f"Ошибка OpenAI для чата {nid}: {ex}"
                            )
                            continue

                        # Промпт просит AI вернуть "ПРОПУСТИТЬ", если сообщение
                        # работодателя — типовое уведомление, не требующее
                        # содержательного ответа (иначе AI придумывает лишние
                        # развёрнутые ответы на шаблонные "мы рассмотрим ваше
                        # резюме" и т.п.).
                        if not send_message or re.fullmatch(
                            r"пропустить|skip", send_message, re.IGNORECASE
                        ):
                            logger.info(
                                "AI решил, что ответ не требуется: %s",
                                vacancy["alternate_url"],
                            )
                            print(
                                "⏭️  Шаблонное сообщение, ответ не требуется:",
                                vacancy["alternate_url"],
                            )
                            continue
                    else:
                        print("🏢", placeholders["employer_name"])
                        print("💼", placeholders["vacancy_name"])
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
                            print("-" * 40)
                            print("Активное резюме:", resume.get("title") or "")
                            print(
                                "/ban, /cancel необязательное сообщение для отмены"
                            )
                            send_message = input("Ваше сообщение: ").strip()
                        except EOFError:
                            continue

                        if not send_message:
                            print("🚶 Пропускаем чат")
                            continue

                        if send_message.startswith("/ban"):
                            self.api_client.put(
                                f"/employers/blacklisted/{employer['id']}"
                            )
                            blacklist.add(employer["id"])
                            print(
                                "🚫 Работодатель заблокирован",
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
                            "dry-run: отклик на %s: %s",
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

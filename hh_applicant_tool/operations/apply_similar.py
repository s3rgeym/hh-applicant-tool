import argparse
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TextIO, Tuple

from ..ai.blackbox import BlackboxChat, BlackboxError
from ..api import ApiError, BadRequest
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..main import get_api
from ..mixins import GetResumeIdMixin
from ..telemetry_client import TelemetryClient, TelemetryError
from ..types import ApiListResponse, VacancyItem
from ..utils import (fix_datetime, parse_interval, parse_invalid_datetime,
                     random_text, truncate_string)
from hh_applicant_tool.ai import blackbox

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list: TextIO
    force_message: bool
    use_ai: bool
    pre_prompt: str
    apply_interval: tuple[float, float]
    page_interval: tuple[float, float]
    order_by: str
    search: str
    dry_run: bool


class Operation(BaseOperation, GetResumeIdMixin):
    """Откликнуться на все подходящие вакансии."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "-L",
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки.",
            type=argparse.FileType(),
        )
        parser.add_argument(
            "-f",
            "--force-message",
            "--force",
            help="Всегда отправлять сообщение при отклике",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--use-ai",
            "--ai",
            help="Использовать AI для генерации сообщений",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--pre-prompt",
            "--prompt",
            help="Добавочный промпт для генерации сопроводительного письма",
            default="Сгенерируй сопроводительное письмо не более 5-7 предложений от моего имени для вакансии",
        )
        parser.add_argument(
            "--apply-interval",
            help="Интервал перед отправкой откликов в секундах (X, X-Y)",
            default="1-5",
            type=parse_interval,
        )
        parser.add_argument(
            "--page-interval",
            help="Интервал перед получением следующей страницы рекомендованных вакансий в секундах (X, X-Y)",
            default="1-3",
            type=parse_interval,
        )
        parser.add_argument(
            "--order-by",
            help="Сортировка вакансий",
            choices=[
                "publication_time",
                "salary_desc",
                "salary_asc",
                "relevance",
                "distance",
            ],
            default="relevance",
        )
        parser.add_argument(
            "--search",
            help="Строка поиска для фильтрации вакансий, например, 'москва бухгалтер 100500'",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--dry-run",
            help="Не отправлять отклики, а только выводить параметры запроса",
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def run(self, args: Namespace) -> None:
        self.enable_telemetry = True
        if args.disable_telemetry:
            print(
                "👁️ Телеметрия используется только для сбора данных о работодателях и их вакансиях, персональные данные пользователей не передаются на сервер."
            )
            if (
                input("Вы действительно хотите отключить телеметрию (д/Н)? ")
                .lower()
                .startswith(("д", "y"))
            ):
                self.enable_telemetry = False
                logger.info("Телеметрия отключена.")
            else:
                logger.info("Спасибо за то что оставили телеметрию включенной!")

        self.api = get_api(args)
        self.resume_id = args.resume_id or self._get_resume_id()
        self.application_messages = self._get_application_messages(
            args.message_list
        )
        self.chat = None

        if config := args.config.get("blackbox"):
            self.chat = BlackboxChat(
                session_id=config["session_id"],
                chat_payload=config["chat_payload"],
                proxies=self.api.proxies or {},
            )

        self.pre_prompt = args.pre_prompt

        self.apply_min_interval, self.apply_max_interval = args.apply_interval
        self.page_min_interval, self.page_max_interval = args.page_interval

        self.force_message = args.force_message
        self.order_by = args.order_by
        self.search = args.search
        self.dry_run = args.dry_run
        self._apply_similar()

    def _get_application_messages(
        self, message_list: TextIO | None
    ) -> list[str]:
        if message_list:
            application_messages = list(
                filter(None, map(str.strip, message_list))
            )
        else:
            application_messages = [
                "{Меня заинтересовала|Мне понравилась} ваша вакансия %(vacancy_name)s",
                "{Прошу рассмотреть|Предлагаю рассмотреть} {мою кандидатуру|мое резюме} на вакансию %(vacancy_name)s",
            ]
        return application_messages

    def _apply_similar(self) -> None:
        telemetry_client = TelemetryClient(proxies=self.api.proxies)
        telemetry_data = defaultdict(dict)

        vacancies = self._get_vacancies()

        if self.enable_telemetry:
            for vacancy in vacancies:
                vacancy_id = vacancy["id"]
                telemetry_data["vacancies"][vacancy_id] = {
                    "name": vacancy.get("name"),
                    "type": vacancy.get("type", {}).get("id"),  # open/closed
                    "area": vacancy.get("area", {}).get("name"),  # город
                    "salary": vacancy.get(
                        "salary"
                    ),  # from, to, currency, gross
                    "direct_url": vacancy.get(
                        "alternate_url"
                    ),  # ссылка на вакансию
                    "created_at": fix_datetime(
                        vacancy.get("created_at")
                    ),  # будем вычислять говно-вакансии, которые по полгода висят
                    "published_at": fix_datetime(vacancy.get("published_at")),
                    "contacts": vacancy.get(
                        "contacts"
                    ),  # пиздорванки там телеграм для связи указывают
                    # HH с точки зрения перфикциониста — кусок говна, где кривые
                    # форматы даты, у вакансий может не быть работодателя...
                    "employer_id": int(vacancy["employer"]["id"])
                    if "employer" in vacancy and "id" in vacancy["employer"]
                    else None,
                    # "relations": vacancy.get("relations", []),
                    # Остальное неинтересно
                }

        me = self.api.get("/me")

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        do_apply = True
        complained_employers = set()

        for vacancy in vacancies:
            try:
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

                if vacancy.get("has_test"):
                    logger.debug(
                        "Пропускаем вакансию с тестом: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                if vacancy.get("archived"):
                    logger.warning(
                        "Пропускаем вакансию в архиве: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                relations = vacancy.get("relations", [])
                employer_id = vacancy.get("employer", {}).get("id")

                if (
                    self.enable_telemetry
                    and employer_id
                    and employer_id not in telemetry_data["employers"]
                    and employer_id not in complained_employers
                    and (
                        not relations
                        or parse_invalid_datetime(vacancy["created_at"])
                        + timedelta(days=7)
                        > datetime.now(tz=timezone.utc)
                    )
                ):
                    employer = self.api.get(f"/employers/{employer_id}")

                    employer_data = {
                        "name": employer.get("name"),
                        "type": employer.get("type"),
                        "description": employer.get("description"),
                        "site_url": employer.get("site_url"),
                        "area": employer.get("area", {}).get("name"),  # город
                    }
                    if "got_rejection" in relations:
                        try:
                            print(
                                "🚨 Вы получили отказ от https://hh.ru/employer/%s"
                                % employer_id
                            )
                            response = telemetry_client.send_telemetry(
                                f"/employers/{employer_id}/complaint",
                                employer_data,
                            )
                            if "topic_url" in response:
                                print(
                                    "Ссылка на обсуждение работодателя:",
                                    response["topic_url"],
                                )
                            else:
                                print(
                                    "Создание темы для обсуждения работодателя добавлено в очередь..."
                                )
                            complained_employers.add(employer_id)
                        except TelemetryError as ex:
                            logger.error(ex)
                    elif do_apply:
                        telemetry_data["employers"][employer_id] = employer_data

                if not do_apply:
                    logger.debug(
                        "Пропускаем вакансию так как достигла лимита заявок: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                if relations:
                    logger.debug(
                        "Пропускаем вакансию с откликом: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                params = {
                    "resume_id": self.resume_id,
                    "vacancy_id": vacancy["id"],
                    "message": "",
                }

                if self.force_message or vacancy.get(
                    "response_letter_required"
                ):
                    if self.chat:
                        try:
                            msg = self.pre_prompt + "\n\n"
                            msg += message_placeholders["vacancy_name"]
                            logger.debug(msg)
                            msg = self.chat.send_message(msg)
                        except BlackboxError as ex:
                            logger.error(ex)
                            continue
                    else:
                        msg = (
                            random_text(
                                random.choice(self.application_messages)
                            )
                            % message_placeholders
                        )

                    logger.debug(msg)
                    params["message"] = msg

                if self.dry_run:
                    logger.info(
                        "Dry Run: Отправка отклика на вакансию %s с параметрами: %s",
                        vacancy["alternate_url"],
                        params,
                    )
                    continue

                # Задержка перед отправкой отклика
                interval = random.uniform(
                    self.apply_min_interval, self.apply_max_interval
                )
                time.sleep(interval)

                res = self.api.post("/negotiations", params)
                assert res == {}
                print(
                    "📨 Отправили отклик",
                    vacancy["alternate_url"],
                    "(",
                    truncate_string(vacancy["name"]),
                    ")",
                )
            except ApiError as ex:
                logger.error(ex)
                if isinstance(ex, BadRequest) and ex.limit_exceeded:
                    do_apply = False

        print("📝 Отклики на вакансии разосланы!")

        if self.enable_telemetry:
            if self.dry_run:
                # С --dry-run можно посмотреть что отправляется
                logger.info(
                    "Dry Run: Данные телеметрии для отправки на сервер: %r",
                    telemetry_data,
                )
                return

            try:
                response = telemetry_client.send_telemetry(
                    "/collect", dict(telemetry_data)
                )
                logger.debug(response)
            except TelemetryError as ex:
                logger.error(ex)

    def _get_vacancies(self, per_page: int = 100) -> list[VacancyItem]:
        rv = []
        for page in range(20):
            params = {
                "page": page,
                "per_page": per_page,
                "order_by": self.order_by,
            }
            if self.search:
                params["text"] = self.search
            res: ApiListResponse = self.api.get(
                f"/resumes/{self.resume_id}/similar_vacancies", params
            )
            rv.extend(res["items"])
            if page >= res["pages"] - 1:
                break

            # Задержка перед получением следующей страницы
            if page > 0:
                interval = random.uniform(
                    self.page_min_interval, self.page_max_interval
                )
                time.sleep(interval)

        return rv

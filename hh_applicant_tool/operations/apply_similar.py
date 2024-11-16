import argparse
import logging
import random
import time
from collections import defaultdict
from typing import TextIO, Tuple

from ..api import ApiError, BadRequest
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace, get_api
from ..telemetry_client import TelemetryClient, TelemetryError
from ..types import ApiListResponse, VacancyItem
from ..utils import fix_datetime, truncate_string, random_text, parse_interval
from ..mixins import GetResumeIdMixin

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list: TextIO
    force_message: bool
    apply_interval: Tuple[float, float]
    page_interval: Tuple[float, float]
    order_by: str
    search: str
    dry_run: bool


class Operation(BaseOperation, GetResumeIdMixin):
    """Откликнуться на все подходящие вакансии."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки.",
            type=argparse.FileType(),
        )
        parser.add_argument(
            "--force-message",
            help="Всегда отправлять сообщение при отклике",
            default=False,
            action=argparse.BooleanOptionalAction,
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
        self.application_messages = self._get_application_messages(args.message_list)

        self.apply_min_interval, self.apply_max_interval = args.apply_interval
        self.page_min_interval, self.page_max_interval = args.page_interval

        self.force_message = args.force_message
        self.order_by = args.order_by
        self.search = args.search
        self.dry_run = args.dry_run
        self._apply_similar()

    def _get_application_messages(self, message_list: TextIO | None) -> list[str]:
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
                    "salary": vacancy.get("salary"),  # from, to, currency, gross
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
                    # Остальное неинтересно
                }

        me = self.api.get("/me")

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

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
                    print("🚫 Пропускаем тест", vacancy["alternate_url"])
                    continue

                if vacancy.get("archived"):
                    print(
                        "🚫 Пропускаем вакансию в архиве",
                        vacancy["alternate_url"],
                    )
                    continue

                relations = vacancy.get("relations", [])

                if relations:
                    print(
                        "🚫 Пропускаем вакансию с",
                        ["откликом или приглашением", "отказом"]["got_rejection" in relations],
                        vacancy["alternate_url"],
                    )
                    continue

                employer_id = vacancy.get("employer", {}).get("id")

                if (
                    self.enable_telemetry
                    and employer_id
                    and employer_id not in telemetry_data["employers"]
                ):
                    employer = self.api.get(f"/employers/{employer_id}")
                    telemetry_data["employers"][employer_id] = {
                        "name": employer.get("name"),
                        "type": employer.get("type"),
                        "description": employer.get("description"),
                        "site_url": employer.get("site_url"),
                        "area": employer.get("area", {}).get("name"),  # город
                    }

                params = {
                    "resume_id": self.resume_id,
                    "vacancy_id": vacancy["id"],
                    "message": "",
                }

                if self.force_message or vacancy.get("response_letter_required"):
                    msg = params["message"] = (
                        random_text(random.choice(self.application_messages))
                        % message_placeholders
                    )
                    logger.debug(msg)

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
                    break

        print("📝 Отклики на вакансии разосланы!")

        if self.enable_telemetry:
            if self.dry_run:
                # С --dry-run можно посмотреть что отправляется
                logger.info('Dry Run: Данные телеметрии для отправки на сервер: %r', telemetry_data)
                return

            try:
                telemetry_client.send_telemetry("/collect", dict(telemetry_data))
            except TelemetryError as ex:
                logger.error(ex)
                
    def _get_vacancies(
            self, per_page: int = 100
    ) -> list[VacancyItem]:
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
                interval = random.uniform(self.page_min_interval, self.page_max_interval)
                time.sleep(interval)

        return rv


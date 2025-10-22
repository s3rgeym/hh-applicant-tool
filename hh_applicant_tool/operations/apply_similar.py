import argparse
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from ..ai.blackbox import BlackboxChat, BlackboxError
from ..api import ApiClient, ApiError
from ..api.errors import LimitExceeded
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..mixins import GetResumeIdMixin
from ..telemetry_client import TelemetryClient, TelemetryError
from ..types import ApiListResponse, VacancyItem
from ..utils import (
    fix_datetime,
    parse_interval,
    parse_invalid_datetime,
    random_text,
    truncate_string,
)

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
    schedule: str
    dry_run: bool
    # Пошли доп фильтры, которых не было
    experience: str
    employment: list[str] | None
    area: list[str] | None
    metro: list[str] | None
    professional_role: list[str] | None
    industry: list[str] | None
    employer_id: list[str] | None
    excluded_employer_id: list[str] | None
    currency: str | None
    salary: int | None
    only_with_salary: bool
    label: list[str] | None
    period: int | None
    date_from: str | None
    date_to: str | None
    top_lat: float | None
    bottom_lat: float | None
    left_lng: float | None
    right_lng: float | None
    sort_point_lat: float | None
    sort_point_lng: float | None
    no_magic: bool
    premium: bool
    responses_count_enabled: bool


def _bool(v: bool) -> str:
    return str(v).lower()


def _join_list(items: list[Any] | None) -> str:
    return ",".join(f"{v}" for v in items) if items else ""


class Operation(BaseOperation, GetResumeIdMixin):
    """Откликнуться на все подходящие вакансии.

    Описание фильтров для поиска вакансий: <https://api.hh.ru/openapi/redoc#tag/Poisk-vakansij-dlya-soiskatelya/operation/get-vacancies-similar-to-resume>
    """

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "-L",
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки.",
            type=argparse.FileType("r", encoding="utf-8", errors="replace"),
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
            "--schedule",
            help="Тип графика. Возможные значения: fullDay, shift, flexible, remote, flyInFlyOut для полного дня, сменного графика, гибкого графика, удаленной работы и вахтового метода",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--dry-run",
            help="Не отправлять отклики, а только выводить параметры запроса",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--experience",
            help="Уровень опыта работы в вакансии. Возможные значения: noExperience, between1And3, between3And6, moreThan6",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--employment", nargs="+", help="Тип занятости (employment)"
        )
        parser.add_argument("--area", nargs="+", help="Регион (area id)")
        parser.add_argument("--metro", nargs="+", help="Станции метро (metro id)")
        parser.add_argument("--professional-role", nargs="+", help="Проф. роль (id)")
        parser.add_argument("--industry", nargs="+", help="Индустрия (industry id)")
        parser.add_argument("--employer-id", nargs="+", help="ID работодателей")
        parser.add_argument(
            "--excluded-employer-id", nargs="+", help="Исключить работодателей"
        )
        parser.add_argument("--currency", help="Код валюты (RUR, USD, EUR)")
        parser.add_argument("--salary", type=int, help="Минимальная зарплата")
        parser.add_argument(
            "--only-with-salary", default=False, action=argparse.BooleanOptionalAction
        )
        parser.add_argument("--label", nargs="+", help="Метки вакансий (label)")
        parser.add_argument("--period", type=int, help="Искать вакансии за N дней")
        parser.add_argument("--date-from", help="Дата публикации с (YYYY-MM-DD)")
        parser.add_argument("--date-to", help="Дата публикации по (YYYY-MM-DD)")
        parser.add_argument("--top-lat", type=float, help="Гео: верхняя широта")
        parser.add_argument("--bottom-lat", type=float, help="Гео: нижняя широта")
        parser.add_argument("--left-lng", type=float, help="Гео: левая долгота")
        parser.add_argument("--right-lng", type=float, help="Гео: правая долгота")
        parser.add_argument(
            "--sort-point-lat",
            type=float,
            help="Координата lat для сортировки по расстоянию",
        )
        parser.add_argument(
            "--sort-point-lng",
            type=float,
            help="Координата lng для сортировки по расстоянию",
        )
        parser.add_argument(
            "--no-magic",
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Отключить авторазбор текста запроса",
        )
        parser.add_argument(
            "--premium",
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Только премиум вакансии",
        )
        parser.add_argument(
            "--responses-count-enabled",
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Включить счётчик откликов",
        )
        parser.add_argument(
            "--search-field", nargs="+", help="Поля поиска (name, company_name и т.п.)"
        )
        parser.add_argument(
            "--clusters",
            action=argparse.BooleanOptionalAction,
            help="Включить кластеры (по умолчанию None)",
        )
        # parser.add_argument("--describe-arguments", action=argparse.BooleanOptionalAction, help="Вернуть описание параметров запроса")

    def run(
        self, args: Namespace, api_client: ApiClient, telemetry_client: TelemetryClient
    ) -> None:
        self.enable_telemetry = True
        if args.disable_telemetry:
            # print(
            #     "👁️ Телеметрия используется только для сбора данных о работодателях и их вакансиях, персональные данные пользователей не передаются на сервер."
            # )
            # if (
            #     input("Вы действительно хотите отключить телеметрию (д/Н)? ")
            #     .lower()
            #     .startswith(("д", "y"))
            # ):
            #     self.enable_telemetry = False
            #     logger.info("Телеметрия отключена.")
            # else:
            #     logger.info("Спасибо за то что оставили телеметрию включенной!")
            self.enable_telemetry = False

        self.api_client = api_client
        self.telemetry_client = telemetry_client
        self.resume_id = args.resume_id or self._get_resume_id()
        self.application_messages = self._get_application_messages(args.message_list)
        self.chat = None

        if config := args.config.get("blackbox"):
            self.chat = BlackboxChat(
                session_id=config["session_id"],
                chat_payload=config["chat_payload"],
                proxies=self.api_client.proxies or {},
            )

        self.pre_prompt = args.pre_prompt

        self.apply_min_interval, self.apply_max_interval = args.apply_interval
        self.page_min_interval, self.page_max_interval = args.page_interval

        self.force_message = args.force_message
        self.order_by = args.order_by
        self.search = args.search
        self.schedule = args.schedule
        self.dry_run = args.dry_run
        self.experience = args.experience
        self.search_field = args.search_field
        self.employment = args.employment
        self.area = args.area
        self.metro = args.metro
        self.professional_role = args.professional_role
        self.industry = args.industry
        self.employer_id = args.employer_id
        self.excluded_employer_id = args.excluded_employer_id
        self.currency = args.currency
        self.salary = args.salary
        self.only_with_salary = args.only_with_salary
        self.label = args.label
        self.period = args.period
        self.date_from = args.date_from
        self.date_to = args.date_to
        self.top_lat = args.top_lat
        self.bottom_lat = args.bottom_lat
        self.left_lng = args.left_lng
        self.right_lng = args.right_lng
        self.sort_point_lat = args.sort_point_lat
        self.sort_point_lng = args.sort_point_lng
        self.clusters = args.clusters
        # self.describe_arguments = args.describe_arguments
        self.no_magic = args.no_magic
        self.premium = args.premium
        self._apply_similar()

    def _get_application_messages(self, message_list: TextIO | None) -> list[str]:
        if message_list:
            application_messages = list(filter(None, map(str.strip, message_list)))
        else:
            application_messages = [
                "{Меня заинтересовала|Мне понравилась} ваша вакансия %(vacancy_name)s",
                "{Прошу рассмотреть|Предлагаю рассмотреть} {мою кандидатуру|мое резюме} на вакансию %(vacancy_name)s",
            ]
        return application_messages

    def _apply_similar(self) -> None:
        telemetry_client = self.telemetry_client
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
                    "direct_url": vacancy.get("alternate_url"),  # ссылка на вакансию
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

        me = self.api_client.get("/me")

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
                    "employer_name": vacancy.get("employer", {}).get("name", ""),
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
                    employer = self.api_client.get(f"/employers/{employer_id}")

                    employer_data = {
                        "name": employer.get("name"),
                        "type": employer.get("type"),
                        "description": employer.get("description"),
                        "site_url": employer.get("site_url"),
                        "area": employer.get("area", {}).get("name"),  # город
                    }
                    if "got_rejection" in relations:
                        print(
                            "🚨 Вы получили отказ от https://hh.ru/employer/%s"
                            % employer_id
                        )

                        complained_employers.add(employer_id)

                    elif do_apply:
                        telemetry_data["employers"][employer_id] = employer_data

                if not do_apply:
                    logger.debug(
                        "Останавливаем рассылку откликов, так как достигли лимита, попробуйте через сутки."
                    )
                    break

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

                if self.force_message or vacancy.get("response_letter_required"):
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
                            random_text(random.choice(self.application_messages))
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

                res = self.api_client.post("/negotiations", params)
                assert res == {}
                print(
                    "📨 Отправили отклик",
                    vacancy["alternate_url"],
                    "(",
                    truncate_string(vacancy["name"]),
                    ")",
                )
            except LimitExceeded:
                print("⚠️ Достигли лимита рассылки")
                do_apply = False
            except ApiError as ex:
                logger.error(ex)

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

    def _get_search_params(self, page: int, per_page: int) -> dict:
        params = {
            "page": page,
            "per_page": per_page,
            "order_by": self.order_by,
        }

        if self.search:
            params["text"] = self.search
        if self.schedule:
            params["schedule"] = self.schedule
        if self.experience:
            params["experience"] = self.experience
        if self.currency:
            params["currency"] = self.currency
        if self.salary:
            params["salary"] = self.salary
        if self.period:
            params["period"] = self.period
        if self.date_from:
            params["date_from"] = self.date_from
        if self.date_to:
            params["date_to"] = self.date_to
        if self.top_lat:
            params["top_lat"] = self.top_lat
        if self.bottom_lat:
            params["bottom_lat"] = self.bottom_lat
        if self.left_lng:
            params["left_lng"] = self.left_lng
        if self.right_lng:
            params["right_lng"] = self.right_lng
        if self.sort_point_lat:
            params["sort_point_lat"] = self.sort_point_lat
        if self.sort_point_lng:
            params["sort_point_lng"] = self.sort_point_lng
        if self.search_field:
            params["search_field"] = _join_list(self.search_field)
        if self.employment:
            params["employment"] = _join_list(self.employment)
        if self.area:
            params["area"] = _join_list(self.area)
        if self.metro:
            params["metro"] = _join_list(self.metro)
        if self.professional_role:
            params["professional_role"] = _join_list(self.professional_role)
        if self.industry:
            params["industry"] = _join_list(self.industry)
        if self.employer_id:
            params["employer_id"] = _join_list(self.employer_id)
        if self.excluded_employer_id:
            params["excluded_employer_id"] = _join_list(self.excluded_employer_id)
        if self.label:
            params["label"] = _join_list(self.label)
        if self.only_with_salary is not None:
            params["only_with_salary"] = _bool(self.only_with_salary)
        if self.clusters is not None:
            params["clusters"] = _bool(self.clusters)
        if self.no_magic is not None:
            params["no_magic"] = _bool(self.no_magic)
        if self.premium is not None:
            params["premium"] = _bool(self.premium)
        if self.responses_count_enabled is not None:
            params["responses_count_enabled"] = _bool(self.responses_count_enabled)

        return params

    def _get_vacancies(self, per_page: int = 100) -> list[VacancyItem]:
        rv = []
        # API отдает только 2000 результатов
        for page in range(20):
            params = self._get_search_params(page, per_page)
            res: ApiListResponse = self.api_client.get(
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

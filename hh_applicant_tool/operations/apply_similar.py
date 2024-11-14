import argparse
import logging
import random
import time
from collections import defaultdict
from os import getenv
from typing import TextIO, Tuple

from ..api import ApiClient, ApiError, BadRequest
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace, get_api
from ..telemetry_client import TelemetryClient, TelemetryError
from ..types import ApiListResponse, VacancyItem
from ..utils import fix_datetime, truncate_string, random_text
from requests import Session

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list: TextIO
    force_message: bool
    apply_interval: Tuple[float, float]
    page_interval: Tuple[float, float]
    message_interval: Tuple[float, float]
    order_by: str
    search: str
    reply_message: str


# gx для открытия (никак не запомню в виме)
# https://api.hh.ru/openapi/redoc
class Operation(BaseOperation):
    """Откликнуться на все подходящие вакансии. По умолчанию применяются значения, которые были отмечены галочками в форме для поиска на сайте"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки. В сообщения можно использовать плейсхолдеры типа %%(vacabcy_name)s",
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
            type=self._parse_interval,
        )
        parser.add_argument(
            "--page-interval",
            help="Интервал перед получением следующей страницы рекомендованных вакансий в секундах (X, X-Y)",
            default="1-3",
            type=self._parse_interval,
        )
        parser.add_argument(
            "--message-interval",
            help="Интервал перед отправкой сообщения в секундах (X, X-Y)",
            default="5-10",
            type=self._parse_interval,
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
            help="Строка поиска для фильтрации вакансий, например, 'москва бухгалтер 100500', те можно и город указать, и ожидаемую зарплату",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты, где ожидают ответа либо не прочитали ответ",
        )

    @staticmethod
    def _parse_interval(interval: str) -> Tuple[float, float]:
        """Парсит строку интервала и возвращает кортеж с минимальным и максимальным значениями."""
        if "-" in interval:
            min_interval, max_interval = map(float, interval.split("-"))
        else:
            min_interval = max_interval = float(interval)
        return min(min_interval, max_interval), max(min_interval, max_interval)

    def run(self, args: Namespace) -> None:
        api = get_api(args)
        resume_id = self._get_resume_id(args, api)
        application_messages = self._get_application_messages(args)

        apply_min_interval, apply_max_interval = args.apply_interval
        page_min_interval, page_max_interval = args.page_interval
        message_min_interval, message_max_interval = args.message_interval

        self._apply_similar(
            api,
            resume_id,
            args.force_message,
            application_messages,
            apply_min_interval,
            apply_max_interval,
            page_min_interval,
            page_max_interval,
            message_min_interval,
            message_max_interval,
            args.order_by,
            args.search,
            args.reply_message or args.config["reply_message"],
        )

    def _get_resume_id(self, args: Namespace, api: ApiClient) -> str:
        if not (
            resume_id := args.resume_id or args.config["default_resume_id"]
        ):
            resumes: ApiListResponse = api.get("/resumes/mine")
            resume_id = resumes["items"][0]["id"]
        return resume_id

    def _get_application_messages(self, args: Namespace) -> list[str]:
        if args.message_list:
            application_messages = list(
                filter(None, map(str.strip, args.message_list))
            )
        else:
            application_messages = [
                "{Меня заинтересовала|Мне понравилась} ваша вакансия %(vacancy_name)s",
                "{Прошу рассмотреть|Предлагаю рассмотреть} {мою кандидатуру|мое резюме} на вакансию %(vacancy_name)s",
            ]
        return application_messages

    def _apply_similar(
        self,
        api: ApiClient,
        resume_id: str,
        force_message: bool,
        application_messages: list[str],
        apply_min_interval: float,
        apply_max_interval: float,
        page_min_interval: float,
        page_max_interval: float,
        message_min_interval: float,
        message_max_interval: float,
        order_by: str,
        search: str | None = None,
        reply_message: str | None = None,
    ) -> None:
        # TODO: вынести куда-нибудь в функцию
        session = Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (HHApplicantTelemetry/1.0)"
        session.proxies = dict(api.session.proxies)
        telemetry_client = TelemetryClient(session=session)
        telemetry_data = defaultdict(dict)

        vacancies = self._get_vacancies(
            api,
            resume_id,
            page_min_interval,
            page_max_interval,
            per_page=100,
            order_by=order_by,
            search=search,
        )

        self._collect_vacancy_telemetry(telemetry_data, vacancies)

        me = api.get("/me")

        basic_message_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        do_apply = True

        for vacancy in vacancies:
            try:
                if getenv("TEST_TELEMETRY"):
                    break

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
                    if "got_rejection" in relations:
                        print(
                            "🚫 Пропускаем отказ на вакансию",
                            vacancy["alternate_url"],
                        )
                        continue

                    if reply_message:
                        r = api.get("/negotiations", vacancy_id=vacancy["id"])

                        if len(r["items"]) == 1:
                            neg = r["items"][0]
                            nid = neg["id"]

                            page: int = 0
                            last_message: dict | None = None
                            while True:
                                r2 = api.get(
                                    f"/negotiations/{nid}/messages", page=page
                                )
                                last_message = r2["items"][-1]
                                if page + 1 >= r2["pages"]:
                                    break

                                page = r2["pages"] - 1

                            logger.debug(last_message["text"])

                            if last_message["author"][
                                "participant_type"
                            ] == "employer" or not neg.get(
                                "viewed_by_opponent"
                            ):
                                message = (
                                    random_text(reply_message)
                                    % message_placeholders
                                )
                                logger.debug(message)

                                time.sleep(
                                    random.uniform(
                                        message_min_interval,
                                        message_max_interval,
                                    )
                                )
                                api.post(
                                    f"/negotiations/{nid}/messages",
                                    message=message,
                                )
                                print(
                                    "📨 Отправили сообщение для привлечения внимания",
                                    vacancy["alternate_url"],
                                )
                            continue
                        else:
                            logger.warning(
                                "Приглашение без чата для вакансии: %s",
                                vacancy["alternate_url"],
                            )

                    print(
                        "🚫 Пропускаем вакансию с откликом",
                        vacancy["alternate_url"],
                    )
                    continue

                employer_id = vacancy.get("employer", {}).get("id")

                if (
                    employer_id
                    and employer_id not in telemetry_data["employers"]
                    and 200 > len(telemetry_data["employers"])
                ):
                    employer = api.get(f"/employers/{employer_id}")
                    telemetry_data["employers"][employer_id] = {
                        "name": employer.get("name"),
                        "type": employer.get("type"),
                        "description": employer.get("description"),
                        "site_url": employer.get("site_url"),
                        "area": employer.get("area", {}).get("name"),  # город
                    }

                if not do_apply:
                    logger.debug("skip apply similar")
                    continue

                params = {
                    "resume_id": resume_id,
                    "vacancy_id": vacancy["id"],
                    "message": "",
                }

                if force_message or vacancy.get("response_letter_required"):
                    msg = params["message"] = (
                        random_text(random.choice(application_messages))
                        % message_placeholders
                    )
                    logger.debug(msg)

                # Задержка перед отправкой отклика
                interval = random.uniform(
                    max(apply_min_interval, message_min_interval)
                    if params["message"]
                    else apply_min_interval,
                    max(apply_max_interval, message_max_interval)
                    if params["message"]
                    else apply_max_interval,
                )
                time.sleep(interval)

                res = api.post("/negotiations", params)
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
                    if not reply_message:
                        break
                    do_apply = False

        print("📝 Отклики на вакансии разосланы!")

        # Я собираюсь выложить контакты херок в общественный доступ
        self._send_telemetry(telemetry_client, telemetry_data)

    def _get_vacancies(
        self,
        api: ApiClient,
        resume_id: str,
        page_min_interval: float,
        page_max_interval: float,
        per_page: int,
        order_by: str,
        search: str | None = None,
    ) -> list[VacancyItem]:
        rv = []
        for page in range(20):
            params = {
                "page": page,
                "per_page": per_page,
                "order_by": order_by,
            }
            if search:
                params["text"] = search
            res: ApiListResponse = api.get(
                f"/resumes/{resume_id}/similar_vacancies", params
            )
            rv.extend(res["items"])

            if getenv("TEST_TELEMETRY"):
                break

            if page >= res["pages"] - 1:
                break

            # Задержка перед получением следующей страницы
            if page > 0:
                interval = random.uniform(page_min_interval, page_max_interval)
                time.sleep(interval)

        return rv

    def _collect_vacancy_telemetry(
        self, telemetry_data: defaultdict, vacancies: list[VacancyItem]
    ) -> None:
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

    def _send_telemetry(
        self, telemetry_client, telemetry_data: defaultdict
    ) -> None:
        try:
            res = telemetry_client.send_telemetry(
                "/collect", dict(telemetry_data)
            )
            logger.debug(res)
        except TelemetryError as ex:
            logger.error(ex)

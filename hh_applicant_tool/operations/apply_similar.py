from __future__ import annotations

import argparse
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, TextIO

from .. import datatypes
from ..ai.base import AIError
from ..api import BadResponse, Redirect
from ..api.errors import ApiError, LimitExceeded
from ..datatypes import PaginatedItems, SearchVacancy
from ..main import BaseNamespace, BaseOperation
from ..utils import bool2str, list2str, rand_text, shorten

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list: TextIO
    ignore_employers: Path | None
    force_message: bool
    use_ai: bool
    first_prompt: str
    prompt: str
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
    per_page: int
    total_pages: int


class Operation(BaseOperation):
    """Откликнуться на все подходящие вакансии.

    Описание фильтров для поиска вакансий: <https://api.hh.ru/openapi/redoc#tag/Poisk-vakansij-dlya-soiskatelya/operation/get-vacancies-similar-to-resume>
    """

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "--search",
            help="Строка поиска для фильтрации вакансий, например, 'москва бухгалтер 100500'",  # noqa: E501
            type=str,
        )
        parser.add_argument(
            "-L",
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки.",  # noqa: E501
            type=argparse.FileType("r", encoding="utf-8", errors="replace"),
        )
        parser.add_argument(
            "-f",
            "--force-message",
            "--force",
            help="Всегда отправлять сообщение при отклике",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--use-ai",
            "--ai",
            help="Использовать AI для генерации сообщений",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--first-prompt",
            help="Начальный помпт чата для генерации сопроводительного письма",
            default="Напиши сопроводительное письмо для отклика на эту вакансию. Не используй placeholder'ы, твой ответ будет отправлен без обработки.",  # noqa: E501
        )
        parser.add_argument(
            "--prompt",
            help="Промпт для генерации сопроводительного письма",
            default="Сгенерируй сопроводительное письмо не более 5-7 предложений от моего имени для вакансии",  # noqa: E501
        )
        parser.add_argument(
            "--total-pages",
            "--pages",
            help="Количество обрабатываемых страниц поиска",  # noqa: E501
            default=20,
            type=int,
        )
        parser.add_argument(
            "--per-page",
            help="Сколько должно быть результатов на странице",  # noqa: E501
            default=100,
            type=int,
        )
        parser.add_argument(
            "--dry-run",
            help="Не отправлять отклики, а только выводить информацию",
            action=argparse.BooleanOptionalAction,
        )

        # Дальше идут параметры в точности соответствующие параметрам запроса
        # при поиске подходящих вакансий
        search_params_group = parser.add_argument_group(
            "Параметры поиска вакансий",
            "Эти параметры напрямую соответствуют фильтрам поиска HeadHunter API",
        )

        search_params_group.add_argument(
            "--order-by",
            help="Сортировка вакансий",
            choices=[
                "publication_time",
                "salary_desc",
                "salary_asc",
                "relevance",
                "distance",
            ],
            # default="relevance",
        )
        search_params_group.add_argument(
            "--experience",
            help="Уровень опыта работы (noExperience, between1And3, between3And6, moreThan6)",
            type=str,
            default=None,
        )
        search_params_group.add_argument(
            "--schedule",
            help="Тип графика (fullDay, shift, flexible, remote, flyInFlyOut)",
            type=str,
        )
        search_params_group.add_argument(
            "--employment", nargs="+", help="Тип занятости"
        )
        search_params_group.add_argument(
            "--area", nargs="+", help="Регион (area id)"
        )
        search_params_group.add_argument(
            "--metro", nargs="+", help="Станции метро (metro id)"
        )
        search_params_group.add_argument(
            "--professional-role", nargs="+", help="Проф. роль (id)"
        )
        search_params_group.add_argument(
            "--industry", nargs="+", help="Индустрия (industry id)"
        )
        search_params_group.add_argument(
            "--employer-id", nargs="+", help="ID работодателей"
        )
        search_params_group.add_argument(
            "--excluded-employer-id", nargs="+", help="Исключить работодателей"
        )
        search_params_group.add_argument(
            "--currency", help="Код валюты (RUR, USD, EUR)"
        )
        search_params_group.add_argument(
            "--salary", type=int, help="Минимальная зарплата"
        )
        search_params_group.add_argument(
            "--only-with-salary",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        search_params_group.add_argument(
            "--label", nargs="+", help="Метки вакансий (label)"
        )
        search_params_group.add_argument(
            "--period", type=int, help="Искать вакансии за N дней"
        )
        search_params_group.add_argument(
            "--date-from", help="Дата публикации с (YYYY-MM-DD)"
        )
        search_params_group.add_argument(
            "--date-to", help="Дата публикации по (YYYY-MM-DD)"
        )
        search_params_group.add_argument(
            "--top-lat", type=float, help="Гео: верхняя широта"
        )
        search_params_group.add_argument(
            "--bottom-lat", type=float, help="Гео: нижняя широта"
        )
        search_params_group.add_argument(
            "--left-lng", type=float, help="Гео: левая долгота"
        )
        search_params_group.add_argument(
            "--right-lng", type=float, help="Гео: правая долгота"
        )
        search_params_group.add_argument(
            "--sort-point-lat",
            type=float,
            help="Координата lat для сортировки по расстоянию",
        )
        search_params_group.add_argument(
            "--sort-point-lng",
            type=float,
            help="Координата lng для сортировки по расстоянию",
        )
        search_params_group.add_argument(
            "--no-magic",
            action="store_true",
            help="Отключить авторазбор текста запроса",
        )
        search_params_group.add_argument(
            "--premium",
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Только премиум вакансии",
        )
        search_params_group.add_argument(
            "--search-field",
            nargs="+",
            help="Поля поиска (name, company_name и т.п.)",
        )

    def run(
        self,
        tool: HHApplicantTool,
    ) -> None:
        self.tool = tool
        self.api_client = tool.api_client
        args: Namespace = tool.args
        self.application_messages = self._get_application_messages(
            args.message_list
        )
        self.area = args.area
        self.bottom_lat = args.bottom_lat
        self.currency = args.currency
        self.date_from = args.date_from
        self.date_to = args.date_to
        self.dry_run = args.dry_run
        self.employer_id = args.employer_id
        self.employment = args.employment
        self.excluded_employer_id = args.excluded_employer_id
        self.experience = args.experience
        self.force_message = args.force_message
        self.industry = args.industry
        self.label = args.label
        self.left_lng = args.left_lng
        self.metro = args.metro
        self.no_magic = args.no_magic
        self.only_with_salary = args.only_with_salary
        self.order_by = args.order_by
        self.per_page = args.per_page
        self.period = args.period
        self.pre_prompt = args.prompt
        self.premium = args.premium
        self.professional_role = args.professional_role
        self.resume_id = args.resume_id or tool.first_resume_id()
        self.right_lng = args.right_lng
        self.salary = args.salary
        self.schedule = args.schedule
        self.search = args.search
        self.search_field = args.search_field
        self.sort_point_lat = args.sort_point_lat
        self.sort_point_lng = args.sort_point_lng
        self.top_lat = args.top_lat
        self.total_pages = args.total_pages
        self.openai_chat = (
            tool.get_openai_chat(args.first_prompt) if args.use_ai else None
        )
        self._apply_similar()

    def _get_application_messages(
        self, message_list: TextIO | None
    ) -> list[str]:
        return (
            list(filter(None, map(str.strip, message_list)))
            if message_list
            else [
                "{Меня заинтересовала|Мне понравилась} ваша вакансия %(vacancy_name)s",
                "{Прошу рассмотреть|Предлагаю рассмотреть} {мою кандидатуру|мое резюме} на вакансию %(vacancy_name)s",  # noqa: E501
            ]
        )

    def _apply_similar(self) -> None:
        me: datatypes.User = self.tool.get_me()

        basic_placeholders = {
            "first_name": me.get("first_name", ""),
            "last_name": me.get("last_name", ""),
            "email": me.get("email", ""),
            "phone": me.get("phone", ""),
        }

        seen_employers = set()
        for vacancy in self._get_vacancies():
            try:
                employer = vacancy.get("employer", {})

                placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": employer.get("name", ""),
                    **basic_placeholders,
                }

                storage = self.tool.storage
                storage.vacancies.save(vacancy)
                if employer := vacancy.get("employer"):
                    employer_id = employer.get("id")
                    if employer_id and employer_id not in seen_employers:
                        employer_profile: datatypes.Employer = (
                            self.api_client.get(f"/employers/{employer_id}")
                        )
                        storage.employers.save(employer_profile)

                # По факту контакты можно получить только здесь?!
                if vacancy.get("contacts"):
                    storage.employer_contacts.save(vacancy)

                if vacancy.get("has_test"):
                    logger.debug(
                        "Пропускаем вакансию с тестом: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                if vacancy.get("archived"):
                    logger.debug(
                        "Пропускаем вакансию в архиве: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                if redirect_url := vacancy.get("response_url"):
                    logger.debug(
                        "Пропускаем вакансию %s с перенаправлением: %s",
                        vacancy["alternate_url"],
                        redirect_url,
                    )
                    continue

                vacancy_id = vacancy["id"]

                relations = vacancy.get("relations", [])

                if relations:
                    logger.debug(
                        "Пропускаем вакансию с откликом: %s",
                        vacancy["alternate_url"],
                    )
                    if "got_rejection" in relations:
                        logger.debug(
                            "Вы получили отказ: %s", vacancy["alternate_url"]
                        )
                        print("⛔  Пришел отказ", vacancy["alternate_url"])
                    continue

                params = {
                    "resume_id": self.resume_id,
                    "vacancy_id": vacancy_id,
                    "message": "",
                }

                if self.force_message or vacancy.get(
                    "response_letter_required"
                ):
                    if self.openai_chat:
                        msg = self.pre_prompt + "\n\n"
                        msg += placeholders["vacancy_name"]
                        logger.debug("prompt: %s", msg)
                        msg = self.openai_chat.send_message(msg)
                    else:
                        msg = (
                            rand_text(random.choice(self.application_messages))
                            % placeholders
                        )

                    logger.debug(msg)
                    params["message"] = msg

                try:
                    if not self.dry_run:
                        res = self.api_client.post(
                            "/negotiations",
                            params,
                            delay=random.uniform(1, 3),
                        )
                        assert res == {}
                        logger.debug(
                            "Отправили отклик: %s", vacancy["alternate_url"]
                        )
                    print(
                        "📨 Отправили отклик:",
                        vacancy["alternate_url"],
                        shorten(vacancy["name"]),
                    )
                except Redirect:
                    logger.warning(
                        f"Игнорирую перенаправление на форму: {vacancy['alternate_url']}"  # noqa: E501
                    )
            except LimitExceeded:
                logger.info("Достигли лимита на отклики")
                print("⚠️ Достигли лимита рассылки")
                # self.tool.storage.settings.set_value("_")
                break
            except ApiError as ex:
                logger.warning(ex)
            except (BadResponse, AIError) as ex:
                logger.error(ex)

        print("📝 Отклики на вакансии разосланы!")

    def _get_search_params(self, page: int) -> dict:
        params = {
            "page": page,
            "per_page": self.per_page,
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
            params["search_field"] = list2str(self.search_field)
        if self.employment:
            params["employment"] = list2str(self.employment)
        if self.area:
            params["area"] = list2str(self.area)
        if self.metro:
            params["metro"] = list2str(self.metro)
        if self.professional_role:
            params["professional_role"] = list2str(self.professional_role)
        if self.industry:
            params["industry"] = list2str(self.industry)
        if self.employer_id:
            params["employer_id"] = list2str(self.employer_id)
        if self.excluded_employer_id:
            params["excluded_employer_id"] = list2str(self.excluded_employer_id)
        if self.label:
            params["label"] = list2str(self.label)
        if self.only_with_salary:
            params["only_with_salary"] = bool2str(self.only_with_salary)
        # if self.clusters:
        #     params["clusters"] = bool2str(self.clusters)
        if self.no_magic:
            params["no_magic"] = bool2str(self.no_magic)
        if self.premium:
            params["premium"] = bool2str(self.premium)
        # if self.responses_count_enabled is not None:
        #     params["responses_count_enabled"] = bool2str(self.responses_count_enabled)

        return params

    def _get_vacancies(self) -> Iterator[SearchVacancy]:
        for page in range(self.total_pages):
            params = self._get_search_params(page)
            res: PaginatedItems[SearchVacancy] = self.api_client.get(
                f"/resumes/{self.resume_id}/similar_vacancies",
                params,
            )
            if not res["items"]:
                return

            yield from res["items"]

            if page >= res["pages"] - 1:
                return

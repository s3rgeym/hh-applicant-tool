from __future__ import annotations

import argparse
import json
import logging
import random
import string
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from .. import utils
from ..ai.base import AIError
from ..api import BadResponse, Redirect, datatypes
from ..api.datatypes import PaginatedItems, SearchVacancy
from ..api.errors import ApiError, LimitExceeded
from ..main import BaseNamespace, BaseOperation
from ..storage.repositories.errors import RepositoryError
from ..utils.datatypes import VacancyTestsData
from ..utils.string import (
    bool2str,
    rand_text,
    unescape_string,
)

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list_path: Path
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
    excluded_terms: str | None


class Operation(BaseOperation):
    """Откликнуться на все подходящие вакансии."""

    __aliases__ = ("apply",)

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "--search",
            help="Строка поиска для фильтрации вакансий, например, 'москва бухгалтер 100500'",  # noqa: E501
            type=str,
        )
        parser.add_argument(
            "-L",
            "--message-list-path",
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки. Символы \\n будут заменены на переносы.",  # noqa: E501
            type=Path,
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
        search_params_group.add_argument(
            "--excluded-terms",
            type=str,
            help="Исключить вакансии, если название или snippet содержит любую из подстрок (через запятую, например, junior, bitrix, дружный коллектив). Это принудительный фильтр для результатов поиска",
        )

    def run(
        self,
        tool: HHApplicantTool,
    ) -> None:
        self.tool = tool
        self.api_client = tool.api_client
        args: Namespace = tool.args
        self.application_messages = self._get_application_messages(
            args.message_list_path
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
        self.resume_id = args.resume_id
        self.right_lng = args.right_lng
        self.salary = args.salary
        self.schedule = args.schedule
        self.search = args.search
        self.search_field = args.search_field
        self.excluded_terms = self._parse_excluded_terms(args.excluded_terms)
        self.sort_point_lat = args.sort_point_lat
        self.sort_point_lng = args.sort_point_lng
        self.top_lat = args.top_lat
        self.total_pages = args.total_pages
        self.openai_chat = (
            tool.get_openai_chat(args.first_prompt) if args.use_ai else None
        )
        self._apply_similar()

    def _apply_similar(self) -> None:
        resumes: list[datatypes.Resume] = self.tool.get_resumes()
        try:
            self.tool.storage.resumes.save_batch(resumes)
        except RepositoryError as ex:
            logger.exception(ex)
        resumes = (
            list(filter(lambda x: x["id"] == self.resume_id, resumes))
            if self.resume_id
            else resumes
        )
        # Выбираем только опубликованные
        resumes = list(
            filter(lambda x: x["status"]["id"] == "published", resumes)
        )
        if not resumes:
            logger.warning("У вас нет опубликованных резюме")
            return

        me: datatypes.User = self.tool.get_me()
        seen_employers = set()

        for resume in resumes:
            self._apply_resume(
                resume=resume,
                user=me,
                seen_employers=seen_employers,
            )

        # Синхронизация откликов
        # for neg in self.tool.get_negotiations():
        #     try:
        #         self.tool.storage.negotiations.save(neg)
        #     except RepositoryError as e:
        #         logger.warning(e)

        print("📝 Отклики на вакансии разосланы!")

    def _apply_resume(
        self,
        resume: datatypes.Resume,
        user: datatypes.User,
        seen_employers: set[str],
    ) -> None:
        logger.info(
            "Начинаю рассылку откликов для резюме: %s (%s)",
            resume["alternate_url"],
            resume["title"],
        )
        print("🚀 Начинаю рассылку откликов для резюме:", resume["title"])

        placeholders = {
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": user.get("email") or "",
            "phone": user.get("phone") or "",
            "resume_title": resume.get("title") or "",
        }

        do_apply = True

        for vacancy in self._get_similar_vacancies(resume_id=resume["id"]):
            try:
                employer = vacancy.get("employer", {})

                message_placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": employer.get("name", ""),
                    **placeholders,
                }

                storage = self.tool.storage

                try:
                    storage.vacancies.save(vacancy)
                except RepositoryError as ex:
                    logger.debug(ex)

                # По факту контакты можно получить только здесь?!
                if vacancy.get("contacts"):
                    logger.debug(
                        f"Найдены контакты в вакансии: {vacancy['alternate_url']}"
                    )

                    try:
                        # logger.debug(vacancy)
                        storage.vacancy_contacts.save(vacancy)
                    except RepositoryError as ex:
                        logger.exception(ex)

                    employer_id = employer.get("id")
                    if employer_id and employer_id not in seen_employers:
                        employer_profile: datatypes.Employer = (
                            self.api_client.get(f"/employers/{employer_id}")
                        )

                        try:
                            storage.employers.save(employer_profile)
                        except RepositoryError as ex:
                            logger.exception(ex)

                if not do_apply:
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
                            "Вы получили отказ от %s",
                            vacancy["alternate_url"],
                        )
                        print("⛔ Пришел отказ от", vacancy["alternate_url"])
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

                if self._is_excluded(vacancy):
                    logger.warning(
                        "Вакансия содержит недопустимые словосочетания: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                response_letter = ""

                if self.force_message or vacancy.get(
                    "response_letter_required"
                ):
                    if self.openai_chat:
                        msg = self.pre_prompt + "\n\n"
                        msg += (
                            "Название вакансии: "
                            + message_placeholders["vacancy_name"]
                        )
                        msg += (
                            "Мое резюме:" + message_placeholders["resume_title"]
                        )
                        logger.debug("prompt: %s", msg)
                        response_letter = self.openai_chat.send_message(msg)
                    else:
                        response_letter = unescape_string(
                            rand_text(random.choice(self.application_messages))
                            % message_placeholders
                        )

                    logger.debug(response_letter)

                logger.debug(
                    "Пробуем откликнуться на вакансию: %s",
                    vacancy["alternate_url"],
                )

                if vacancy.get("has_test"):
                    logger.debug(
                        "Решаем тест: %s",
                        vacancy["alternate_url"],
                    )

                    try:
                        if not self.dry_run:
                            result = self._solve_vacancy_test(
                                vacancy_id=vacancy["id"],
                                resume_hash=resume["id"],
                                letter=response_letter,
                            )
                            if result.get("success") == "true":
                                print(
                                    "📨 Отправили отклик на вакансию с тестом",
                                    vacancy["alternate_url"],
                                )
                            else:
                                err = result.get("error")

                                if err == "negotiations-limit-exceeded":
                                    do_apply = False
                                    logger.warning("Достигли лимита на отклики")
                                else:
                                    logger.error(
                                        f"Произошла ошибка при отклике на вакансию с тестом: {vacancy['alternate_url']} - {err}"
                                    )
                    except Exception as ex:
                        logger.error(f"Произошла непредвиденная ошибка: {ex}")

                else:
                    params = {
                        "resume_id": resume["id"],
                        "vacancy_id": vacancy_id,
                        "message": response_letter,
                    }
                    try:
                        if not self.dry_run:
                            res = self.api_client.post(
                                "/negotiations",
                                params,
                                delay=random.uniform(1, 3),
                            )
                            assert res == {}
                            print(
                                "📨 Отправили отклик на вакансию",
                                vacancy["alternate_url"],
                            )
                    except Redirect:
                        logger.warning(
                            f"Игнорирую перенаправление на форму: {vacancy['alternate_url']}"  # noqa: E501
                        )
            except LimitExceeded:
                do_apply = False
                logger.warning("Достигли лимита на отклики")
            except ApiError as ex:
                logger.warning(ex)
            except (BadResponse, AIError) as ex:
                logger.error(ex)

        logger.info(
            "Закончили рассылку откликов для резюме: %s (%s)",
            resume["alternate_url"],
            resume["title"],
        )
        print("✅️ Закончили рассылку откликов для резюме:", resume["title"])

    def _get_vacancy_tests(
        self, response_url: str
    ) -> tuple[VacancyTestsData, str]:
        """Парсит данные тестов и XSRF токен через сплиты с обработкой исключений 🤖"""
        r = self.tool.session.get(response_url)

        try:
            # Парсим тесты и токен через сплиты
            tests = utils.json.loads(
                r.text.split(',"vacancyTests":')[1].split(',"counters":')[0],
                strict=False,
            )
            xsrf_token = r.text.split('"xsrfToken":"')[1].split('"')[0]

            return tests, xsrf_token

        except (IndexError, json.JSONDecodeError):
            raise ValueError("Не удалось извлечь данные теста из ответа HH")

    def _solve_vacancy_test(
        self,
        vacancy_id: str | int,
        resume_hash: str,
        letter: str = "",
    ) -> dict[str, Any]:
        """Загружает тест, ждет паузу и отправляет отклик."""
        response_url = f"https://hh.ru/applicant/vacancy_response?vacancyId={vacancy_id}&startedWithQuestion=false&hhtmFrom=vacancy"

        # Загружаем данные теста и токен
        tests, xsrf_token = self._get_vacancy_tests(response_url)

        try:
            test_data = tests[str(vacancy_id)]
        except KeyError:
            raise ValueError(
                "Отсутствуют данные теста для непосредственно вакансии."
            )

        logger.debug(f"{test_data = }")

        payload: dict[str, Any] = {
            "_xsrf": xsrf_token,
            "uidPk": test_data["uidPk"],
            "guid": test_data["guid"],
            "startTime": test_data["startTime"],
            "testRequired": test_data["required"],
            "vacancy_id": vacancy_id,
            "resume_hash": resume_hash,
            "ignore_postponed": "true",
            "incomplete": "false",
            "mark_applicant_visible_in_vacancy_country": "false",
            "country_ids": "[]",
            "lux": "true",
            "withoutTest": "no",
            "letter": letter,
        }

        for task in test_data["tasks"]:
            field_name = f"task_{task['id']}"
            solutions = task.get("candidateSolutions", [])

            if solutions:
                payload[field_name] = random.choice(solutions)["id"]
            else:
                # Рандомные эмоджи
                # payload[f"{field_name}_text"] = "".join(
                #     chr(random.randint(0x1F300, 0x1F64F))
                #     for _ in range(random.randint(3, 15))
                # )
                payload[f"{field_name}_text"] = random.choice(
                    string.ascii_lowercase + string.digits
                ) * random.randint(5, 35)

        logger.debug(f"{payload = }")

        # Ожидание перед отправкой (float)
        time.sleep(random.uniform(2.0, 3.0))

        response = self.tool.session.post(
            "https://hh.ru/applicant/vacancy_response/popup",
            data=payload,
            headers={
                "Referer": response_url,
                # x-gib-fgsscgib-w-hh и x-gib-gsscgib-w-hh вроде в куках
                # передаются и не нужны
                "X-Hhtmfrom": "vacancy",
                "X-Hhtmsource": "vacancy_response",
                "X-Requested-With": "XMLHttpRequest",
                "X-Xsrftoken": xsrf_token,
            },
        )

        logger.debug(
            "%s %s %d",
            response.request.method,
            response.url,
            response.status_code,
        )

        data = response.json()
        # logger.debug(data)

        return data

    def _get_search_params(self, page: int) -> dict:
        params = {
            "page": page,
            "per_page": self.per_page,
        }
        if self.order_by:
            params |= {"order_by": self.order_by}
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
            params["search_field"] = list(self.search_field)
        if self.employment:
            params["employment"] = list(self.employment)
        if self.area:
            params["area"] = list(self.area)
        if self.metro:
            params["metro"] = list(self.metro)
        if self.professional_role:
            params["professional_role"] = list(self.professional_role)
        if self.industry:
            params["industry"] = list(self.industry)
        if self.employer_id:
            params["employer_id"] = list(self.employer_id)
        if self.excluded_employer_id:
            params["excluded_employer_id"] = list(self.excluded_employer_id)
        if self.label:
            params["label"] = list(self.label)
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

    def _get_similar_vacancies(self, resume_id: str) -> Iterator[SearchVacancy]:
        for page in range(self.total_pages):
            logger.debug(
                f"Загружаем подходящие вакансии со страницы: {page + 1}"
            )
            params = self._get_search_params(page)
            res: PaginatedItems[SearchVacancy] = self.api_client.get(
                f"/resumes/{resume_id}/similar_vacancies",
                params,
            )

            logger.debug(f"Количество подходящих вакансий: {res['found']}")

            if not res["items"]:
                return

            yield from res["items"]

            if page >= res["pages"] - 1:
                return

    @staticmethod
    def _parse_excluded_terms(excluded_terms: str | None) -> list[str]:
        if not excluded_terms:
            return []
        return [
            x.strip() for x in excluded_terms.lower().split(",") if x.strip()
        ]

    def _is_excluded(self, vacancy: SearchVacancy) -> bool:
        snippet = vacancy.get("snippet") or {}
        combined = " ".join(
            [
                vacancy.get("name") or "",
                snippet.get("requirement") or "",
                snippet.get("responsibility") or "",
            ]
        ).lower()

        return any(v in combined for v in self.excluded_terms)

    def _get_application_messages(self, path: Path | None) -> list[str]:
        return (
            list(
                filter(
                    None,
                    map(
                        str.strip,
                        path.open(encoding="utf-8", errors="replace"),
                    ),
                )
            )
            if path
            else [
                "Здравствуйте, меня зовут %(first_name)s. {Меня заинтересовала|Мне понравилась} ваша вакансия «%(vacancy_name)s». Хотелось бы {пообщаться|задать вопросы} о ней.",
                "{Прошу|Предлагаю} рассмотреть {мою кандидатуру|мое резюме «%(resume_title)s»} на вакансию «%(vacancy_name)s». С уважением, %(first_name)s.",  # noqa: E501
            ]
        )

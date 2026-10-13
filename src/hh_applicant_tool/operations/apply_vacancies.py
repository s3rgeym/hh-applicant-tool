# Этот код, блять, уродлив. Просто ужасен
from __future__ import annotations

import argparse
import html
import logging
import random
import re
import time
from datetime import datetime
from email.message import EmailMessage
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator
from urllib.parse import (
    urlparse,
)

import requests

from ..ai.base import AIError
from ..api import BadResponse, Redirect, datatypes
from ..api.datatypes import PaginatedItems, SearchVacancy
from ..api.errors import ApiError, LimitExceeded
from ..errors import OperationError
from ..storage.repositories.errors import RepositoryError
from ..tool import BaseNamespace, BaseOperation
from ..utils.common import find_key
from ..utils.datatypes import VacancyTestsData
from ..utils.string import (
    bool2str,
    rand_text,
    render_template,
    shorten,
    strip_tags,
)

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger("hh-applicant-tool")

# Параметры поиска вакансий, задаваемые флагами
SEARCH_PARAM_NAMES = (
    "text",
    "search_field",
    "order_by",
    "per_page",
    "experience",
    "schedule",
    "work_format",
    "employment",
    "area",
    "metro",
    "professional_role",
    "industry",
    "employer_id",
    "excluded_employer_id",
    "currency",
    "salary",
    "only_with_salary",
    "label",
    "period",
    "date_from",
    "date_to",
    "top_lat",
    "bottom_lat",
    "left_lng",
    "right_lng",
    "sort_point_lat",
    "sort_point_lng",
    "no_magic",
    "premium",
)

DEFAULT_PER_PAGE = 100

DEFAULT_COVER_LETTER = """\
{Здравствуйте|Добрый день}, меня зовут %(first_name)s.\
 {Прошу|Предлагаю} рассмотреть {мою кандидатуру|мое резюме «%(resume_title)s»} на вакансию «%(vacancy_name)s».\
 С уважением, %(first_name)s."""


# Системные промпты - простые строки, не шаблоны
DEFAULT_COVER_LETTER_SYSTEM_PROMPT = (
    "Ты помогаешь соискателю писать сопроводительные письма. "
    "Пиши кратко, вежливо и по делу, не выдумывай фактов."
)
DEFAULT_AI_FILTER_SYSTEM_PROMPT = (
    "Ты определяешь, подходит ли вакансия кандидату. "
    "Отвечай одним словом: «да» или «нет»."
)

# Пользовательские промпты - шаблоны, подстановка через %(name)s
DEFAULT_COVER_LETTER_PROMPT = (
    "Сгенерируй сопроводительное письмо не более 5-7 предложений "
    "от моего имени для вакансии «%(vacancy_name)s» "
    "работодателя «%(employer_name)s». "
    "Меня зовут %(first_name)s, мое резюме: «%(resume_title)s»."
)
DEFAULT_AI_FILTER_PROMPT = """\
Резюме кандидата:
Должность: %(resume_title)s
Навыки: %(resume_skills)s

Вакансия: %(vacancy_name)s
Ключевые навыки: %(vacancy_key_skills)s
Описание: %(vacancy_description)s

Подходит ли эта вакансия кандидату?"""

DEFAULT_APPLY_MAIL_SUBJECT = "{Отклик|Резюме} на вакансию %(vacancy_name)s"
DEFAULT_APPLY_MAIL_BODY = "{Здравствуйте|Добрый день}, {прошу рассмотреть|пожалуйста рассмотрите} мое резюме %(resume_url)s на вакансию %(vacancy_name)s."


class Namespace(BaseNamespace):
    resume_id: str | None
    cover_letter: str | None
    ignore_employers: Path | None
    force_letter: bool
    ai_filter: bool | None
    ai_filter_system_prompt: str
    ai_filter_prompt: str
    cover_letter_system_prompt: str
    cover_letter_prompt: str
    dry_run: bool
    # Параметры поиска (None - не задано)
    text: str | None
    search_field: list[str] | None
    order_by: str | None
    per_page: int
    experience: str | None
    schedule: str | None
    work_format: list[str] | None
    employment: list[str] | None
    area: list[str] | None
    metro: list[str] | None
    professional_role: list[str] | None
    industry: list[str] | None
    employer_id: list[str] | None
    excluded_employer_id: list[str] | None
    currency: str | None
    salary: int | None
    only_with_salary: bool | None
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
    no_magic: bool | None
    premium: bool | None
    total_pages: int
    excluded_filter: str | None
    max_responses: int
    send_email: bool
    skip_tests: bool


class Operation(BaseOperation):
    """Откликнуться на все подходящие вакансии."""

    __aliases__ = ("apply", "apply-similar")

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "-f",
            "--force-letter",
            "--force",
            help="Всегда отправлять сопроводительное письмо при отклике",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--ai-filter",
            help="Использовать AI для фильтрации вакансий",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--total-pages",
            "--pages",
            help="Количество обрабатываемых страниц поиска",  # noqa: E501
            default=20,
            type=int,
        )
        parser.add_argument(
            "--send-email",
            help="Отправлять письмо на email компании или рекрутера с просьбой рассмотреть резюме",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--skip-tests",
            help="Пропускать тесты при откликах вместо их решения",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--excluded-filter",
            type=str,
            help="Исключить вакансии, если название или описание не соответствует шаблону. Например, `--excluded-filter 'junior|стажир|bitrix|дружн\\w+ коллектив|полиграф|open\\s*space|опенспейс|хакатон|конкурс|тестов\\w+ задан'`",
        )
        parser.add_argument(
            "--max-responses",
            type=int,
            help="Отправить не более N откликов (по умолчанию без ограничения)",
        )
        parser.add_argument(
            "--dry-run",
            help="Не отправлять отклики, а только выводить информацию",
            action=argparse.BooleanOptionalAction,
        )

        # Дальше идут параметры в точности соответствующие параметрам запроса
        # при поиске подходящих вакансий
        api_search_filters = parser.add_argument_group(
            "Фильтры для поиска вакансий",
            "Эти параметры напрямую соответствуют фильтрам поиска HeadHunter API",
        )

        api_search_filters.add_argument(
            "-s",
            "--search",
            dest="text",
            help="Строка поиска для фильтрации вакансий. Если указана, то поиск будет производиться по вакансиям. В остальных случаях отклики будут производиться по списку рекомендованных вакансий.",  # noqa: E501
            type=str,
        )
        api_search_filters.add_argument(
            "--per-page",
            help="Сколько должно быть результатов на странице",  # noqa: E501
            default=DEFAULT_PER_PAGE,
            type=int,
        )
        api_search_filters.add_argument(
            "--order-by",
            help="Сортировка вакансий",
            choices=[
                "publication_time",
                "salary_desc",
                "salary_asc",
                "relevance",
                "distance",
            ],
        )
        api_search_filters.add_argument(
            "--experience",
            help="Уровень опыта работы",
            choices=[
                "noExperience",
                "between1And3",
                "between3And6",
                "moreThan6",
            ],
        )
        api_search_filters.add_argument(
            "--schedule",
            help="Тип графика",
            choices=["fullDay", "shift", "flexible", "remote", "flyInFlyOut"],
        )
        api_search_filters.add_argument(
            "--work-format",
            nargs="+",
            help="Формат работы",
            choices=["REMOTE", "HYBRID", "ON_SITE", "FIELD_WORK"],
        )
        api_search_filters.add_argument(
            "--employment", nargs="+", help="Тип занятости"
        )
        api_search_filters.add_argument(
            "--area", nargs="+", help="Регион (area id)"
        )
        api_search_filters.add_argument(
            "--metro", nargs="+", help="Станции метро (metro id)"
        )
        api_search_filters.add_argument(
            "--professional-role", nargs="+", help="Проф. роль (id)"
        )
        api_search_filters.add_argument(
            "--industry", nargs="+", help="Индустрия (industry id)"
        )
        api_search_filters.add_argument(
            "--employer-id", nargs="+", help="ID работодателей"
        )
        api_search_filters.add_argument(
            "--excluded-employer-id", nargs="+", help="Исключить работодателей"
        )
        api_search_filters.add_argument(
            "--currency", help="Код валюты", choices=["RUR", "USD", "EUR"]
        )
        api_search_filters.add_argument(
            "--salary", type=int, help="Минимальная зарплата"
        )
        api_search_filters.add_argument(
            "--only-with-salary",
            action=argparse.BooleanOptionalAction,
            help="Только вакансии с указанной зарплатой",
        )
        api_search_filters.add_argument(
            "--label", nargs="+", help="Метки вакансий (label)"
        )
        api_search_filters.add_argument(
            "--period", type=int, help="Искать вакансии за N дней"
        )
        api_search_filters.add_argument(
            "--date-from", help="Дата публикации с (YYYY-MM-DD)"
        )
        api_search_filters.add_argument(
            "--date-to", help="Дата публикации по (YYYY-MM-DD)"
        )
        api_search_filters.add_argument(
            "--top-lat", type=float, help="Гео: верхняя широта"
        )
        api_search_filters.add_argument(
            "--bottom-lat", type=float, help="Гео: нижняя широта"
        )
        api_search_filters.add_argument(
            "--left-lng", type=float, help="Гео: левая долгота"
        )
        api_search_filters.add_argument(
            "--right-lng", type=float, help="Гео: правая долгота"
        )
        api_search_filters.add_argument(
            "--sort-point-lat",
            type=float,
            help="Координата lat для сортировки по расстоянию",
        )
        api_search_filters.add_argument(
            "--sort-point-lng",
            type=float,
            help="Координата lng для сортировки по расстоянию",
        )
        api_search_filters.add_argument(
            "--no-magic",
            action="store_true",
            help="Отключить авторазбор текста запроса",
        )
        api_search_filters.add_argument(
            "--premium",
            action=argparse.BooleanOptionalAction,
            help="Только премиум вакансии",
        )
        api_search_filters.add_argument(
            "--search-field",
            nargs="+",
            help="Поля поиска (name, company_name и т.п.)",
        )

    @property
    def api_client(self):
        return self.tool.api_client

    def run(
        self,
        tool: HHApplicantTool,
        args: Namespace,
    ) -> None:
        self.tool = tool
        config = tool.general_config
        self.cover_letter = config.get("cover_letter", DEFAULT_COVER_LETTER)
        for name in SEARCH_PARAM_NAMES:
            setattr(self, name, getattr(args, name))
        self.dry_run = args.dry_run
        self.excluded_pat = None
        if args.excluded_filter:
            try:
                self.excluded_pat = re.compile(
                    args.excluded_filter, re.IGNORECASE
                )
            except re.error as ex:
                raise OperationError(
                    f"Некорректное регулярное выражение в --excluded-filter: {ex}"
                ) from ex
        self.force_letter = args.force_letter
        self.max_responses = args.max_responses
        self.resume_id = args.resume_id
        self.send_email = args.send_email
        self.skip_tests = args.skip_tests
        self.total_pages = args.total_pages

        # Приоритет: аргумент командной строки -> конфиг -> дефолтная константа
        # Системные промпты - обычный текст, пользовательские - шаблоны
        self.cover_letter_prompt = config.get(
            "cover_letter_prompt", DEFAULT_COVER_LETTER_PROMPT
        )
        self.ai_filter_prompt = config.get(
            "ai_filter_prompt", DEFAULT_AI_FILTER_PROMPT
        )
        self.ai_filter = bool(args.ai_filter)

        self.cover_letter_ai = self.vacancy_filter_ai = None
        if args.use_ai:
            c = tool.get_openai_args("openai.cover_letter")
            c.setdefault("system_prompt", DEFAULT_COVER_LETTER_SYSTEM_PROMPT)
            c.setdefault("temperature", 0.8)
            self.cover_letter_ai = tool.get_ai_client(**c)

            if self.ai_filter:
                c = tool.get_openai_args("openai.vacancy_filter")
                c.setdefault("system_propmt", DEFAULT_AI_FILTER_PROMPT)
                self.vacancy_filter_ai = tool.get_ai_client(**c)

        self.apply_mail_subject = config.get(
            "apply_mail_subject", DEFAULT_APPLY_MAIL_SUBJECT
        )
        self.apply_mail_body = config.get(
            "apply_mail_body", DEFAULT_APPLY_MAIL_BODY
        )

        self._apply_vacancies()

    def _get_resume_info(self, resume_id: str | None) -> dict[str, str]:
        """Данные резюме для подстановки в шаблон промпта AI-фильтра."""
        info = {
            "resume_skills": "",
            "resume_about": "",
            "resume_experience": "",
        }
        if not resume_id:
            return info

        try:
            full_resume = self.api_client.get(f"/resumes/{resume_id}")
        except Exception as e:
            logger.warning(f"Не удалось получить полное резюме: {e}")
            return info

        # hh.ru отдаёт skills как null, когда поле не заполнено,
        # и .get(..., "") тут не спасает: null уже есть в ответе
        info["resume_about"] = full_resume.get("skills") or ""
        info["resume_skills"] = ", ".join(full_resume.get("skill_set") or [])

        lines = []
        for exp in full_resume.get("experience") or []:
            end = exp.get("end") or "по настоящее время"
            lines.append(
                f"- {exp.get('company') or 'Не указано'}, "
                f"{exp.get('position') or 'Не указано'} "
                f"({exp.get('start') or ''} - {end})"
            )
            if exp.get("description"):
                lines.append(f"  {exp['description']}")
        info["resume_experience"] = "\n".join(lines)

        return info

    # Если AI ответил что-то непонятное, лучше не отбрасывать вакансию
    @staticmethod
    def _parse_is_suitable_response(response: str) -> bool | None:
        answer = response.strip().lower().strip(" .!\"'«»")

        if re.match(r"(да|yes|true)\b", answer):
            return True
        if re.match(r"(нет|no|false)\b", answer):
            return False

        return None

    def _is_vacancy_suitable(
        self, vacancy: dict, placeholders: dict[str, str]
    ) -> bool:
        if not self.vacancy_filter_ai:
            return True

        full_vacancy = (
            self.api_client.get(f"/vacancies/{vacancy['id']}")
            if vacancy.get("id")
            else {}
        )
        key_skills = ", ".join(
            s["name"]
            for s in (full_vacancy.get("key_skills") or [])
            if s.get("name")
        )

        prompt = render_template(
            self.ai_filter_prompt,
            {
                **placeholders,
                "vacancy_description": strip_tags(
                    full_vacancy.get("description") or ""
                ),
                "vacancy_key_skills": key_skills,
            },
            "промпта AI-фильтра",
        )
        response = self.vacancy_filter_ai.complete(prompt)
        logger.debug("AI ответ фильтра: %s", response)

        result = self._parse_is_suitable_response(response)
        if result is None:
            logger.warning(
                "AI-фильтр дал непонятный ответ для вакансии %s: %.100s. Считаю вакансию подходящей.",
                vacancy.get("name", ""),
                response,
            )
            return True

        return result

    def _apply_vacancies(self) -> None:
        resumes: list[datatypes.Resume] = self.tool.get_resumes()
        try:
            self.tool.storage.resumes.save_batch(resumes)
        except RepositoryError as ex:
            logger.exception(ex)
        if self.resume_id:
            resumes = [x for x in resumes if x["id"] == self.resume_id]
            if not resumes:
                raise OperationError(f"Резюме {self.resume_id} не найдено")
        # Выбираем только опубликованные
        resumes = [x for x in resumes if x["status"]["id"] == "published"]
        if not resumes:
            raise OperationError("У вас нет опубликованных резюме")

        me: datatypes.User = self.tool.get_me()
        seen_employers = set()

        for resume in resumes:
            limit_reached = self._apply_resume(
                resume=resume,
                user=me,
                seen_employers=seen_employers,
            )
            if limit_reached:
                logger.warning(
                    "Лимит откликов hh.ru исчерпан. Пропускаю оставшиеся резюме."
                )
                print("⛔ Лимит откликов hh.ru исчерпан. Попробуйте позже.")
                break

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
    ) -> bool:
        logger.info(
            "Начинаю рассылку откликов для резюме: %s (%s)",
            resume["alternate_url"],
            resume["title"],
        )
        print("🚀 Начинаю рассылку откликов для резюме:", resume["title"])
        applied_count = 0
        limit_reached = False

        placeholders = {
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": user.get("email") or "",
            "phone": user.get("phone") or "",
            "resume_hash": resume.get("id") or "",
            "resume_title": resume.get("title") or "",
            "resume_url": resume.get("alternate_url") or "",
        }

        if self.ai_filter:
            placeholders.update(self._get_resume_info(resume.get("id")))

        do_apply = True
        storage = self.tool.storage
        site_emails = {}

        for vacancy in self._get_vacancies(resume_id=resume["id"]):
            if self.max_responses and applied_count >= self.max_responses:
                logger.info(
                    "Достигнут лимит откликов --max-responses (%d). Останавливаюсь.",
                    self.max_responses,
                )
                break
            try:
                employer = vacancy.get("employer", {})

                message_placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "vacancy_url": vacancy.get("alternate_url") or "",
                    "employer_name": employer.get("name", ""),
                    **placeholders,
                }

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

                if vacancy.get("has_test") and self.skip_tests:
                    logger.debug(
                        "Пропускаю вакансию с тестом %s",
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
                    logger.info(
                        "Вакансия попала под фильтр: %s",
                        vacancy["alternate_url"],
                    )

                    if not self.dry_run:
                        self._save_skipped_vacancy(
                            vacancy, "excluded_filter", resume["id"]
                        )

                        self.api_client.put(
                            f"/vacancies/blacklisted/{vacancy['id']}"
                        )
                        logger.info(
                            "Вакансия добавлена в черный список: %s",
                            vacancy["alternate_url"],
                        )
                    continue

                # AI фильтрация вакансий
                if self.ai_filter and self.vacancy_filter_ai:
                    if self._is_vacancy_already_skipped(vacancy, resume["id"]):
                        logger.debug(
                            "Вакансия уже была отклонена ранее: %s",
                            vacancy["alternate_url"],
                        )
                        print(
                            "⏩ Вакансия уже отклонена ранее",
                            vacancy["alternate_url"],
                        )
                        continue

                    if not self._is_vacancy_suitable(
                        vacancy, message_placeholders
                    ):
                        logger.info(
                            "Вакансия отклонена AI фильтром: %s",
                            vacancy["alternate_url"],
                        )
                        print(
                            "🧠 AI посчитал неподходящей",
                            vacancy["alternate_url"],
                        )

                        self._save_skipped_vacancy(
                            vacancy, "ai_rejected", resume["id"]
                        )
                        continue

                # Перед откликом выгружаем профиль компании
                employer_id = employer.get("id")
                if employer_id and employer_id not in seen_employers:
                    employer_profile: datatypes.Employer = self.api_client.get(
                        f"/employers/{employer_id}"
                    )

                    # Какая блядь эту строку стерла?
                    seen_employers.add(employer_id)

                    try:
                        storage.employers.save(employer_profile)
                    except RepositoryError as ex:
                        logger.exception(ex)

                    # Если есть сайт, то ищем на нем емейлы для отправки письма
                    if self.send_email and (
                        site_url := (
                            employer_profile.get("site_url") or ""
                        ).strip()
                    ):
                        site_url = (
                            site_url
                            if "://" in site_url
                            else "https://" + site_url
                        )
                        logger.debug("visit site: %s", site_url)

                        try:
                            site_info = self._parse_site(site_url)
                            site_emails[employer_id] = site_info["emails"]
                        except requests.RequestException as ex:
                            site_info = None
                            logger.error(ex)

                        if site_info:
                            logger.debug("site info: %r", site_info)

                            # try:
                            #     subdomains = self._get_subdomains(site_url)
                            # except requests.RequestException as ex:
                            #     subdomains = []
                            #     logger.error(ex)

                            try:
                                storage.employer_sites.save(
                                    {
                                        "site_url": site_url,
                                        "employer_id": employer_id,
                                        "subdomains": [],
                                        **site_info,
                                    }
                                )
                            except RepositoryError as ex:
                                logger.exception(ex)

                letter = ""

                if self.force_letter or vacancy.get("response_letter_required"):
                    if self.cover_letter_ai:
                        prompt = render_template(
                            self.cover_letter_prompt,
                            message_placeholders,
                            "промпта сопроводительного письма",
                        )
                        logger.debug("prompt: %s", prompt)
                        letter = self.cover_letter_ai.complete(prompt)
                    else:
                        letter = render_template(
                            rand_text(self.cover_letter),
                            message_placeholders,
                            "сопроводительного письма",
                        )

                    logger.debug(letter)

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
                                letter=letter,
                            )
                            if result.get("success") == "true":
                                applied_count += 1
                                print(
                                    "📨 Отправили отклик на вакансию с тестом",
                                    vacancy["alternate_url"],
                                )
                            else:
                                err = (
                                    result.get("error")
                                    if isinstance(result, dict)
                                    else None
                                )

                                if err == "negotiations-limit-exceeded":
                                    do_apply = False
                                    limit_reached = True
                                    logger.warning(
                                        "Достигли лимита на отклики (отправлено в этой сессии: %d)",
                                        applied_count,
                                    )
                                    break
                                else:
                                    logger.error(
                                        "Произошла ошибка при отклике на вакансию с тестом: %s, result: %.300s",
                                        vacancy["alternate_url"],
                                        result,
                                    )

                            # Какой-то негодяй тут continue убрал и отклик
                            # повторно отправлялся
                            continue

                    except Exception as ex:
                        logger.error(f"Произошла непредвиденная ошибка: {ex}")
                        continue

                params = {
                    "resume_id": resume["id"],
                    "vacancy_id": vacancy_id,
                    "message": letter,
                }

                try:
                    if not self.dry_run:
                        res = self.api_client.post(
                            "/negotiations",
                            params,
                            delay=random.uniform(1, 3),
                        )
                        assert res == {}
                        applied_count += 1
                        print(
                            "📨 Отправили отклик на вакансию",
                            vacancy["alternate_url"],
                        )
                except Redirect:
                    logger.warning(
                        f"Игнорирую перенаправление на форму: {vacancy['alternate_url']}"  # noqa: E501
                    )
                    continue

                # Отправка письма на email
                if self.send_email:
                    # fix NoneType has no attribute get
                    # contacts может быть null
                    mail_to: str | list[str] | None = (
                        vacancy.get("contacts") or {}
                    ).get("email") or site_emails.get(employer_id)
                    if mail_to:
                        mail_to = (
                            ", ".join(mail_to)
                            if isinstance(mail_to, list)
                            else mail_to
                        )
                        mail_subject = render_template(
                            self.apply_mail_subject,
                            message_placeholders,
                            "apply_mail_subject",
                            randomize_text=True,
                        )
                        mail_body = render_template(
                            self.apply_mail_body,
                            message_placeholders,
                            "apply_mail_body",
                            randomize_text=True,
                            escape_html=True,
                        )
                        try:
                            self._send_email(mail_to, mail_subject, mail_body)
                            print(
                                "📧 Отправлено письмо на email по поводу вакансии",
                                vacancy["alternate_url"],
                            )
                        except Exception as ex:
                            logger.error(f"Ошибка отправки письма: {ex}")
            except LimitExceeded:
                do_apply = False
                limit_reached = True
                logger.warning(
                    "Достигли лимита на отклики (отправлено в этой сессии: %d)",
                    applied_count,
                )
                break
            except ApiError as ex:
                logger.warning(ex)
            except (BadResponse, AIError) as ex:
                logger.error(ex)

        logger.info(
            "Закончили рассылку откликов для резюме: %s (%s). Отправлено: %d",
            resume["alternate_url"],
            resume["title"],
            applied_count,
        )
        print(
            f"✅️ Закончили рассылку для резюме: {resume['title']}. Отправлено: {applied_count}"
        )
        return limit_reached

    def _send_email(self, to: str, subject: str, body: str) -> None:
        cfg = self.tool.config.get("smtp", {})
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.get("from") or cfg.get("user")
        msg["To"] = to
        msg.set_content(body, subtype="html")
        self.tool.smtp.send_message(msg)

    def _get_vacancy_tests(self, response_url: str) -> VacancyTestsData | None:
        """Парсит тесты"""
        res = self.tool.get_initial_state(response_url)
        return find_key(res, "vacancyTests")

    def _solve_vacancy_test(
        self,
        vacancy_id: str | int,
        resume_hash: str,
        letter: str = "",
    ) -> dict[str, Any]:
        """Загружает тест, ждет паузу и отправляет отклик."""
        response_url = f"{self.tool.base_url}/applicant/vacancy_response?vacancyId={vacancy_id}&startedWithQuestion=false&hhtmFrom=vacancy"

        if not (tests_data := self._get_vacancy_tests(response_url)):
            raise ValueError(f"Данные тестов не найдены на {response_url}.")

        if not (test_data := tests_data.get(str(vacancy_id))):
            raise ValueError(
                f"Пустые данные теста вакансии vacancy_id={vacancy_id}"
            )

        logger.debug(f"{test_data = }")

        payload: dict[str, Any] = {
            "_xsrf": self.tool.xsrf_token,
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
            solutions = task.get("candidateSolutions") or []
            question = (task.get("description") or "").strip()

            if solutions:
                if self.cover_letter_ai:
                    options = "\n".join(
                        [
                            f"{s['id']}: {strip_tags(s['text'])}"
                            for s in solutions
                        ]
                    )
                    prompt = (
                        f"Вопрос: {question}\n"
                        f"Варианты:\n{options}\n"
                        f"Выбери ID правильного ответа. Пришли только ID."
                    )
                    ai_answer = self.cover_letter_ai.complete(prompt).strip()
                    # Ищем ID в ответе AI на случай лишнего текста
                    match = re.search(r"\d+", ai_answer)
                    selected_id = (
                        match.group(0) if match else solutions[0]["id"]
                    )
                    payload[field_name] = selected_id
                else:
                    yes_solution = next(
                        filter(lambda x: x["text"].lower() == "да", solutions),
                        None,
                    )

                    payload[field_name] = (
                        yes_solution["id"]
                        if yes_solution
                        # По статистике правильный ответ в большинстве случаев
                        # находится посередине
                        else solutions[len(solutions) // 2]["id"]
                    )
            else:
                # Рандомные эмоджи
                # payload[f"{field_name}_text"] = "".join(
                #     chr(random.randint(0x1F300, 0x1F64F))
                #     for _ in range(random.randint(3, 15))
                # )

                if "://" in question:
                    answer = rand_text(
                        "{{Простите|Извините}, но я не перехожу по {внешним|сторонним} ссылкам, так как {опасаюсь взлома|не хочу {быть взломанным|подхватить вирус|чтобы у меня {со|с банковского} счета украли деньги}}.|У меня нет времени на заполнение анкет и гуглодоков}"
                    )
                elif self.cover_letter_ai:
                    prompt = f"Дай краткий и профессиональный ответ на вопрос: {question}"
                    answer = self.cover_letter_ai.complete(prompt)
                    ## добавляем ответ AI на вопрос теста##
                    logger.debug("AI ответ= %r", answer)
                # Тупоеблые любят вопросы с ответами да/нет, где ответ да является правильным в большинстве случаев.
                else:
                    answer = "Да"

                payload[f"{field_name}_text"] = answer

        logger.debug(f"{payload = }")

        # Ожидание перед отправкой (float)
        time.sleep(random.uniform(2.0, 3.0))

        response = self.tool.session.post(
            f"{self.tool.base_url}/applicant/vacancy_response/popup",
            data=payload,
            headers={
                "Referer": response_url,
                # x-gib-fgsscgib-w-hh и x-gib-gsscgib-w-hh вроде в куках
                # передаются и не нужны
                "X-Hhtmfrom": "vacancy",
                "X-Hhtmsource": "vacancy_response",
                "X-Requested-With": "XMLHttpRequest",
                "X-Xsrftoken": self.tool.xsrf_token,
            },
        )

        logger.debug(
            "%s %s %d",
            response.request.method,
            response.url,
            response.status_code,
        )

        try:
            data = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as ex:
            logger.warning(
                "Ответ на отклик с тестом не является JSON (status=%s, %s), result: %s",
                response.status_code,
                response.url,
                shorten(response.text, 300),
            )
            raise ValueError(
                "Эндпоинт отклика на тест вернул не-JSON ответ "
                "(возможно, перенаправление на капчу или форму)."
            ) from ex

        return data

    def _parse_site(self, url: str) -> dict[str, Any]:
        with self.tool.session.get(url, timeout=10) as r:
            val = lambda m: html.unescape(m.group(1)) if m else ""

            title = val(re.search(r"<title>(.*?)</title>", r.text, re.I | re.S))
            description = val(
                re.search(
                    r'<meta name="description" content="(.*?)"', r.text, re.I
                )
            )
            generator = val(
                re.search(
                    r'<meta name="generator" content="(.*?)"', r.text, re.I
                )
            )

            # Поиск email
            emails = set(
                m.group(0)
                # Исключение всякого мусора типа energy-software-slider-225x225@2x.png
                for m in re.finditer(
                    r"\b[a-z][a-z0-9_.-]+@([a-z0-9][a-z0-9-]+)(?!\.(?:png|jpe?g|bmp|gif|ico|js|css)\b)(\.[a-z0-9][a-z0-9-]+)+\b",
                    r.text,
                )
            )

            return {
                "title": title,
                "description": description,
                "generator": generator,
                "emails": list(emails),
                "server_name": r.headers.get("Server"),
                "powered_by": r.headers.get("X-Powered-By"),
                # Не работает, если отключена проверка сертификата
                "ip_address": r.raw._connection.sock.getpeername()[0]
                if r.raw._connection
                else None,
            }

    # Слишком тормознутая... Толи российские айпи заблокированы
    def _get_subdomains(self, url: str) -> set[str]:
        domain = urlparse(url).netloc
        r = self.tool.session.get(
            "https://crt.sh",
            params={"q": domain, "output": "json"},
            timeout=30,
        )

        r.raise_for_status()

        return set(
            item
            for item in chain.from_iterable(
                item["name_value"].split() for item in r.json()
            )
            if not item.startswith("*.")
        )

    def _get_search_params(self, page: int) -> dict:
        params = {
            "page": page,
            "per_page": self.per_page,
        }
        if self.order_by:
            params |= {"order_by": self.order_by}
        if self.schedule:
            params["schedule"] = self.schedule
        if self.work_format:
            params["work_format"] = list(self.work_format)
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

    def _get_vacancies(
        self,
        resume_id: str,
    ) -> Iterator[SearchVacancy]:
        for page in range(self.total_pages):
            logger.debug(f"Загружаем вакансии со страницы: {page + 1}")
            params = self._get_search_params(page)

            logger.debug(params)

            if self.text:
                search_endpoint = "/vacancies"
                params |= {"text": self.text}
            else:
                search_endpoint = f"/resumes/{resume_id}/similar_vacancies"
            res: PaginatedItems[SearchVacancy] = self.api_client.get(
                search_endpoint,
                params,
            )
            logger.debug(f"Количество вакансий: {res['found']}")

            if not res["items"]:
                return

            yield from res["items"]

            if page >= res["pages"] - 1:
                return

    def _is_excluded(self, vacancy: SearchVacancy) -> bool:
        if not self.excluded_pat:
            return False

        snippet = vacancy.get("snippet", {})
        vacancy_summary = " ".join(
            filter(
                None,
                [
                    vacancy.get("name"),
                    snippet.get("requirement"),
                    snippet.get("responsibility"),
                ],
            )
        )

        logger.debug(vacancy_summary)

        if self.excluded_pat.search(vacancy_summary):
            return True

        # Грузим полный текст вакансии только, если предыдущий фильтр не сработал
        state = self.tool.get_initial_state(
            self.tool.base_url + "/vacancy/" + vacancy["id"]
        )
        description = find_key(state, "description")
        if not description:
            logger.warning(
                "Не удалось найти описание вакансии на странице: %s",
                vacancy["alternate_url"],
            )
            return False

        description = strip_tags(description)
        logger.debug(description[:2047])
        return bool(self.excluded_pat.search(description))

    def _is_vacancy_already_skipped(
        self, vacancy: SearchVacancy, resume_id: str | None = None
    ) -> bool:
        try:
            vacancy_id = vacancy["id"]

            if resume_id:
                if any(
                    self.tool.storage.skipped_vacancies.find(
                        resume_id=resume_id,
                        vacancy_id=vacancy_id,
                    )
                ):
                    return True

            return any(
                self.tool.storage.skipped_vacancies.find(
                    resume_id="",
                    vacancy_id=vacancy_id,
                )
            )

        except Exception:
            return False

    def _save_skipped_vacancy(
        self,
        vacancy: SearchVacancy,
        reason: str,
        resume_id: str | None = None,
    ) -> None:
        try:
            employer = vacancy.get("employer", {})
            self.tool.storage.skipped_vacancies.save(
                {
                    "resume_id": resume_id or "",
                    "vacancy_id": vacancy["id"],
                    "reason": reason,
                    "alternate_url": vacancy.get("alternate_url"),
                    "name": vacancy.get("name"),
                    "employer_name": employer.get("name"),
                    "created_at": datetime.now(),
                }
            )
        except Exception as ex:
            logger.warning(f"Не удалось сохранить пропущенную вакансию: {ex}")

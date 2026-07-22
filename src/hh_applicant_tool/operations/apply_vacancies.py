from __future__ import annotations

import argparse
import asyncio
import html
import logging
import random
import re
import time
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Literal
from urllib.parse import urlparse

import requests

from ..ai.base import AIError
from ..api import BadResponse, Redirect, datatypes
from ..api.datatypes import PaginatedItems, SearchVacancy
from ..api.errors import ApiError, CaptchaRequired, LimitExceeded
from ..main import BaseNamespace, BaseOperation
from ..storage.repositories.errors import RepositoryError
from ..utils.json import JSONDecoder
from ..utils.string import (
    bool2str,
    rand_text,
    strip_tags,
    unescape_string,
)

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class VacancyResponseFormParser(HTMLParser):
    """Парсер актуальной HTML-формы отклика HH.

    HH больше не обязан отдавать данные тестов в JS-поле vacancyTests. Поэтому
    берём источник правды ниже уровнем — реальные поля формы, которые браузер
    отправляет при отклике.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[dict[str, Any]] = []
        self.textareas: list[dict[str, str]] = []
        self.selects: list[dict[str, Any]] = []
        self.questions: list[str] = []

        self._label_stack: list[dict[str, Any]] = []
        self._textarea: dict[str, Any] | None = None
        self._select: dict[str, Any] | None = None
        self._option: dict[str, Any] | None = None
        self._question_depth = 0
        self._question_parts: list[str] = []
        self._current_question = ""

    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {k.lower(): v or "" for k, v in attrs}

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attrs_dict = self._attrs(attrs)

        if self._question_depth and tag not in self._VOID_TAGS:
            self._question_depth += 1
        elif attrs_dict.get("data-qa") == "task-question":
            self._question_depth = 1
            self._question_parts = []

        if tag == "label":
            self._label_stack.append({"text": [], "input_indexes": []})
            return

        if tag == "input":
            item = {
                "type": attrs_dict.get("type", "text").lower(),
                "name": attrs_dict.get("name", ""),
                "value": attrs_dict.get("value", ""),
                "checked": "checked" in attrs_dict,
                "label": "",
                "question": self._current_question,
            }
            self.inputs.append(item)
            if self._label_stack:
                self._label_stack[-1]["input_indexes"].append(
                    len(self.inputs) - 1
                )
            return

        if tag == "textarea":
            self._textarea = {
                "name": attrs_dict.get("name", ""),
                "value": "",
                "parts": [],
                "question": self._current_question,
            }
            return

        if tag == "select":
            self._select = {
                "name": attrs_dict.get("name", ""),
                "options": [],
                "question": self._current_question,
            }
            return

        if tag == "option" and self._select is not None:
            self._option = {
                "value": attrs_dict.get("value", ""),
                "text": [],
                "selected": "selected" in attrs_dict,
            }

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_stack:
            label = self._label_stack.pop()
            label_text = self._clean_text(" ".join(label["text"]))
            for input_index in label["input_indexes"]:
                self.inputs[input_index]["label"] = label_text

        if tag == "textarea" and self._textarea is not None:
            self._textarea["value"] = self._clean_text(
                " ".join(self._textarea.pop("parts"))
            )
            self.textareas.append(self._textarea)
            self._textarea = None

        if tag == "option" and self._select is not None and self._option:
            self._option["text"] = self._clean_text(
                " ".join(self._option["text"])
            )
            self._select["options"].append(self._option)
            self._option = None

        if tag == "select" and self._select is not None:
            self.selects.append(self._select)
            self._select = None

        if self._question_depth:
            self._question_depth -= 1
            if self._question_depth == 0:
                question = self._clean_text(" ".join(self._question_parts))
                if question:
                    self.questions.append(question)
                    self._current_question = question
                self._question_parts = []

    def handle_data(self, data: str) -> None:
        if self._label_stack:
            self._label_stack[-1]["text"].append(data)
        if self._textarea is not None:
            self._textarea["parts"].append(data)
        if self._option is not None:
            self._option["text"].append(data)
        if self._question_depth:
            self._question_parts.append(data)

    def hidden_payload(self) -> dict[str, str]:
        return {
            item["name"]: item["value"]
            for item in self.inputs
            if item["name"] and item["type"] == "hidden"
        }

    def choice_groups(self) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in self.inputs:
            if item["name"] and item["type"] in {"radio", "checkbox"}:
                groups.setdefault(item["name"], []).append(item)
        return groups

    def text_inputs(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.inputs
            if item["name"]
            and item["type"] in {"text", "search", "email", "url", "tel"}
        ]


class Namespace(BaseNamespace):
    resume_id: str | None
    letter_file: Path | None
    ignore_employers: Path | None
    force_message: bool
    use_ai: bool
    ai_filter: Literal["heavy", "light"] | None
    ai_rate_limit: int
    system_prompt: str
    message_prompt: str
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
    excluded_filter: str | None
    max_responses: int
    send_email: bool
    skip_tests: bool
    only_with_tests: bool


class Operation(BaseOperation):
    """Откликнуться на все подходящие вакансии."""

    __aliases__ = ("apply", "apply-similar")

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "--search",
            help="Строка поиска для фильтрации вакансий. Если указана, то поиск будет производиться по вакансиям. В остальных случаях отклики будут производиться по списку рекомендованных вакансий.",  # noqa: E501
            type=str,
        )
        parser.add_argument(
            "-L",
            "--letter-file",
            "--letter",
            help="Путь до файла с текстом сопроводительного письма.",
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
            "--ai-filter",
            help="Использовать AI для фильтрации вакансий. Режимы: heavy - полный анализ вакансии и резюме, light - быстрый анализ по названию и навыкам",
            choices=["heavy", "light"],
            default=None,
        )
        parser.add_argument(
            "--ai-rate-limit",
            help="Лимит запросов к AI в минуту для фильтрации",
            type=int,
            default=40,
        )
        parser.add_argument(
            "--system-prompt",
            "--ai-system",
            help="Системный промпт для AI генерации сопроводительных писем",
            default="Напиши сопроводительное письмо для отклика на эту вакансию. Не используй placeholder'ы, твой ответ будет отправлен без обработки.",  # noqa: E501
        )
        parser.add_argument(
            "--message-prompt",
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
            "--send-email",
            help="Отправлять письмо на email компании или рекрутера с просьбой рассмотреть резюме",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--skip-tests",
            help="Пропускать тесты при откликах вместо",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--only-with-tests",
            help="Откликаться только на вакансии с тестами",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--excluded-filter",
            type=str,
            help=r"Исключить вакансии, если название или описание не соответствует шаблону. Например, `--excluded-filter 'junior|стажир|bitrix|дружн\w+ коллектив|полиграф|open\s*space|опенспейс|хакатон|конкурс|тестов\w+ задан'`",
        )
        parser.add_argument(
            "--max-responses",
            type=int,
            help="Пропускать отклик на вакансии с более чем N откликов (не реализован)",
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
        api_search_filters.add_argument(
            "--experience",
            help="Уровень опыта работы (noExperience, between1And3, between3And6, moreThan6)",
            type=str,
            default=None,
        )
        api_search_filters.add_argument(
            "--schedule",
            help="Тип графика (fullDay, shift, flexible, remote, flyInFlyOut)",
            type=str,
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
            "--currency", help="Код валюты (RUR, USD, EUR)"
        )
        api_search_filters.add_argument(
            "--salary", type=int, help="Минимальная зарплата"
        )
        api_search_filters.add_argument(
            "--only-with-salary",
            default=False,
            action=argparse.BooleanOptionalAction,
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
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Только премиум вакансии",
        )
        api_search_filters.add_argument(
            "--search-field",
            nargs="+",
            help="Поля поиска (name, company_name и т.п.)",
        )

    cover_letter: str = "{Здравствуйте|Добрый день}, меня зовут %(first_name)s. {Прошу|Предлагаю} рассмотреть {мою кандидатуру|мое резюме «%(resume_title)s»} на вакансию «%(vacancy_name)s». С уважением, %(first_name)s."

    @property
    def api_client(self):
        return self.tool.api_client

    @property
    def args(self) -> Namespace:
        return self._args

    def run(
        self,
        tool: HHApplicantTool,
        args: Namespace,
    ) -> None:
        self.tool = tool
        self._args = args
        self.cover_letter = (
            args.letter_file.read_text(encoding="utf-8", errors="ignore")
            if args.letter_file
            else self.cover_letter
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
        self.excluded_filter = args.excluded_filter
        self.experience = args.experience
        self.force_message = args.force_message
        self.industry = args.industry
        self.label = args.label
        self.left_lng = args.left_lng
        self.max_responses = args.max_responses
        self.metro = args.metro
        self.no_magic = args.no_magic
        self.only_with_salary = args.only_with_salary
        self.order_by = args.order_by
        self.per_page = args.per_page
        self.period = args.period
        self.message_prompt = args.message_prompt
        self.premium = args.premium
        self.professional_role = args.professional_role
        self.resume_id = args.resume_id
        self.right_lng = args.right_lng
        self.salary = args.salary
        self.schedule = args.schedule
        self.search = args.search
        self.search_field = args.search_field
        self.sort_point_lat = args.sort_point_lat
        self.sort_point_lng = args.sort_point_lng
        self.top_lat = args.top_lat
        self.total_pages = args.total_pages
        self.cover_letter_ai = (
            tool.get_cover_letter_ai(args.system_prompt)
            if args.use_ai
            else None
        )
        self.ai_filter = args.ai_filter
        self.vacancy_filter_ai = None
        self._resume_analysis_cache: dict[tuple[str | None, str], str] = {}

        self._apply_vacancies()

    def _get_full_resume(self, resume_id: str) -> dict:
        return self.api_client.get(f"/resumes/{resume_id}")

    def _analyze_resume_heavy(self, resume: dict) -> str:
        resume_id = resume.get("id")
        cache_key = (resume_id, "heavy")
        if cache_key in self._resume_analysis_cache:
            return self._resume_analysis_cache[cache_key]

        if resume_id:
            try:
                full_resume = self._get_full_resume(resume_id)

                parts = []

                title = full_resume.get("title", "")
                if title:
                    parts.append(f"Должность: {title}")

                if "skills" in full_resume:
                    parts.append("\n---------- О СЕБЕ ----------")
                    parts.append(full_resume.get("skills", ""))

                if "skill_set" in full_resume and full_resume["skill_set"]:
                    parts.append("\n---------- НАВЫКИ ----------")
                    skills_row = ", ".join(full_resume["skill_set"])
                    parts.append(skills_row)

                if "experience" in full_resume:
                    parts.append("\n---------- ОПЫТ РАБОТЫ ----------")
                    for exp in full_resume.get("experience", []):
                        company = exp.get("company", "Не указано")
                        position = exp.get("position", "Не указано")
                        start = exp.get("start", "")
                        end = exp.get("end") or "по настоящее время"

                        parts.append(f"\n- {company}")
                        parts.append(f" Должность: {position}")
                        parts.append(f" Период: {start} - {end}")

                        description = exp.get("description")
                        if description:
                            parts.append(" Описание:")
                            parts.append(f" {description}")

                result = "\n".join(parts)
                self._resume_analysis_cache[cache_key] = result
                return result

            except Exception as e:
                logger.warning(f"Не удалось получить полное резюме: {e}")

        return ""

    def _analyze_resume_light(self, resume: dict) -> str:
        resume_id = resume.get("id")
        cache_key = (resume_id, "light")
        if cache_key in self._resume_analysis_cache:
            return self._resume_analysis_cache[cache_key]

        parts = []

        full_resume = self._get_full_resume(resume_id)

        title = full_resume.get("title", "")
        if title:
            parts.append(f"Должность: {title}")

        if "skill_set" in full_resume and full_resume["skill_set"]:
            parts.append("Навыки: ")
            skills_row = ", ".join(full_resume["skill_set"])
            parts.append(skills_row)

        result = "\n".join(parts)
        self._resume_analysis_cache[cache_key] = result
        return result

    def _get_vacancy_key_skills(self, vacancy_id: str | int) -> str:
        try:
            full_vacancy = self.api_client.get(f"/vacancies/{vacancy_id}")
            key_skills_data = full_vacancy.get("key_skills") or []
            return ", ".join(
                s["name"] for s in key_skills_data if s.get("name")
            )
        except Exception as e:
            logger.warning(
                "Не удалось получить key_skills вакансии %s: %s", vacancy_id, e
            )
            return ""

    def _build_vacancy_context(
        self,
        vacancy: dict,
        full_vacancy: dict | None = None,
        include_full: bool = False,
    ) -> str:
        parts: list[str] = []

        name = vacancy.get("name")
        if name:
            parts.append(f"Вакансия: {name}")

        if full_vacancy:
            description = full_vacancy.get("description")
            if description:
                parts.append(f"Описание: {strip_tags(description)}")
        else:
            if vacancy.get("id"):
                key_skills = self._get_vacancy_key_skills(vacancy["id"])
                if key_skills:
                    parts.append(f"Ключевые навыки: {key_skills}")

        return "\n".join(parts)

    def _ask_ai_suitability(
        self, prompt: str, vacancy_name: str, log_suffix: str = ""
    ) -> bool:
        MAX_RETRIES = 3

        if not self.vacancy_filter_ai:
            return True

        for attempt in range(MAX_RETRIES):
            try:
                response = self.vacancy_filter_ai.complete(prompt).strip()

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "AI %s ответ (попытка %d): %s",
                        log_suffix,
                        attempt + 1,
                        response,
                    )

                result = self._parse_ai_json_response(response)
                if result is not None:
                    if result:
                        return True
                    logger.info(
                        "Вакансия %s отклонена AI %s", vacancy_name, log_suffix
                    )
                    return False

                # Если не удалось распарсить JSON, повторяем запрос
                logger.warning(
                    "AI %s не дал валидный JSON для вакансии %s (попытка %d/%d)",
                    log_suffix,
                    vacancy_name,
                    attempt + 1,
                    MAX_RETRIES,
                )
                continue

            except AIError as e:
                # ChatOpenAI уже делает retry для 429, поэтому здесь только логируем
                logger.error("Ошибка AI %s: %s", log_suffix, e)
                return True

        logger.warning(
            "AI %s не дал валидный JSON после %d попыток для вакансии %s",
            log_suffix,
            MAX_RETRIES,
            vacancy_name,
        )
        return True

    def _parse_ai_json_response(self, response: str) -> bool | None:
        response = response.strip().lower()

        if response in ("да", "yes", "true"):
            return True
        if response in ("нет", "no", "false"):
            return False

        import re

        from ..utils import json as utils_json

        if response.startswith("```"):
            response = re.sub(r"^```(?:json)?\s*", "", response)
            response = re.sub(r"\s*```$", "", response)

        json_match = re.search(
            r'\{[^{}]*"suitable"\s*:\s*(true|false)[^{}]*\}',
            response,
            re.IGNORECASE,
        )
        if json_match:
            try:
                data = utils_json.loads(json_match.group(0))
                return data.get("suitable")
            except Exception:
                pass

        return None

    # КТО ЭТО ПРОЧИТАЛ ТОТ ПИД@РАС
    def _is_vacancy_suitable_heavy(self, vacancy: dict) -> bool:
        full_vacancy = None
        if vacancy.get("id"):
            full_vacancy = self.api_client.get(f"/vacancies/{vacancy['id']}")

        vacancy_info = self._build_vacancy_context(
            vacancy,
            full_vacancy=full_vacancy,
            include_full=True,
        )
        prompt = f"Вакансия: {vacancy_info}"
        return self._ask_ai_suitability(
            prompt, vacancy.get("name", ""), "(heavy)"
        )

    def _is_vacancy_suitable_light(self, vacancy: dict) -> bool:
        vacancy_info = self._build_vacancy_context(vacancy, include_full=False)
        prompt = f"Вакансия: {vacancy_info}"
        return self._ask_ai_suitability(
            prompt, vacancy.get("name", ""), "(light)"
        )

    def _build_filter_system_prompt_heavy(self, resume_analysis: str) -> str:
        return f"""
Определи, подходит ли вакансия кандидату.

Смотри в первую очередь на тип работы (роль), а не на технологии.

Правила:

1. Если работа по сути другая -> suitable = false

2. Если роль совпадает или очень близкая:
   - есть пересечения по задачам или навыкам -> suitable = true
   - даже частичное совпадение допустимо

3. Общие технологии сами по себе ничего не значат.
   Если работа разная, это не делает вакансию подходящей.

4. Если данных мало:
   - ориентируйся на название роли

Не пиши объяснения.
Ответ строго JSON:
{{"suitable": true}} или {{"suitable": false}}

Кандидат:
{resume_analysis}
"""

    def _build_filter_system_prompt_light(self, resume_analysis: str) -> str:
        return f"""
Ты делаешь очень грубую проверку: подходит вакансия или нет.

Используй только:
- название резюме
- список навыков резюме
- название вакансии
- явно указанные ключевые навыки вакансии

Не анализируй описание, обязанности, контекст, домен, уровень, карьерный рост и прочую воду.
Не додумывай ничего, чего нет в тексте.

Правила:
- если название вакансии и резюме в одной профессии или близких ролях, и есть хотя бы частичное совпадение по ключевым навыкам -> suitable = true
- если роли явно разные или совпадений по навыкам почти нет -> suitable = false
- если данных мало -> ориентируйся только на явные совпадения, без фантазий

Ответ только JSON:
{{"suitable": true}} или {{"suitable": false}}

Кандидат:
{resume_analysis}
"""

    SEL_CAPTCHA_IMAGE = 'img[data-qa="account-captcha-picture"]'
    SEL_CAPTCHA_INPUT = 'input[data-qa="account-captcha-input"]'

    # Даже куки не грузятся, исправь
    async def _solve_captcha_async(self, captcha_url: str) -> bool:
        from playwright.async_api import async_playwright

        captcha_ai = self.tool.get_captcha_ai()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()

                await page.goto(captcha_url, timeout=30000)

                captcha_element = await page.wait_for_selector(
                    self.SEL_CAPTCHA_IMAGE, timeout=10000, state="visible"
                )

                img_bytes = await captcha_element.screenshot()

                captcha_text = await asyncio.to_thread(
                    captcha_ai.solve_captcha, img_bytes
                )

                if not captcha_text:
                    logger.error("AI не смог распознать капчу")
                    return False

                logger.info(f"Распознанный текст капчи: {captcha_text}")

                await page.fill(self.SEL_CAPTCHA_INPUT, captcha_text)
                await page.press(self.SEL_CAPTCHA_INPUT, "Enter")

                await page.wait_for_load_state("networkidle", timeout=15000)

                cookies = await context.cookies()
                for c in cookies:
                    self.tool.session.cookies.set(
                        c["name"],
                        c["value"],
                        domain=c.get("domain", ""),
                        path=c.get("path", "/"),
                    )

                return True
            finally:
                await browser.close()

        return False

    def _apply_vacancies(self) -> None:
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

        do_apply = True
        storage = self.tool.storage
        site_emails = {}

        if self.ai_filter:
            if self.ai_filter == "heavy":
                system_prompt = self._build_filter_system_prompt_heavy(
                    self._analyze_resume_heavy(resume)
                )
            elif self.ai_filter == "light":
                system_prompt = self._build_filter_system_prompt_light(
                    self._analyze_resume_light(resume)
                )
            else:
                raise ValueError(
                    f"Неизвестный режим AI фильтра: {self.ai_filter}"
                )

            logger.debug(
                "AI системный промпт (%s): %s",
                self.ai_filter,
                system_prompt,
            )

            self.vacancy_filter_ai = self.tool.get_vacancy_filter_ai(
                system_prompt
            )

            if self.args.ai_rate_limit:
                self.vacancy_filter_ai.rate_limit = self.args.ai_rate_limit

        for vacancy in self._get_vacancies(resume_id=resume["id"]):
            if (
                getattr(self, "_cancel_event", None)
                and self._cancel_event.is_set()
            ):
                logger.info("Операция отменена пользователем")
                break
            try:
                employer = vacancy.get("employer", {})

                message_placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
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

                if self.args.only_with_tests and not vacancy.get("has_test"):
                    logger.debug(
                        "Пропускаем вакансию без теста: %s",
                        vacancy["alternate_url"],
                    )
                    continue

                if vacancy.get("has_test") and self.args.skip_tests:
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

                    if self.ai_filter == "heavy":
                        is_suitable = self._is_vacancy_suitable_heavy(vacancy)
                    elif self.ai_filter == "light":
                        is_suitable = self._is_vacancy_suitable_light(vacancy)
                    else:
                        raise ValueError(
                            f"Неизвестный режим AI фильтра: {self.ai_filter}"
                        )

                    if not is_suitable:
                        logger.info(
                            "Вакансия отклонена AI фильтром (%s): %s",
                            self.ai_filter,
                            vacancy["alternate_url"],
                        )
                        print(
                            f"🧠 AI ({self.ai_filter}) посчитал неподходящей",
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

                    try:
                        storage.employers.save(employer_profile)
                    except RepositoryError as ex:
                        logger.exception(ex)

                    # Если есть сайт, то ищем на нем емейлы для отправки письма
                    if self.args.send_email and (
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

                if self.force_message or vacancy.get(
                    "response_letter_required"
                ):
                    if self.cover_letter_ai:
                        msg = self.message_prompt + "\n\n"
                        msg += (
                            "Название вакансии: "
                            + message_placeholders["vacancy_name"]
                        )
                        msg += (
                            "Мое резюме: "
                            + message_placeholders["resume_title"]
                        )
                        logger.debug("prompt: %s", msg)
                        letter = self.cover_letter_ai.complete(msg)
                    else:
                        letter = (
                            rand_text(self.cover_letter) % message_placeholders
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
                                err = result.get("error")

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
                                        f"Произошла ошибка при отклике на вакансию с тестом: {vacancy['alternate_url']} - {err}"
                                    )
                    except Exception as ex:
                        logger.error(f"Произошла непредвиденная ошибка: {ex}")
                        continue

                else:
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
                    except CaptchaRequired as ex:
                        logger.warning(f"Требуется капча: {ex.captcha_url}")
                        try:
                            success = asyncio.run(
                                self._solve_captcha_async(ex.captcha_url)
                            )
                            if success:
                                if not self.dry_run:
                                    res = self.api_client.post(
                                        "/negotiations",
                                        params,
                                        delay=random.uniform(1, 3),
                                    )
                                    assert res == {}
                                    applied_count += 1
                                    print(
                                        "📨 Отправили отклик на вакансию после капчи",
                                        vacancy["alternate_url"],
                                    )
                            else:
                                logger.error("Не удалось решить капчу")
                                raise
                        except Exception as e:
                            logger.error(f"Ошибка при решении капчи: {e}")
                            raise

                # Отправка письма на email
                if self.args.send_email:
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
                        mail_subject = (
                            rand_text(
                                self.tool.config.get("apply_mail_subject")
                                or "{Отклик|Резюме} на вакансию %(vacancy_name)s"
                            )
                            % message_placeholders
                        )
                        mail_body = (
                            unescape_string(
                                rand_text(
                                    self.tool.config.get("apply_mail_body")
                                    or "{Здравствуйте|Добрый день}, {прошу рассмотреть|пожалуйста рассмотрите} мое резюме %(resume_url)s на вакансию %(vacancy_name)s."
                                )
                            )
                            % message_placeholders
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
        msg.set_content(body)
        self.tool.smtp.send_message(msg)

    json_decoder = JSONDecoder()

    def _solve_vacancy_test(
        self,
        vacancy_id: str | int,
        resume_hash: str,
        letter: str = "",
    ) -> dict[str, Any]:
        """Загружает тест, ждет паузу и отправляет отклик."""
        response_url = f"https://hh.ru/applicant/vacancy_response?vacancyId={vacancy_id}&startedWithQuestion=false&hhtmFrom=vacancy"

        r = self.tool.session.get(response_url)
        r.raise_for_status()

        form = VacancyResponseFormParser()
        form.feed(r.text)

        payload: dict[str, Any] = form.hidden_payload()
        xsrf_token = payload.get("_xsrf")
        if not xsrf_token:
            raise ValueError("Не найден _xsrf в HTML-форме отклика.")

        payload |= {
            "_xsrf": xsrf_token,
            "vacancy_id": str(vacancy_id),
            "resume_hash": resume_hash,
            "ignore_postponed": "true",
            "incomplete": "false",
            "mark_applicant_visible_in_vacancy_country": "false",
            "country_ids": "[]",
            "lux": "true",
            "withoutTest": "no",
            "letter": letter,
        }

        question = "\n".join(form.questions)
        answered_fields: set[str] = set()

        self._log_test_message("🧩 Найден тест для вакансии: %s", response_url)
        if form.questions:
            self._log_test_message(
                "❓ Найдено вопросов теста: %d", len(form.questions)
            )

        for field_name, solutions in form.choice_groups().items():
            field_question = (
                solutions[0].get("question") or question
                if solutions
                else question
            )
            if field_question:
                self._log_test_message("❓ Вопрос: %s", field_question)

            selected = self._select_test_solution(
                field_name, field_question, solutions
            )
            if not selected:
                continue

            if selected["type"] == "checkbox":
                payload[field_name] = [selected["value"]]
            else:
                payload[field_name] = selected["value"]
            answered_fields.add(field_name)
            answer_label = selected.get("label") or selected.get("value")
            self._log_test_message(
                "✅ Ответ на %s: %s", field_name, answer_label
            )

            if self._is_custom_answer(answer_label):
                custom_field_name = f"{field_name}_text"
                if custom_field_name not in payload:
                    payload[custom_field_name] = (
                        self._answer_test_text_question(field_question)
                    )
                    answered_fields.add(custom_field_name)
                    self._log_test_message(
                        "✅ Свой вариант для %s: %s",
                        custom_field_name,
                        payload[custom_field_name],
                    )

        for textarea in form.textareas:
            field_name = textarea["name"]
            if not field_name or field_name in payload:
                continue
            answer = self._answer_test_text_question(
                textarea.get("question") or question
            )
            payload[field_name] = answer
            answered_fields.add(field_name)
            self._log_test_message(
                "✅ Текстовый ответ на %s: %s", field_name, answer
            )

        for text_input in form.text_inputs():
            field_name = text_input["name"]
            if not field_name or field_name in payload:
                continue
            answer = self._answer_test_text_question(
                text_input.get("question") or question
            )
            payload[field_name] = answer
            answered_fields.add(field_name)
            self._log_test_message(
                "✅ Текстовый ответ на %s: %s", field_name, answer
            )

        for select in form.selects:
            field_name = select["name"]
            if not field_name or field_name in payload:
                continue
            options = [
                option
                for option in select["options"]
                if option["value"] or option["text"]
            ]
            if not options:
                continue
            selected = next(
                (option for option in options if option["selected"]),
                options[len(options) // 2],
            )
            payload[field_name] = selected["value"]
            answered_fields.add(field_name)
            answer_label = selected.get("text") or selected.get("value")
            self._log_test_message(
                "✅ Ответ на %s: %s", field_name, answer_label
            )

        if not answered_fields:
            raise ValueError(
                "Не найдены поля теста в HTML-форме отклика. "
                "HH изменил разметку или вернул не форму теста."
            )

        logger.debug("Поля теста заполнены: %s", sorted(answered_fields))

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

    @staticmethod
    def _log_test_message(message: str, *args: Any) -> None:
        text = message % args if args else message
        print(text)
        logger.info(text)

    def _select_test_solution(
        self,
        field_name: str,
        question: str,
        solutions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not solutions:
            return None

        if getattr(self, "cover_letter_ai", None):
            options = "\n".join(
                f"{idx}: {solution.get('label') or solution.get('value')}"
                for idx, solution in enumerate(solutions, 1)
            )
            user_instruction = self._vacancy_test_ai_instruction()
            prompt = (
                "Ты выбираешь ответ в тесте вакансии.\n"
                "Контекст ниже описывает кандидата и его предпочтения; "
                "это НЕ текст ответа работодателю.\n\n"
                "Контекст кандидата:\n"
                f"{user_instruction}\n\n"
                f"Вопрос: {question}\n"
                f"Поле формы: {field_name}\n"
                f"Варианты:\n{options}\n"
                "Правила выбора:\n"
                "- верни только номер варианта, без пояснений;\n"
                "- если вопрос спрашивает ожидания/пожелания — выбирай "
                "вариант, наиболее выгодный и уверенный для кандидата;\n"
                "- не путай прошлые места работы кандидата с его ожиданиями "
                "от новой работы.\n"
                f"Выбери номер ответа, который лучше всего соответствует "
                f"моим условиям. Пришли только номер."
            )
            ai_answer = self.cover_letter_ai.complete(prompt).strip()
            match = re.search(r"\d+", ai_answer)
            if match:
                selected_index = int(match.group(0)) - 1
                if 0 <= selected_index < len(solutions):
                    return solutions[selected_index]

        yes_solution = next(
            (
                solution
                for solution in solutions
                if self._is_positive_answer(
                    solution.get("label") or solution.get("value") or ""
                )
            ),
            None,
        )
        if yes_solution:
            return yes_solution

        non_custom_solutions = [
            solution
            for solution in solutions
            if not self._is_custom_answer(
                solution.get("label") or solution.get("value") or ""
            )
        ]
        if non_custom_solutions:
            return non_custom_solutions[len(non_custom_solutions) // 2]

        return solutions[len(solutions) // 2]

    def _vacancy_test_ai_instruction(self) -> str:
        return (
            self.tool.config.get("vacancy_test_ai_prompt")
            or "Ты отвечаешь на тесты вакансий от моего имени. "
            "Отвечай честно, не выдумывай факты обо мне и выбирай вариант, "
            "который лучше всего соответствует условиям кандидата."
        )

    @staticmethod
    def _is_positive_answer(text: str) -> bool:
        normalized = re.sub(r"\s+", " ", strip_tags(text)).strip().lower()
        return normalized in {
            "да",
            "yes",
            "готов",
            "готова",
            "согласен",
            "согласна",
            "подходит",
        }

    @staticmethod
    def _is_custom_answer(text: str | None) -> bool:
        normalized = re.sub(r"\s+", " ", strip_tags(text or "")).strip().lower()
        return normalized in {
            "свой вариант",
            "другое",
            "другой вариант",
            "иное",
            "other",
            "other option",
        }

    def _answer_test_text_question(self, question: str) -> str:
        if "://" in question:
            return rand_text(
                "{{Простите|Извините}, но я не перехожу по {внешним|сторонним} ссылкам, так как {опасаюсь взлома|не хочу {быть взломанным|подхватить вирус|чтобы у меня {со|с банковского} счета украли деньги}}.|У меня нет времени на заполнение анкет и гуглодоков}"
            )

        if getattr(self, "cover_letter_ai", None):
            prompt = (
                "Ты отвечаешь на один текстовый вопрос в тесте вакансии.\n"
                "Контекст ниже описывает кандидата и его предпочтения; "
                "это НЕ готовый ответ и НЕ список ожиданий от новой работы.\n\n"
                "Контекст кандидата:\n"
                f"{self._vacancy_test_ai_instruction()}\n\n"
                f"Вопрос: {question}\n"
                "Сформулируй ответ строго на этот вопрос.\n"
                "Требования к ответу:\n"
                "- не сильно длинным, если в вопросе это не указано;\n"
                "- от первого лица;\n"
                "- уверенно и профессионально;\n"
                "Ответ:"
            )
            return self.cover_letter_ai.complete(prompt)

        return self.tool.config.get("vacancy_test_answer") or "Да"

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

    def _get_vacancies(
        self, resume_id: str | None = None
    ) -> Iterator[SearchVacancy]:
        for page in range(self.total_pages):
            logger.debug(f"Загружаем вакансии со страницы: {page + 1}")
            params = self._get_search_params(page)

            if self.search:
                res: PaginatedItems[SearchVacancy] = self.api_client.get(
                    "/vacancies",
                    params,
                )
            else:
                res: PaginatedItems[SearchVacancy] = self.api_client.get(
                    f"/resumes/{resume_id}/similar_vacancies",
                    params,
                )

            logger.debug(f"Количество вакансий: {res['found']}")

            if not res["items"]:
                return

            yield from res["items"]

            if page >= res["pages"] - 1:
                return

    def _is_excluded(self, vacancy: SearchVacancy) -> bool:
        if not self.excluded_filter:
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

        excluded_pat: re.Pattern = re.compile(
            self.excluded_filter, re.IGNORECASE
        )

        if excluded_pat.search(vacancy_summary):
            return True

        # Грузим полный текст вакансии только, если предыдущий фильтр не сработал
        r = self.tool.session.get("https://hh.ru/vacancy/" + vacancy["id"])
        r.raise_for_status()

        description, _ = self.json_decoder.raw_decode(
            re.search(r'"description": (.*)', r.text).group(1)
        )
        description = strip_tags(description)
        logger.debug(description[:2047])
        return bool(excluded_pat.search(description))

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
        self, vacancy: SearchVacancy, reason: str, resume_id: str | None = None
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

import argparse
import logging
import random
import time
from typing import TextIO, Tuple

from ..api import ApiClient, ApiError, BadRequest
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse, VacancyItem
from ..utils import print_err, truncate_string

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list: TextIO
    force_message: bool
    apply_interval: Tuple[float, float]
    page_interval: Tuple[float, float]


class Operation(BaseOperation):
    """Откликнуться на все подходящие вакансии"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--resume-id", help="Идентефикатор резюме")
        parser.add_argument(
            "--message-list",
            help="Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки. В сообщения можно использовать плейсхолдеры типа %%(name)s",
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
            help="Интервал между отправкой откликов в секундах (X, X-Y)",
            default="1-5",
            type=self._parse_interval,
        )
        parser.add_argument(
            "--page-interval",
            help="Интервал между получением следующей страницы рекомендованных вакансий в секундах (X, X-Y)",
            default="1-3",
            type=self._parse_interval,
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
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
            user_agent=args.config["user_agent"],
        )
        if not (
            resume_id := args.resume_id or args.config["default_resume_id"]
        ):
            resumes: ApiListResponse = api.get("/resumes/mine")
            resume_id = resumes["items"][0]["id"]
        if args.message_list:
            application_messages = list(
                filter(None, map(str.strip, args.message_list))
            )
        else:
            application_messages = [
                "Меня заинтересовала ваша вакансия %(name)s",
                "Прошу рассмотреть мою жалкую кандидатуру на вакансию %(name)s",
                "Ваша вакансия %(name)s соответствует моим навыкам и опыту",
                "Хочу присоединиться к вашей успешной команде лидеров рынка в качестве %(name)s",
                "Мое резюме содержит все баззворды, указанные в вашей вакансии %(name)s",
            ]

        apply_min_interval, apply_max_interval = args.apply_interval
        page_min_interval, page_max_interval = args.page_interval

        self._apply_similar(
            api,
            resume_id,
            args.force_message,
            application_messages,
            apply_min_interval,
            apply_max_interval,
            page_min_interval,
            page_max_interval,
        )

    def _get_vacancies(
        self,
        api: ApiClient,
        resume_id: str,
        page_min_interval: float,
        page_max_interval: float,
    ) -> list[VacancyItem]:
        rv = []
        per_page = 100
        for page in range(20):
            res: ApiListResponse = api.get(
                f"/resumes/{resume_id}/similar_vacancies",
                page=page,
                per_page=per_page,
                order_by="relevance",
            )
            rv.extend(res["items"])
            if page >= res["pages"] - 1:
                break

            # Задержка перед получением следующей страницы
            if page > 0:
                interval = random.uniform(page_min_interval, page_max_interval)
                time.sleep(interval)

        return rv

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
    ) -> None:
        item: VacancyItem
        for item in self._get_vacancies(
            api, resume_id, page_min_interval, page_max_interval
        ):
            try:
                if item["has_test"]:
                    print("Пропускаем тест", item["alternate_url"])
                    continue

                relations = item.get("relations", [])

                # Там черезжопно нужно хеш отклика получать чтобы его отменить
                # if "got_response" in relations:
                #     # Тупая пизда ее даже не рассматривала
                #     print(
                #         "Отменяем заявку чтобы отправить ее снова",
                #         item["alternate_url"],
                #     )
                #     api.delete(f"/negotiations/active/{item['id']}")
                # elif relations:
                if relations:
                    print("Пропускаем ответ на заявку", item["alternate_url"])
                    continue

                # Задержка перед отправкой отклика
                interval = random.uniform(
                    apply_min_interval, apply_max_interval
                )
                time.sleep(interval)

                params = {
                    "resume_id": resume_id,
                    "vacancy_id": item["id"],
                    "message": (
                        random.choice(application_messages) % item
                        if force_message or item["response_letter_required"]
                        else ""
                    ),
                }

                res = api.post("/negotiations", params)
                assert res == {}
                print(
                    "📨 Отправили отклик",
                    item["alternate_url"],
                    "(",
                    truncate_string(item["name"]),
                    ")",
                )
            except ApiError as ex:
                print_err("❗ Ошибка:", ex)
                if isinstance(ex, BadRequest) and ex.limit_exceeded:
                    break

        print("📝 Отклики на вакансии разосланы!")

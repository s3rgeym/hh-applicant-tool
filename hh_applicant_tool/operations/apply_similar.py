# Этот модуль можно использовать как образец для других
import argparse
import logging
import random
from typing import TextIO

from ..api import ApiClient, ApiError, BadRequest
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse, VacancyItem
from ..utils import print_err, truncate_string

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str | None
    message_list: TextIO


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
            # Используем id первого резюме
            # TODO: создать 10 резюме и рассылать по 2000 откликов в сутки
            resume_id = resumes["items"][0]["id"]
        if args.message_list:
            application_messages = list(
                filter(None, map(str.strip, args.message_list))
            )
        else:
            application_messages = [
                "Меня заинтересовала Ваша вакансия %(name)s",
                "Прошу рассмотреть мою кандидатуру на вакансию %(name)s",
            ]
        self._apply_similar(
            api, resume_id, args.force_message, application_messages
        )

    def _get_vacancies(
        self, api: ApiClient, resume_id: str
    ) -> list[VacancyItem]:
        rv = []
        # работает ограничение: глубина возвращаемых результатов не может быть больше 2000
        # Номер страницы (считается от 0, по умолчанию - 0)
        per_page = 100
        for page in range(20):
            res: ApiListResponse = api.get(
                f"/resumes/{resume_id}/similar_vacancies",
                page=page,
                per_page=per_page,
                # Мне кажется, что так поисковая выдача можно забиться неадекватами, которые по полгода кого-то ищут
                # Но так откликается на что-то уж совсем нерелевантное
                # order_by="publication_time",
                order_by="relevance",
            )
            rv.extend(res["items"])
            if page >= res["pages"] - 1:
                break
        return rv

    def _apply_similar(
        self,
        api: ApiClient,
        resume_id: str,
        force_message: bool,
        application_messages: list[str],
    ) -> None:
        # Получаем список рекомендованных вакансий и отправляем заявки
        # Проблема тут в том, что вакансии на которые мы отклимкались должны исчезать из поиска, но ОНИ ТАМ ПРИСУТСТВУЮТ. Так же есть вакансии с ебучими тестами, которые всегда вверху. Вроде можно отсортировать по дате, а потом постепенно уменьшать диапазон, но он не точный и округляется до 5 минут, а потому там повторы
        item: VacancyItem
        for item in self._get_vacancies(api, resume_id):
            # В рот я ебал вас и ваши тесты, пидоры
            if item["has_test"]:
                continue
            # Откликаемся на ваканчию
            params = {
                "resume_id": resume_id,
                "vacancy_id": item["id"],
                "message": (
                    random.choice(application_messages) % item
                    if force_message or item["response_letter_required"]
                    else ""
                ),
            }
            try:
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

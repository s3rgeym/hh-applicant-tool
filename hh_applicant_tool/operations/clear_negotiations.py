# Этот модуль можно использовать как образец для других
import argparse
import logging
from datetime import datetime, timedelta, timezone

from ..api import ApiClient, ClientError
from ..contsants import INVALID_ISO8601_FORMAT
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse
from ..utils import truncate_string

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    older_than: int | None
    blacklist_discard: bool


class Operation(BaseOperation):
    """Отменяет старые заявки и скрывает отказы."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--older-than",
            type=int,
            default=30,
            help="Удалить заявки старше опр. кол-ва дней. По умолчанию: %(default)d",
        )
        parser.add_argument(
            "--blacklist-discard",
            help="Если установлен, то заблокирует работодателя в случае отказа, чтобы его вакансии не отображались в возможных",
            type=bool,
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def _get_active_negotiations(self, api: ApiClient) -> list[dict]:
        rv = []
        page = 0
        per_page = 100
        while True:
            r: ApiListResponse = api.get(
                "/negotiations", page=page, per_page=per_page, status="active"
            )
            rv.extend(r["items"])
            page += 1
            if page >= r["pages"]:
                break
        return rv

    def run(self, args: Namespace) -> None:
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
        )
        negotiations = self._get_active_negotiations(api)
        logger.info("Всего активных: %d", len(negotiations))
        for item in negotiations:
            state = item["state"]
            # messaging_status archived
            # decline_allowed False
            # hidden True
            is_discard = state["id"] == "discard"
            if not item["hidden"] and (
                is_discard
                or (
                    state["id"] == "response"
                    and (
                        datetime.utcnow() - timedelta(days=args.older_than)
                    ).replace(tzinfo=timezone.utc)
                    > datetime.strptime(
                        item["updated_at"], INVALID_ISO8601_FORMAT
                    )
                )
            ):
                vacancy = item["vacancy"]
                logger.debug(
                    "Удаляем %s на вакансию %r <%s>",
                    state["name"].lower(),
                    truncate_string(vacancy["name"]),
                    vacancy["alternate_url"],
                )
                res = api.delete(f"/negotiations/active/{item['id']}")
                assert {} == res
                # https://api.hh.ru/openapi/redoc#tag/Skrytye-vakansii/operation/delete-vacancy-from-blacklisted
                if is_discard and args.blacklist_discard:
                    employer = vacancy["employer"]
                    try:
                        api.put(f"/employers/blacklisted/{employer['id']}")
                        logger.debug(
                            "n-listed: %r <%s>",
                            truncate_string(employer["name"]),
                            employer["url"],
                        )
                    except ClientError as ex:
                        logger.warning(ex)

        print("🧹 Чистка заявок завершена!")

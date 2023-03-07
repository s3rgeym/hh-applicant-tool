# Этот модуль можно использовать как образец для других
import argparse
import logging
from datetime import datetime, timedelta, timezone

from ..api import ApiClient
from ..contsants import INVALID_ISO8601_FORMAT
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    older_than: int | None


class Operation(BaseOperation):
    """Очистить зяавки. Удалит заявки с отказами и/либо все заявки старше N дней."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--older-than",
            type=int,
            default=30,
            help="Удалить заявки старше опр. кол-ва дней. По умолчанию: %(default)d",
        )

    def _get_negotiations(self, api: ApiClient) -> list[dict]:
        rv = []
        page = 0
        per_page = 100
        while True:
            r: ApiListResponse = api.get(
                "/negotiations",
                order_by="created_at",
                order="desc",
                page=page,
                per_page=per_page,
            )
            rv.extend(r["items"])
            if len(rv) % per_page:
                break
            page += 1
        return rv

    def run(self, args: Namespace) -> None:
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
        )
        negotiations = self._get_negotiations(api)
        logger.info("Всего заявок и предложений: %d", len(negotiations))
        for item in negotiations:
            state = item["state"]
            # messaging_status archived
            # decline_allowed False
            # hidden True
            do_delete = not item["hidden"] and (
                state["id"] == "discard"
                or (
                    state["id"] == "response"
                    and (
                        datetime.utcnow() - timedelta(days=args.older_than)
                    ).replace(tzinfo=timezone.utc)
                    > datetime.strptime(
                        item["created_at"], INVALID_ISO8601_FORMAT
                    )
                )
            )
            if do_delete:
                logger.debug(
                    "Удаляем %s на вакансию %r: %s",
                    state["name"].lower(),
                    item["vacancy"]["name"][:40],
                    item["vacancy"]["alternate_url"],
                )
                res = api.delete(f"/negotiations/active/{item['id']}")
                assert {} == res

        print("🧹 Чистка заявок завершена!")

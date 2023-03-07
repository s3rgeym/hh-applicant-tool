# Этот модуль можно использовать как образец для других
import argparse
import logging

from prettytable import PrettyTable

from ..api import ApiClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Список резюме"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace) -> None:
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
        )
        resumes: ApiListResponse = api.get("/resumes/mine")
        t = PrettyTable(
            field_names=["ID", "Заголовок", "Статус"], align="l", valign="t"
        )
        t.add_rows(
            [
                (
                    x["id"],
                    x["title"],
                    ["Доступно", "Заблокировано"][x["blocked"]],
                )
                for x in resumes["items"]
            ]
        )
        print(t)

# Этот модуль можно использовать как образец для других
import argparse
import logging

from ..api import ApiClient, ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse
from ..utils import print_err, truncate_string

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Обновить все резюме"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace) -> None:
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
            user_agent=args.config["user_agent"],
        )
        resumes: ApiListResponse = api.get("/resumes/mine")
        for resume in resumes["items"]:
            try:
                res = api.post(f"/resumes/{resume['id']}/publish")
                assert res == {}
                print("✅ Обновлено", truncate_string(resume["title"]))
            except ApiError as ex:
                print_err("❗ Ошибка:", ex)

# Этот модуль можно использовать как образец для других
import argparse
import logging

from ..api import ApiClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..utils import dumps

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выведет текущего пользователя"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace) -> None:
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
            user_agent=args.config["user_agent"],
        )
        result = api.get("/me")
        print(dumps(result))

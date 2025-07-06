# Этот модуль можно использовать как образец для других
import argparse
import json
import logging

from ..api import ApiClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выведет текущего пользователя"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace, api_client: ApiClient, _) -> None:
        result = api_client.get("/me")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

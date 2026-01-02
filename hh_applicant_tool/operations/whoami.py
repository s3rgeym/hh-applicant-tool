# Этот модуль можно использовать как образец для других
import argparse
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
        result = api_client.get("me")
        full_name = " ".join(
            filter(
                None,
                [
                    result.get("last_name"),
                    result.get("first_name"),
                    result.get("middle_name"),
                ],
            )
        )
        counters = result["counters"]
        print(
            f"#{result['id']}",
            full_name or "—",
            f"({result['auth_type']})",
            f"[ Резюме: {counters['resumes_count']} | Просмотры: +{counters['new_resume_views']} | Непрочитанных: +{counters['unread_negotiations']} ]",
        )

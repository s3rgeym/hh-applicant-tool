# Этот модуль можно использовать как образец для других
import argparse
import logging

from ..api import ApiError, ApiClient, OAuthClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..utils import print_err

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Получает новый access_token."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, api: ApiClient, args: Namespace) -> None:
        try:
            oauth: OAuthClient = api.oauth_client
            token = oauth.refresh_access(api.refresh_token)
            api.handle_access_token(token)
            print("✅ Токен обновлен!")
        except ApiError as ex:
            print_err("❗ Ошибка:", ex)
            return 1

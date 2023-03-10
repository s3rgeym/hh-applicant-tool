# Этот модуль можно использовать как образец для других
import argparse
import logging

from ..api import ApiError, OAuthClient
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

    def run(self, args: Namespace) -> None:
        if (
            not args.config["token"]
            or not args.config["token"]["refresh_token"]
        ):
            print_err("❗ Необходим refresh_token!")
            return 1
        try:
            oauth = OAuthClient(
                user_agent=(
                    args.config["oauth_user_agent"]
                    or args.config["user_agent"]
                ),
            )
            token = oauth.refresh_access(args.config["token"]["refresh_token"])
            args.config.save(token=token)
            print("✅ Токен обновлен!")
        except ApiError as ex:
            print_err("❗ Ошибка:", ex)
            return 1

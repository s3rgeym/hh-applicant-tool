from __future__ import annotations

import argparse
import logging

from ..tool import BaseNamespace, BaseOperation

if __name__ == "__hh_applicant_tool.operations.set_client":  # TYPE_CHECKING guard
    from ..tool import HHApplicantTool


logger = logging.getLogger(__name__.split(".")[0])


class Namespace(BaseNamespace):
    client: str


class Operation(BaseOperation):
    """
    Переключить клиент для эмуляции: android или ios.

    При переключении токены (token.json) очищаются, так как OAuth-токены
    привязаны к client_id. После переключения потребуется повторная авторизация.

    Примеры:
        hh-applicant-tool set-client ios
        hh-applicant-tool set-client android
    """

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        client_arg = parser.add_argument(
            "client",
            choices=["android", "ios"],
            help="Клиент для эмуляции",
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> int | None:
        config = tool.config
        config.setdefault("general", {})

        old_client = config.get("general", {}).get("client", "android")
        new_client = args.client

        if old_client == new_client:
            print(f"Уже используется клиент: {new_client}")
            return 0

        # Очищаем токены при смене клиента
        if tool.token_config.exists():
            print("Очистка токенов (привязаны к client_id)...")
            tool.token_config.unlink()

        # Сохраняем новый клиент
        config["general"]["client"] = new_client
        config.save()

        print(f"Клиент переключен: {old_client} -> {new_client}")
        print("Токены очищены. Выполните авторизацию заново:")
        print(f"   hh-applicant-tool authorize <телефон|email>")

        return 0

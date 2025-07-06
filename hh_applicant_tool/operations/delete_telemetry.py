# Этот модуль можно использовать как образец для других
import argparse
import logging

from ..telemetry_client import TelemetryClient, TelemetryError

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..utils import print_err

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Удалить всю телеметрию, сохраненную на сервере."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, a, b, telemetry_client: TelemetryClient) -> None:
        try:
            telemetry_client.send_telemetry("/delete")
            print("✅ Вся телеметрия, сохраненная на сервере, была успешно удалена!")
        except TelemetryError as ex:
            print_err("❗ Ошибка:", ex)
            return 1

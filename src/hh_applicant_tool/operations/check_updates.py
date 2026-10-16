from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

import requests

from ..tool import BaseNamespace, BaseOperation
from ..utils.package import get_package_version, parse_version

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger("hh-applicant-tool")

PYPI_URL = "https://pypi.org/pypi/hh-applicant-tool/json"


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Проверяет, доступны ли обновления утилиты"""

    __aliases__: list[str] = []

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool, args: BaseNamespace) -> None:
        response = requests.get(PYPI_URL, timeout=15)
        response.raise_for_status()
        pypi_ver = response.json()["info"]["version"]

        local_str = get_package_version()
        remote_ver = parse_version(pypi_ver)
        local_ver = parse_version(local_str)

        if local_ver < remote_ver:
            print(f"🚀 Доступна новая версия: {pypi_ver} (у вас {local_str})")
            print("📦 Обновить: pip install -U hh-applicant-tool")
        elif local_ver > remote_ver:
            print(
                f"🧪 Локальная версия {local_str} новее, чем на PyPI ({pypi_ver}). "
                "Похоже, вы используете dev-сборку."
            )
        else:
            print(f"✅ У вас последняя версия: {local_str}")

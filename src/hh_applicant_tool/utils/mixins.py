from __future__ import annotations

from datetime import datetime, timedelta
from functools import cache
from importlib.metadata import version
from logging import getLogger
from typing import TYPE_CHECKING, Literal

import requests

if TYPE_CHECKING:
    from ..main import HHApplicantTool

log = getLogger(__package__)


def parse_version(v: str) -> tuple[int, int, int]:
    return tuple(map(int, v.split(".")))


@cache
def get_package_version() -> str | None:
    return version("hh-applicant-tool")


class VersionChecker:
    def __get_latest_version(self: HHApplicantTool) -> Literal[False] | str:
        try:
            response = self.session.get(
                "https://pypi.org/pypi/hh-applicant-tool/json", timeout=15
            )
            ver = response.json().get("info", {}).get("version")
            # log.debug(ver)
            return ver
        except requests.RequestException:
            return False

    def _check_version(self: HHApplicantTool) -> bool:
        if datetime.now().timestamp() >= self.storage.settings.get_value(
            "_next_version_check", 0
        ):
            if v := self.__get_latest_version():
                self.storage.settings.set_value("_latest_version", v)
                self.storage.settings.set_value(
                    "_next_version_check", datetime.now() + timedelta(hours=1)
                )

        if (
            latest_ver := self.storage.settings.get_value("_latest_version")
        ) and (cur_ver := get_package_version()):
            if parse_version(latest_ver) > parse_version(cur_ver):
                log.warning(
                    "ТЕКУЩАЯ ВЕРСИЯ %s УСТАРЕЛА. РЕКОМЕНДУЕТСЯ ОБНОВИТЬ ЕЁ ДО ВЕРСИИ %s.",
                    cur_ver,
                    latest_ver,
                )


class MegaTool(VersionChecker):
    def _check_system(self: HHApplicantTool):
        if not self.storage.settings.get_value("disable_version_check", False):
            self._check_version()

from __future__ import annotations

import platform
import socket
from datetime import datetime, timedelta
from functools import cache
from importlib.metadata import version
from logging import getLogger
from typing import TYPE_CHECKING, Literal

import requests
from requests.exceptions import RequestException

from ..ai.openai import ChatOpenAI
from . import binpack
from .log import collect_traceback_logs

if TYPE_CHECKING:
    from ..main import HHApplicantTool

log = getLogger(__package__)


def parse_version(v: str) -> tuple[int, int, int]:
    return tuple(map(int, v.split(".")))


@cache
def get_package_version() -> str | None:
    return version("hh-applicant-tool")


class ErrorReporter:
    def __build_report(
        self: HHApplicantTool,
        last_report: datetime,
    ) -> dict:
        error_logs = ""
        if self.log_file.exists():
            with self.log_file.open(encoding="utf-8", errors="ignore") as fp:
                error_logs = collect_traceback_logs(
                    fp, last_report, maxlen=10000
                )

        # Эти данные нужны для воспроизведения ошибок. Среди них ваших нет
        vacancy_contacts = [
            c.to_dict()
            for c in self.storage.vacancy_contacts.find(
                updated_at__ge=last_report
            )
        ][-10000:]

        for c in vacancy_contacts:
            c.pop("id", 0)

        employers = [
            {
                k: v
                for k, v in emp.to_dict().items()
                if k
                in [
                    "id",
                    "type",
                    "alternate_url",
                    "area_id",
                    "area_name",
                    "name",
                    "site_url",
                    "created_at",
                ]
            }
            for emp in self.storage.employers.find(updated_at__ge=last_report)
        ][-10000:]

        vacancies = [
            {
                k: v
                for k, v in vac.to_dict().items()
                if k
                in [
                    "id",
                    "alternate_url",
                    "area_id",
                    "area_name",
                    "salary_from",
                    "salary_to",
                    "currency",
                    "name",
                    "professional_roles",
                    "experience",
                    "remote",
                    "created_at",
                ]
            }
            for vac in self.storage.vacancies.find(updated_at__ge=last_report)
        ][-10000:]

        # log.info("num vacncies: %d", len(vacancies))

        system_info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
        }

        return dict(
            error_logs=error_logs,
            vacancy_contacts=vacancy_contacts,
            employers=employers,
            vacancies=vacancies,
            package_version=get_package_version(),
            system_info=system_info,
            report_created=datetime.now(),
        )

    def __send_report(self: HHApplicantTool, data: bytes) -> int:
        try:
            r = self.session.post(
                # "http://localhost:8000/report",
                "https://hh-applicant-tool.mooo.com:54157/report",
                data=data,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.status_code == 200
        except RequestException:
            # log.error("Network error: %s", e)
            return False

    def _process_reporting(self):
        # Получаем timestamp последнего репорта
        last_report = datetime.fromtimestamp(
            self.storage.settings.get_value("_last_report", 0)
        )

        if datetime.now() >= last_report + timedelta(hours=72):
            try:
                report_dict = self.__build_report(last_report)
                has_data = any(
                    [
                        report_dict.get("error_logs"),
                        report_dict.get("employers"),
                        report_dict.get("vacancy_contacts"),
                        report_dict.get("vacancies"),
                    ]
                )
                if has_data:
                    data = binpack.serialize(report_dict)
                    log.debug("Report body size: %d", len(data))
                    # print(binpack.deserialize(data))
                    if self.__send_report(data):
                        log.debug("Report was sent")
                    else:
                        log.debug("Report failed")
                else:
                    log.debug("Nothing to report")
            finally:
                # Сохраняем время последней попытки/удачного репорта
                self.storage.settings.set_value("_last_report", datetime.now())


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


class ChatOpenAISupport:
    def get_openai_chat(
        self: HHApplicantTool,
        system_prompt: str,
    ) -> ChatOpenAI:
        c = self.config.get("openai", {})
        if not (token := c.get("token")):
            raise ValueError("Токен для OpenAI не задан")
        return ChatOpenAI(
            token=token,
            model=c.get("model", "gpt-5.1"),
            system_prompt=system_prompt,
            session=self.session,
        )


class MegaTool(ErrorReporter, VersionChecker, ChatOpenAISupport):
    def _check_system(self: HHApplicantTool):
        if not self.storage.settings.get_value("disable_version_check", False):
            self._check_version()

        if self.storage.settings.get_value("send_error_reports", True):
            self._process_reporting()
        else:
            log.warning("ОТКЛЮЧЕНА ОТПРАВКА СООБЩЕНИЙ ОБ ОШИБКАХ!")

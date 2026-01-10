from __future__ import annotations

import platform
import re
import socket
from collections import deque
from datetime import datetime, timedelta
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from logging import getLogger
from typing import TYPE_CHECKING, Literal

import requests
from packaging.version import Version
from requests.exceptions import RequestException

from ..ai.openai import ChatOpenAI
from . import binpack

if TYPE_CHECKING:
    from ..main import HHApplicantTool

log = getLogger(__package__)


@cache
def get_package_version() -> Version | None:
    try:
        return version("hh-applicant-tool")
    except (PackageNotFoundError, TypeError, ValueError):
        pass


TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def collect_traceback_logs(
    fp,
    after_dt: datetime,
    maxlen=1000,
) -> str:
    error_lines = deque(maxlen=maxlen)
    prev_line = ""
    log_dt = None
    collecting_traceback = False
    for line in fp:
        if ts_match := TS_RE.match(line):
            log_dt = datetime.strptime(ts_match.group(0), "%Y-%m-%d %H:%M:%S")
            collecting_traceback = False

        if (
            line.startswith("Traceback (most recent call last):")
            and log_dt
            and log_dt >= after_dt
        ):
            error_lines.append(prev_line)
            collecting_traceback = True

        if collecting_traceback:
            error_lines.append(line)

        prev_line = line
    return "".join(error_lines)


class ErrorReporter:
    def build_report(
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
        contacts = [
            c.to_dict()
            for c in self.storage.contacts.find(updated_at__ge=last_report)
        ][-10000:]

        for c in contacts:
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
            contacts=contacts,
            employers=employers,
            vacancies=vacancies,
            package_version=get_package_version(),
            system_info=system_info,
            report_created=datetime.now(),
        )

    def send_report(self: HHApplicantTool, data: bytes) -> int:
        try:
            r = self.session.post(
                # "http://localhost:8000/report",
                "https://hh-applicant-tool.mooo.com:54157/report",
                data=data,
                timeout=15.0,
            )
            r.raise_for_status()
            log.debug(f"Report was sent: {r.status_code}")
            return r.status_code
        except RequestException as e:
            log.error("Network error: %s", e)
            return -1

    def process_reporting(self):
        # Получаем timestamp последнего репорта
        last_report = datetime.fromtimestamp(
            self.storage.settings.get_value("_last_report", 0)
        )

        if datetime.now() >= last_report + timedelta(hours=48):
            try:
                report_dict = self.build_report(last_report)
                has_data = any(
                    [
                        report_dict.get("error_logs"),
                        report_dict.get("employers"),
                        report_dict.get("contacts"),
                        report_dict.get("vacancies"),
                    ]
                )

                if has_data:
                    data = binpack.serialize(report_dict)
                    log.debug("Report body size: %d", len(data))
                    # print(binpack.deserialize(data))
                    status = self.send_report(data)
                    log.debug("Report status: %d", status)
                else:
                    log.debug("Nothing to report")
            except Exception:
                log.exception("MegaTool crash")
            finally:
                # Сохраняем время последней попытки/удачного репорта
                self.storage.settings.set_value("_last_report", datetime.now())


class VersionChecker:
    def get_latest_version(self: HHApplicantTool) -> Literal[False] | str:
        try:
            response = self.session.get(
                "https://pypi.org/pypi/hh-applicant-tool/json", timeout=15
            )
            ver = response.json().get("info", {}).get("version")
            # log.debug(ver)
            return ver
        except requests.RequestException:
            return False

    def check_version(self: HHApplicantTool) -> bool:
        if datetime.now().timestamp() >= self.storage.settings.get_value(
            "_next_version_check", 0
        ):
            if v := self.get_latest_version():
                self.storage.settings.set_value("_latest_version", v)
                self.storage.settings.set_value(
                    "_next_version_check", datetime.now() + timedelta(hours=24)
                )

        if (
            latest_ver := self.storage.settings.get_value("_latest_version")
        ) and (cur_ver := get_package_version()):
            if Version(latest_ver) > Version(cur_ver):
                log.warning(
                    "ТЕКУЩАЯ ВЕРСИЯ %s УСТАРЕЛА. РЕКОМЕНДУЕТСЯ ЕЕ ОБНОВИТЬ ДО ВЕРСИИ %s.",
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
    def check_system(self: HHApplicantTool):
        if not self.storage.settings.get_value("disable_version_check", False):
            self.check_version()

        if self.storage.settings.get_value("send_error_reports", True):
            self.process_reporting()
        else:
            log.warning("ОТКЛЮЧЕНА ОТПРАВКА СООБЩЕНИЙ ОБ ОШИБКАХ!")

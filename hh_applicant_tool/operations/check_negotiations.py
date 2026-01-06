from __future__ import annotations

import argparse
import csv
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from ..constants import INVALID_ISO8601_FORMAT
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..types import ApiListResponse
from ..utils import parse_interval

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    older_than: int
    blacklist_discard: bool
    all: bool
    dry_run: bool
    cleanup: bool
    report: Optional[argparse.FileType]
    delay_interval: tuple[float, float]


class Operation(BaseOperation):
    """Синхронизирует отклики. Детально обрабатывает и заносит в отчет только ПРИГЛАШЕНИЯ."""

    __aliases__ = ["negotiations"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-t",
            "--older-than",
            type=int,
            default=30,
            help="Порог старости отклика в днях. По умолчанию: %(default)d",
        )
        parser.add_argument(
            "-a",
            "--all",
            action=argparse.BooleanOptionalAction,
            help="Режим 'Терминатор': удалять всё, включая приглашения",
        )
        parser.add_argument(
            "-b",
            "--blacklist-discard",
            help="Сжигать мосты: кидать работодателя в ЧС при отказе",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "-x",
            "--cleanup",
            help="Разрешить удаление откликов в аккаунте HH",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "-r",
            "--report",
            type=argparse.FileType("w", encoding="utf-8"),
            help="Сохранить приглашения в csv-файл",
        )
        parser.add_argument(
            "-d",
            "--delay-interval",
            type=parse_interval,
            default="1-3",
            help="Разброс пауз между запросами (сек), например: 1.5-4",
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            help="Холостой ход: посмотреть, что произойдет, ничего не удаляя",
            action=argparse.BooleanOptionalAction,
        )

    @property
    def api_client(self):
        return self.applicant_tool.api_client

    def run(self, applicant_tool: HHApplicantTool) -> None:
        self.applicant_tool = applicant_tool
        args = applicant_tool.args

        page = 0
        total_found = 0
        csv_writer = None

        # 1. Сразу готовим CSV, чтобы писать в него "на лету"
        if args.report:
            fieldnames = [
                "url",
                "name",
                "employer",
                "salary_from",
                "salary_to",
                "currency",
                "contact_name",
                "contact_email",
                "contact_phones",
                "updated_at",
            ]
            csv_writer = csv.DictWriter(args.report, fieldnames=fieldnames)
            csv_writer.writeheader()
            args.report.flush()

        while True:
            r: ApiListResponse = self.api_client.get(
                "/negotiations",
                page=page,
                per_page=100,
                delay=random.uniform(*args.delay_interval),
            )
            items = r["items"]
            if not items:
                break

            total_found += len(items)

            for item in items:
                resume = item["resume"]
                state = item["state"]
                state_id = state["id"]
                vacancy = item["vacancy"]
                vacancy_id = vacancy["id"]

                # Синхронизация статуса в локальной БД
                self.applicant_tool.database.execute(
                    "UPDATE negotiations SET status = ?"
                    "  WHERE vacancy_id = ? AND resume_id = ?",
                    (state_id, vacancy_id, resume["id"]),
                )
                self.applicant_tool.database.commit()

                # ОБРАБОТКА ПРИГЛАШЕНИЯ
                if state_id in ["invitation", "interview"]:
                    # Получаем полные данные вакансии (с контактами)
                    full_vacancy = self.api_client.get(
                        f"/vacancies/{vacancy_id}",
                        delay=random.uniform(*args.delay_interval),
                    )
                    self.applicant_tool.save_vacancy(full_vacancy)
                    salary = full_vacancy.get("salary") or {}
                    contacts = full_vacancy.get("contacts") or {}
                    # Собираем телефоны через запятую
                    phones_str = ", ".join(
                        p["formatted"]
                        for p in contacts.get("phones", [])
                        if p.get("number")
                    )

                    if csv_writer:
                        csv_writer.writerow(
                            {
                                "url": full_vacancy["alternate_url"],
                                "name": full_vacancy.get("name"),
                                "employer": full_vacancy.get("employer", {}).get(
                                    "name"
                                ),
                                "salary_from": salary.get("from"),
                                "salary_to": salary.get("to"),
                                "currency": salary.get("currency"),
                                "contact_name": contacts.get("name"),
                                "contact_email": contacts.get("email"),
                                "contact_phones": phones_str,
                                "updated_at": item.get("updated_at"),
                            }
                        )
                        args.report.flush()  # Данные пишутся сразу, не ждем конца работы
                    else:
                        print(state["name"], full_vacancy["alternate_url"])
                        print("Название вакансии:", full_vacancy["name"])

                        print(
                            "Организация:",
                            full_vacancy.get("employer", {}).get("name", "Неизвестен"),
                        )

                        print(
                            "Зарплата от",
                            salary.get("from") or "—",
                            "до",
                            salary.get("to") or "—",
                            salary.get("currency") or "—",
                        )

                        if email := contacts.get("email"):
                            print("Email:", email)

                        if phones_str:
                            print("Телефон:", phones_str)

                        print()

                # ЧИСТКА (если включен флаг -x)
                if args.cleanup:
                    is_discard = state_id == "discard"
                    updated_at = datetime.strptime(
                        item["updated_at"], INVALID_ISO8601_FORMAT
                    ).replace(tzinfo=timezone.utc)
                    is_old = (
                        datetime.now(timezone.utc) - timedelta(days=args.older_than)
                    ) > updated_at

                    if not item["hidden"] and (
                        args.all or is_discard or (state_id == "response" and is_old)
                    ):
                        if not args.dry_run:
                            self.api_client.delete(
                                f"/negotiations/active/{item['id']}",
                                with_decline_message=item.get("decline_allowed", False),
                                delay=random.uniform(*args.delay_interval),
                            )
                        print(f"❌ Удален отклик: {vacancy['name']}")

                        if is_discard and args.blacklist_discard:
                            emp = vacancy.get("employer")
                            if emp and emp.get("id") and not args.dry_run:
                                self.api_client.put(
                                    f"/employers/blacklisted/{emp['id']}",
                                    delay=random.uniform(*args.delay_interval),
                                )
                                print(f"🚫 Заблокирован: {emp['name']}")

            page += 1
            if page >= r["pages"]:
                break

        print(f"✅ Проверка завершена. Всего откликов: {total_found}")

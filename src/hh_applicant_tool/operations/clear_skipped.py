from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    reason: str | None
    dry_run: bool


class Operation(BaseOperation):

    __aliases__ = ["clear-skipped-vacancies"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--reason",
            help="Очистить только вакансии с указанной причиной (ai_rejected, excluded_filter, blocked)",
            type=str,
            default=None,
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            action="store_true",
            help="Только показать количество записей без удаления",
        )

    def run(self, tool: HHApplicantTool) -> None:
        args = tool.args
        repo = tool.storage.skipped_vacancies

        if args.reason:
            count = sum(1 for _ in repo.find(reason=args.reason))
            if args.dry_run:
                print(f"📋 Найдено {count} записей с причиной '{args.reason}'")
            else:
                if count > 0:
                    for item in repo.find(reason=args.reason):
                        repo.delete(item.id, commit=False)
                    repo.commit()
                    print(f"✂️  Удалено {count} записей с причиной '{args.reason}'")
                else:
                    print(f"❌ Нет записей с причиной '{args.reason}'")
        else:
            total = repo.count_total()
            if args.dry_run:
                print(f"📋 Всего записей в базе: {total}")
            else:
                if total > 0:
                    repo.clear()
                    print(f"✂️  Очищено {total} записей из базы пропущенных вакансий")
                else:
                    print("📋 База пропущенных вакансий уже пуста")

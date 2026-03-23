from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation
from ..operations.list_profiles import _find_local_profiles
from ..utils.ui import console, err, ok, section

if TYPE_CHECKING:
    from ..main import HHApplicantTool


class Namespace(BaseNamespace):
    command: list[str]
    profiles: list[str]
    all: bool


class Operation(BaseOperation):
    """Запустить команду для нескольких профилей последовательно"""

    __aliases__: list[str] = ["foreach"]
    __category__: str = "Утилиты"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "command",
            nargs=argparse.REMAINDER,
            help="Команда и её аргументы (например: apply-vacancies --search python)",
        )
        parser.add_argument(
            "-p",
            "--profiles",
            nargs="+",
            metavar="PROFILE",
            help="Список профилей (по умолчанию — все с активным токеном)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Использовать все профили, включая без токена",
        )

    def run(self, tool: HHApplicantTool) -> int | None:
        args = tool.args

        if not args.command:
            print("Укажите команду. Пример:")
            print("  hh-applicant-tool run-all apply-vacancies --search python")
            return 1

        from ..main import DEFAULT_CONFIG_DIR

        base_dir = Path(DEFAULT_CONFIG_DIR)
        local_profiles = _find_local_profiles(base_dir)

        if not local_profiles:
            print("Нет локальных профилей. Сначала авторизуйтесь:")
            print("  hh-applicant-tool authorize")
            return 1

        # Выбираем профили
        if args.profiles:
            selected = [
                (name, info)
                for name, info in local_profiles
                if name in args.profiles
            ]
            missing = set(args.profiles) - {n for n, _ in selected}
            if missing:
                print(f"Профили не найдены: {', '.join(missing)}")
                return 1
        elif args.all:
            selected = local_profiles
        else:
            # Только с активным токеном
            selected = [
                (name, info)
                for name, info in local_profiles
                if info["has_token"]
            ]
            if not selected:
                print(
                    "Нет профилей с активным токеном. "
                    "Используйте --all чтобы запустить для всех."
                )
                return 1

        cmd_str = " ".join(args.command)
        console.print(
            f"\nЗапускаю [bold]{cmd_str}[/] "
            f"для [hh.label]{len(selected)}[/] профил(ей)\n"
        )

        exit_codes: list[tuple[str, int]] = []
        exe = sys.argv[0]

        for name, _info in selected:
            section(f"Профиль: {name}")
            cmd = [exe, "--profile-id", name, *args.command]
            result = subprocess.run(cmd)
            exit_codes.append((name, result.returncode))
            console.print()

        section("Итого")
        n_ok = sum(1 for _, code in exit_codes if code == 0)
        n_fail = len(exit_codes) - n_ok
        for name, code in exit_codes:
            if code == 0:
                ok(f"{name}")
            else:
                err(f"{name}  (код {code})")
        console.print(
            f"\n[hh.ok]Успешно: {n_ok}[/]  "
            f"[hh.err]Ошибок: {n_fail}[/]\n"
        )

        return 0 if n_fail == 0 else 1

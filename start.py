#!/usr/bin/env python3
# Тут очень много странного/лишнего. Необходима помощь в рефакторинге. 
"""
Лаунчер hh-applicant-tool.

Пользователь кликает на этот файл — и всё работает.
Скрипт сам установит зависимости, проведёт авторизацию при первом
запуске и предложит выбор: UI или CLI.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent

# Максимальная версия Python, поддерживаемая pywebview/pythonnet на Windows
MAX_PYTHON = (3, 13)


# ──────────────────────────────────────────────
# Автоперезапуск на совместимой версии Python
# ──────────────────────────────────────────────

def _find_compatible_python() -> str | None:
    """Найти py -3.XX на Windows через py launcher."""
    if platform.system() != "Windows":
        return None
    for minor in range(MAX_PYTHON[1], 10, -1):  # 3.13, 3.12, 3.11
        tag = f"-3.{minor}"
        try:
            r = subprocess.run(
                ["py", tag, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return tag
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


def _install_compatible_python() -> bool:
    """Установить совместимый Python через winget (Windows)."""
    if platform.system() != "Windows":
        return False
    try:
        subprocess.run(
            ["winget", "--version"],
            capture_output=True, timeout=5,
        ).check_returncode()
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False

    pkg = f"Python.Python.3.{MAX_PYTHON[1]}"
    print(f"   Устанавливаю Python 3.{MAX_PYTHON[1]} через winget...")
    print(f"   (winget install {pkg})\n")
    code = subprocess.run(
        ["winget", "install", pkg, "--accept-source-agreements", "--accept-package-agreements"],
    ).returncode
    return code == 0


def _relaunch(tag: str) -> None:
    """Перезапустить start.py через py launcher с указанным тегом."""
    result = subprocess.run(
        ["py", tag, str(REPO_DIR / "start.py")] + sys.argv[1:],
    )
    sys.exit(result.returncode)


def _maybe_relaunch() -> None:
    """Если Python слишком новый для pywebview — найти или установить совместимый.

    Порядок:
    1. Текущий Python подходит → ничего не делаем
    2. Есть другой совместимый Python → перезапуск на нём
    3. Нет совместимого → устанавливаем через winget → перезапуск
    4. Нет winget → предупреждаем, продолжаем без UI (CLI работает)
    """
    if sys.version_info[:2] <= MAX_PYTHON:
        return
    print(
        f"\n⚠  Python {sys.version_info[0]}.{sys.version_info[1]} слишком новый "
        f"для графического интерфейса (нужен ≤ 3.{MAX_PYTHON[1]})."
    )

    # Шаг 2: уже установлен?
    tag = _find_compatible_python()
    if tag:
        print(f"   Найден Python {tag} — перезапускаю...\n")
        _relaunch(tag)

    # Шаг 3: установить
    if _install_compatible_python():
        tag = _find_compatible_python()
        if tag:
            print("\n   Python установлен. Перезапускаю...\n")
            _relaunch(tag)

    # Шаг 4: ничего не помогло — CLI всё равно работает
    print("   Не удалось установить совместимый Python.")
    print("   Графический интерфейс недоступен, но CLI работает.\n")


# ──────────────────────────────────────────────
# Путь к config.json (повторяет логику utils/config.py + constants.py)
# ──────────────────────────────────────────────

def _config_base() -> Path:
    match platform.system():
        case "Windows":
            return Path(
                os.environ.get(
                    "APPDATA",
                    Path.home() / "AppData" / "Roaming",
                )
            )
        case "Darwin":
            return Path.home() / "Library" / "Application Support"
        case _:
            return Path(
                os.environ.get(
                    "XDG_CONFIG_HOME",
                    Path.home() / ".config",
                )
            )


def get_config_json() -> Path:
    """Путь до config.json профиля по умолчанию."""
    profile = os.environ.get("HH_PROFILE_ID", ".")
    return _config_base() / "hh-applicant-tool" / profile / "config.json"


def has_token() -> bool:
    """True если пользователь уже авторизован (токен сохранён)."""
    cfg = get_config_json()
    if not cfg.exists():
        return False
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return bool(data.get("token"))
    except Exception:
        return False


# ──────────────────────────────────────────────
# Автоустановка зависимостей
# ──────────────────────────────────────────────

def _is_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _pip_install(extras: str = "") -> int:
    """Запуск pip install. extras — напр. '[ui]' или ''."""
    target = f"{REPO_DIR}{extras}" if extras else str(REPO_DIR)
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", target, "--quiet"],
    ).returncode


def ensure_installed() -> None:
    """Устанавливает пакет с зависимостями если ещё не установлен.

    Стратегия:
    1. Пробуем поставить с UI (pywebview)
    2. Если не удалось — ставим без UI (CLI всегда работает)
    3. Если и это не удалось — выдаём инструкцию
    """
    if _is_installed("hh_applicant_tool") and _is_installed("webview"):
        return

    if not _is_installed("hh_applicant_tool"):
        print("\nПервый запуск — устанавливаю зависимости...")
        print("Это может занять 1-2 минуты.\n")
    elif not _is_installed("webview"):
        print("\nУстанавливаю pywebview для графического интерфейса...\n")

    # Попытка 1: с UI
    code = _pip_install("[ui]")

    if code != 0:
        # Попытка 2: без UI (CLI работает всегда)
        print("\n⚠  Не удалось установить графический интерфейс.")
        print("   Устанавливаю базовый пакет (только CLI)...\n")
        code = _pip_install()

        if code != 0:
            print("\nОшибка при установке зависимостей.")
            print("Попробуйте вручную:")
            print(f"  cd {REPO_DIR}")
            print(f"  {sys.executable} -m pip install -e .\n")
            _pause_and_exit(1)

    # Обновляем кэш importlib после установки
    importlib.invalidate_caches()

    if not _is_installed("hh_applicant_tool"):
        print("\nОшибка: пакет не найден после установки.")
        print("Возможно, нужен перезапуск скрипта.\n")
        _pause_and_exit(1)

    # Playwright нужен для авторизации — ставим отдельно
    if not _is_installed("playwright"):
        print("Устанавливаю Playwright для авторизации...\n")
        code = subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright", "--quiet"],
        ).returncode
        if code != 0:
            print("⚠  Не удалось установить Playwright. Авторизация может не работать.\n")
        else:
            # Скачиваем Chromium (idempotent — пропустит если уже есть)
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
            )
        importlib.invalidate_caches()

    print("Зависимости установлены!\n")


# ──────────────────────────────────────────────
# Запуск команд
# ──────────────────────────────────────────────

def run_tool(*args: str) -> int:
    """Запускает hh-applicant-tool <args>."""
    cmd = [sys.executable, "-m", "hh_applicant_tool", *args]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(cmd, env=env).returncode


def run_ui() -> int:
    """Запускает UI напрямую (без subprocess).

    pywebview на Windows не создаёт окно из вложенного subprocess,
    поэтому UI запускаем через прямой import в текущем процессе.
    """
    try:
        from hh_applicant_tool.main import main as hh_main

        return hh_main(["ui"]) or 0
    except Exception as e:
        print(f"\nОшибка UI: {e}\n")
        return 1


# ──────────────────────────────────────────────
# Авторизация (через существующую операцию authorize)
# ──────────────────────────────────────────────

def run_authorize() -> int:
    """Запуск авторизации напрямую через import (как run_ui).

    Вызываем существующую операцию authorize через main,
    без subprocess — чтобы избежать проблем с encoding на Windows.
    """
    try:
        from hh_applicant_tool.main import main as hh_main

        return hh_main(["authorize", "--no-headless", "--manual"]) or 0
    except Exception as e:
        print(f"\nОшибка авторизации: {e}\n")
        return 1


# ──────────────────────────────────────────────
# Меню CLI
# ──────────────────────────────────────────────

CLI_COMMANDS = [
    ("apply-vacancies", "Откликнуться на подходящие вакансии"),
    ("authorize", "Авторизоваться на hh.ru"),
    ("list-resumes", "Показать список резюме"),
    ("update-resumes", "Обновить резюме (поднять в поиске)"),
    ("whoami", "Показать информацию о текущем пользователе"),
]


def cli_menu() -> None:
    print("\nДоступные команды:\n")
    for i, (cmd, desc) in enumerate(CLI_COMMANDS, 1):
        print(f"  {i}. {cmd} — {desc}")
    print("\n  0. Назад\n")

    print("Выберите команду: ", end="", flush=True)
    choice = _getch().strip()

    if choice == "0" or choice == "":
        return

    if choice.isdigit() and 1 <= int(choice) <= len(CLI_COMMANDS):
        cmd = CLI_COMMANDS[int(choice) - 1][0]
    else:
        cmd = choice

    extra = input(
        f"Аргументы для {cmd} (Enter — без аргументов): "
    ).strip()
    args = [cmd] + shlex.split(extra) if extra else [cmd]
    print()
    run_tool(*args)
    print()
    input("Нажмите Enter для возврата в меню...")


# ──────────────────────────────────────────────
# Главное меню
# ──────────────────────────────────────────────

def _getch() -> str:
    """Читает один символ без ожидания Enter. Fallback на input() если не TTY."""
    if not sys.stdin.isatty():
        return input().strip()
    if platform.system() == "Windows":
        try:
            import msvcrt
            ch = msvcrt.getwch()
            print(ch)
            return ch
        except Exception:
            return input().strip()
    else:
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print(ch)
            return ch
        except Exception:
            return input().strip()


def main_menu() -> None:
    while True:
        print("\nЧто хотите сделать?\n")
        print("  1. Запустить графический интерфейс (UI)")
        print("  2. Запустить команду через CLI")
        print("  0. Выход\n")

        print("Выбор: ", end="", flush=True)
        choice = _getch().strip()

        if choice == "1":
            print("\nЗапускаю UI...\n")
            code = run_ui()
            if code != 0:
                print(f"\nUI завершился с ошибкой (код {code}).")
        elif choice == "2":
            cli_menu()
        elif choice == "0":
            print("До встречи!")
            sys.exit(0)
        else:
            print("Неизвестный вариант, попробуйте ещё раз.")


# ──────────────────────────────────────────────
# Пауза перед закрытием (чтобы окно не схлопнулось при клике)
# ──────────────────────────────────────────────

def _pause_and_exit(code: int = 0) -> None:
    """На Windows окно закроется сразу — даём прочитать."""
    if platform.system() == "Windows":
        input("\nНажмите Enter для закрытия...")
    sys.exit(code)


# ──────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────

def main() -> None:
    print("=" * 42)
    print("   HH Applicant Tool")
    print("=" * 42)

    # 0. Проверка версии Python (pywebview/pythonnet не работает на слишком новых)
    _maybe_relaunch()

    # 1. Автоустановка зависимостей
    ensure_installed()

    # 2. Первый запуск — авторизация
    if not has_token():
        print("Добро пожаловать! Похоже, это первый запуск.\n")
        print("Для работы нужно войти в аккаунт hh.ru.")
        print("Откроется браузер для авторизации...\n")
        run_authorize()
        if not has_token():
            print("\nАвторизация не удалась.\n")
            _pause_and_exit(1)
        print("\nУспешно! Вы авторизованы.\n")

    # 3. Главное меню
    main_menu()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nОтменено.")
        sys.exit(0)

import argparse
import logging
from os import getenv

from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..main import get_proxies
from ..telemetry_client import TelemetryClient

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    username: str | None = None
    password: str | None = None
    search: str | None = None


class Operation(BaseOperation):
    """Выведет контакты работодателя по заданной строке поиска"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-u",
            "--username",
            type=str,
            help="Имя пользователя для аутентификации",
            default=getenv("AUTH_USERNAME"),
        )
        parser.add_argument(
            "-P",
            "--password",
            type=str,
            help="Пароль для аутентификации",
            default=getenv("AUTH_PASSWORD"),
        )
        parser.add_argument(
            "-s",
            "--search",
            type=str,
            default="",
            help="Строка поиска для контактов работодателя",
        )
        parser.add_argument(
            "-p",
            "--page",
            default=1,
            help="Номер страницы в выдаче",
        )

    def run(self, args: Namespace) -> None:
        proxies = get_proxies(args)
        client = TelemetryClient(proxies=proxies)
        auth = (
            (args.username, args.password)
            if args.username and args.password
            else None
        )
        # Аутентификация пользователя
        results = client.get_telemetry(
            "/contact/persons",
            {"search": args.search, "per_page": 10, "page": args.page},
            auth=auth,
        )
        self._print_contacts(results)

    def _print_contacts(self, data: dict) -> None:
        """Вывод всех контактов в древовидной структуре."""
        page = data["page"]
        pages = (data["total"] // data["per_page"]) + 1
        print(f"📋 Контакты ({page}/{pages}):")
        contacts = data.get("contact_persons", [])
        for idx, contact in enumerate(contacts):
            is_last_contact = idx == len(contacts) - 1
            self._print_contact(contact, is_last_contact)
        print()

    def _print_contact(self, contact: dict, is_last_contact: bool) -> None:
        """Вывод информации о конкретном контакте."""
        prefix = "└──" if is_last_contact else "├──"
        print(f" {prefix} 🧑 {contact.get('name', 'н/д')}")
        prefix2 = "    " if is_last_contact else " │   "
        print(f"{prefix2}├── 📧 Email: {contact.get('email', 'н/д')}")
        employer = contact.get("employer") or {}
        print(f"{prefix2}├── 🏢 Работодатель: {employer.get('name', 'н/д')}")
        print(f"{prefix2}├── 🏠 Город: {employer.get('area', 'н/д')}")
        print(f"{prefix2}├── 🌐 Сайт: {employer.get('site_url', 'н/д')}")

        phones = contact["phone_numbers"] or [{"phone_number": "(нет номеров)"}]
        print(f"{prefix2}├── 📞 Телефоны:")
        last_phone = len(phones) - 1
        for i, phone in enumerate(phones):
            sub_prefix = "└──" if i == last_phone else "├──"
            print(f"{prefix2}│   {sub_prefix} {phone['phone_number']}")

        telegrams = contact["telegram_usernames"] or [
            {"username": "(нет аккаунтов)"}
        ]
        print(f"{prefix2}└── 📱 Telegram:")
        last_telegram = len(telegrams) - 1
        for i, telegram in enumerate(telegrams):
            sub_prefix = "└──" if i == last_telegram else "├──"
            print(f"{prefix2}    {sub_prefix} {telegram['username']}")

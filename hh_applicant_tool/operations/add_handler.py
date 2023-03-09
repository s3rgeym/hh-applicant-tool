import argparse
import logging
from pathlib import Path
from subprocess import check_call

from ..constants import HHANDROID_SOCKET_PATH
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..utils import print_err

logger = logging.getLogger(__name__)

DESKTOP_ENTRY = f"""[Desktop Entry]
Name=hhandroid protocol handler
Exec=sh -c 'printf %u | socat UNIX-CONNECT:{HHANDROID_SOCKET_PATH} -'
Type=Application
Terminal=false
MimeType=x-scheme-handler/hhandroid
"""


class Namespace(BaseNamespace):
    force: bool


class Operation(BaseOperation):
    """Добавляет обработчик для протокола hhandroid, используемого Android-приложением при авторизации"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-f",
            "--force",
            help="Перезаписать если существует",
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def run(self, args: Namespace) -> None:
        # TODO: с root не будет работать
        desktop_path = Path(
            "~/.local/share/applications/hhandroid.desktop"
        ).expanduser()
        if args.force or not desktop_path.exists():
            desktop_path.write_text(DESKTOP_ENTRY)
            logger.info("saved %s", desktop_path)
            check_call(["update-desktop-database", str(desktop_path.parent)])
            print("✅ Обработчик добавлен!")
        else:
            print_err("⛔ Обработчик уже существует!")
            return 1

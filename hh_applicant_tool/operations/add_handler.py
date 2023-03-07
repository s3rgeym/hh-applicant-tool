import argparse
from pathlib import Path
from subprocess import check_call

from ..contsants import HHANDROID_SOCKET_PATH
from ..main import BaseOperation, logger

DESKTOP_ENTRY = f"""[Desktop Entry]
Name=hhandroid protocol handler
Exec=sh -c 'printf %u | socat UNIX-CONNECT:{HHANDROID_SOCKET_PATH} -'
Type=Application
Terminal=false
MimeType=x-scheme-handler/hhandroid
"""


class Operation(BaseOperation):
    """Добавляет обработчик для протокола hhandroid, используемого Android-приложением при авторизации"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        # TODO: с root не будет работать
        desktop_path = Path(
            "~/.local/share/applications/hhandroid.desktop"
        ).expanduser()
        desktop_path.write_text(DESKTOP_ENTRY)
        logger.info("saved %s", desktop_path)
        check_call(["update-desktop-database", str(desktop_path.parent)])
        print("✅ Обработчик добавлен!")

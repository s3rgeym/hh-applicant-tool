import logging
import re
from logging.handlers import RotatingFileHandler
from os import PathLike
from typing import Callable

MAX_LOG_SIZE = 10 << 20

_logger = logging.getLogger(__name__)


class ColorHandler(logging.StreamHandler):
    styles: dict[str, str] = {
        "CRITICAL": "1;31",
        "ERROR": "31",
        "WARNING": "91",
        "INFO": "32",
        "DEBUG": "34",
    }

    def format(self, record: logging.LogRecord) -> str:
        orig_exc_info = record.exc_info
        if self.level > logging.DEBUG:
            record.exc_info = None

        message = super().format(record)
        record.exc_info = orig_exc_info

        style = self.styles.get(record.levelname)
        if not style:
            return message
        return f"\033[{style}m{message}\033[0m"


class RedactingFilter(logging.Filter):
    def __init__(
        self,
        patterns: list[str],
        placeholder: str | Callable = lambda m: "*" * len(m.group(0)),
    ):
        super().__init__()
        self.pattern = (
            re.compile(f"({'|'.join(patterns)})") if patterns else None
        )
        self.placeholder = placeholder

    def filter(self, record: logging.LogRecord) -> bool:
        if self.pattern:
            msg = record.getMessage()
            msg = self.pattern.sub(self.placeholder, msg)
            record.msg, record.args = msg, ()

        return True


def configure(
    verbosity_level: int,
    log_file: PathLike,
) -> None:
    _logger.setLevel(logging.DEBUG)

    color_handler = ColorHandler()
    color_handler.setFormatter(
        logging.Formatter("[%(levelname).1s] %(message)s")
    )
    color_handler.setLevel(verbosity_level)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_SIZE,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    file_handler.setLevel(logging.DEBUG)

    redactor = RedactingFilter(
        [
            r"\b[A-Z0-9]{64,}\b",
            r"\b[a-fA-F0-9]{32,}\b",
        ]
    )
    file_handler.addFilter(redactor)

    for handler in (color_handler, file_handler):
        _logger.addHandler(handler)


debug, info, warning, error, exception, critical = (
    _logger.debug,
    _logger.info,
    _logger.warning,
    _logger.error,
    _logger.exception,
    _logger.critical,
)

warn = warning

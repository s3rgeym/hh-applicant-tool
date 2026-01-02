import enum
import logging
import re
from enum import auto


class Color(enum.Enum):
    BLACK = 30
    RED = auto()
    GREEN = auto()
    YELLOW = auto()
    BLUE = auto()
    PURPLE = auto()
    CYAN = auto()
    WHITE = auto()

    def __str__(self) -> str:
        return str(self.value)


class ColorHandler(logging.StreamHandler):
    _color_map = {
        "CRITICAL": Color.RED,
        "ERROR": Color.RED,
        "WARNING": Color.RED,
        "INFO": Color.GREEN,
        "DEBUG": Color.BLUE,
    }

    def format(self, record: logging.LogRecord) -> str:
        # Подавляем вывод подробного сообщения об ошибке
        orig_exc_info = record.exc_info
        # Детали ошибки показываем только при отладке
        if self.level > logging.DEBUG:
            record.exc_info = None
        message = super().format(record)
        # Обязательно нужно восстановить оригинальное значение или в файловом
        # логе не будет деталей ошибки
        record.exc_info = orig_exc_info
        # isatty = getattr(self.stream, "isatty", None)
        # if isatty and isatty():
        color_code = self._color_map[record.levelname]
        return f"\033[{color_code}m{message}\033[0m"
        # return message


class RedactingFilter(logging.Filter):
    def __init__(self, patterns: list[str]):
        super().__init__()
        self.regex = re.compile(f"({'|'.join(patterns)})") if patterns else None

    def filter(self, record: logging.LogRecord) -> bool:
        if self.regex:
            msg = record.getMessage()
            msg = self.regex.sub("[REDACTED]", msg)
            record.msg, record.args = msg, ()

        return True

import enum
import logging
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
        message = super().format(record)
        isatty = getattr(self.stream, "isatty", None)
        if isatty and isatty():
            color_code = self._color_map[record.levelname]
            return f"\033[{color_code}m{message}\033[0m"
        return message

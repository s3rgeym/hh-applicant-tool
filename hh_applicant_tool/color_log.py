import enum
import logging
from enum import auto
import os


if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
    # Берем дескриптор стандартного вывода (stdout)
    handle = kernel32.GetStdHandle(-11) 
    mode = ctypes.c_uint()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    kernel32.SetConsoleMode(handle, mode.value | 0x0004)


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

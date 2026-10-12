import os
import platform
import sys
from pathlib import Path

env = os.getenv


def is_docker() -> bool:
    return Path("/.dockerenv").exists()


def has_gui_support() -> bool:
    if "Linux" in sys.platform:
        return "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ
    return True


def get_config_directory() -> Path:
    match platform.system():
        case "Windows":
            return Path(env("APPDATA", Path.home() / "AppData" / "Roaming"))
        case "Darwin":
            return Path.home() / "Library" / "Application Support"
        case _:
            return Path(env("XDG_CONFIG_HOME", Path.home() / ".config"))

import os
import sys
from pathlib import Path


def is_docker() -> bool:
    return Path("/.dockerenv").exists()


def has_gui_support() -> bool:
    if "Linux" in sys.platform:
        return "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ
    return True

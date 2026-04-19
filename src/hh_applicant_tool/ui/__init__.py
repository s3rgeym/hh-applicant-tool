from __future__ import annotations

from pathlib import Path
from threading import Timer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import HHApplicantTool

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_window(tool: HHApplicantTool, *, debug: bool = False) -> None:
    import webview

    from .api import Api

    def release_on_top() -> None:
        try:
            window.on_top = False
        except Exception:
            pass

    def bring_to_front() -> None:
        try:
            window.restore()
        except Exception:
            pass
        try:
            window.show()
        except Exception:
            pass
        Timer(1.5, release_on_top).start()

    api = Api(tool)
    window = webview.create_window(
        title="HH Applicant Tool",
        url=(TEMPLATES_DIR / "index.html").as_uri(),
        js_api=api,
        width=1100,
        height=750,
        min_size=(800, 500),
        on_top=True,
    )
    api.set_window(window)
    webview.start(bring_to_front, debug=debug, http_server=True)

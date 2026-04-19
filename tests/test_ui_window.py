from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hh_applicant_tool.ui import TEMPLATES_DIR, create_window  # noqa: E402


class _FakeWindow:
    def __init__(self):
        self.on_top = True

    def restore(self):
        return None

    def show(self):
        return None


def test_create_window_uses_file_uri_and_http_server(monkeypatch):
    captured = {}
    fake_window = _FakeWindow()

    def fake_create_window(**kwargs):
        captured["create_window"] = kwargs
        return fake_window

    def fake_start(callback, **kwargs):
        captured["start"] = kwargs
        callback()

    fake_webview = types.SimpleNamespace(
        create_window=fake_create_window,
        start=fake_start,
    )

    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    class _FakeApi:
        def __init__(self, tool):
            self.tool = tool

        def set_window(self, window):
            captured["window"] = window

    monkeypatch.setitem(
        sys.modules,
        "hh_applicant_tool.ui.api",
        types.SimpleNamespace(Api=_FakeApi),
    )

    create_window(tool=object(), debug=False)

    kwargs = captured["create_window"]
    assert kwargs["url"] == (TEMPLATES_DIR / "index.html").as_uri()
    assert kwargs["on_top"] is True
    assert captured["start"]["http_server"] is True
    assert captured["window"] is fake_window

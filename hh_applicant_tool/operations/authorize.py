import argparse
import logging
import time
from urllib.parse import parse_qs, urlsplit
import sys
from typing import Any

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineCore import QWebEngineUrlSchemeHandler
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    # Заглушки чтобы на сервере не нужно было ставить сотни мегабайт qt-говна

    class QUrl:
        pass

    class QApplication:
        pass

    class QMainWindow:
        pass

    class QWebEngineUrlSchemeHandler:
        pass

    class QWebEngineView:
        pass


from ..api import OAuthClient
from ..main import BaseOperation, Namespace
from ..utils import Config

logger = logging.getLogger(__package__)


class HHAndroidUrlSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, parent: "WebViewWindow") -> None:
        super().__init__()
        self.parent = parent

    def requestStarted(self, info: Any) -> None:
        url = info.requestUrl().toString()
        if url.startswith("hhandroid://"):
            self.parent.handle_redirect_uri(url)


class WebViewWindow(QMainWindow):
    def __init__(
        self, url: str, oauth_client: OAuthClient, config: Config
    ) -> None:
        super().__init__()
        self.oauth_client = oauth_client
        self.config = config
        # Настройка WebEngineView
        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)
        self.setWindowTitle("Авторизация на HH.RU")
        self.hhandroid_handler = HHAndroidUrlSchemeHandler(self)
        # Установка перехватчика запросов и обработчика кастомной схемы
        profile = self.web_view.page().profile()
        profile.installUrlSchemeHandler(b"hhandroid", self.hhandroid_handler)
        # Настройки окна для мобильного вида
        self.resize(480, 800)
        self.web_view.setUrl(QUrl(url))

    def handle_redirect_uri(self, redirect_uri: str) -> None:
        logger.debug(f"handle redirect uri: {redirect_uri}")
        sp = urlsplit(redirect_uri)
        code = parse_qs(sp.query).get("code", [None])[0]
        if code:
            token = self.oauth_client.authenticate(code)
            logger.debug("Сохраняем токен")
            self.config.save(token=dict(token, created_at=int(time.time())))
            print("🔓 Авторизация прошла успешно!")
            self.close()


class Operation(BaseOperation):
    """Авторизоваться на сайте"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace) -> None:
        oauth = OAuthClient(
            user_agent=(
                args.config["oauth_user_agent"] or args.config["user_agent"]
            ),
        )

        app = QApplication(sys.argv)
        window = WebViewWindow(
            oauth.authorize_url, oauth_client=oauth, config=args.config
        )
        window.show()

        app.exec()

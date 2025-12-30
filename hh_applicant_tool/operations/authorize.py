import argparse
import logging
from urllib.parse import parse_qs, urlsplit
import sys
from typing import Any
from ..utils import print_err

from ..api import ApiClient  # noqa: E402
from ..main import BaseOperation, Namespace  # noqa: E402

logger = logging.getLogger(__package__)

QT_IMPORTED = False

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineCore import QWebEngineUrlSchemeHandler
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtNetwork import QNetworkProxy

    QT_IMPORTED = True
except ImportError as ex:
    logger.debug(ex)
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



class HHAndroidUrlSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, parent: "WebViewWindow") -> None:
        super().__init__()
        self.parent = parent

    def requestStarted(self, info: Any) -> None:
        url = info.requestUrl().toString()
        if url.startswith("hhandroid://"):
            self.parent.handle_redirect_uri(url)


class WebViewWindow(QMainWindow):
    def __init__(self, api_client: ApiClient) -> None:
        super().__init__()
        self.api_client = api_client
        
        self.web_view = QWebEngineView()   
        self.setCentralWidget(self.web_view)
        self.setWindowTitle("Авторизация на HH.RU")
        self.hhandroid_handler = HHAndroidUrlSchemeHandler(self)
        
        profile = self.web_view.page().profile()
        profile.installUrlSchemeHandler(b"hhandroid", self.hhandroid_handler)
        
        self.web_view.page().acceptNavigationRequest = self._filter_http_requests

        self.resize(480, 800)
        self.web_view.setUrl(QUrl(api_client.oauth_client.authorize_url))

    def _filter_http_requests(self, url: QUrl, _type, is_main_frame):
        """Блокирует любые переходы по протоколу HTTP"""
        if url.scheme().lower() == "http":
            logger.warning(f"🚫 Заблокирован небезопасный запрос: {url.toString()}")
            return False
        return True

    def handle_redirect_uri(self, redirect_uri: str) -> None:
        logger.debug(f"handle redirect uri: {redirect_uri}")
        sp = urlsplit(redirect_uri)
        code = parse_qs(sp.query).get("code", [None])[0]
        if code:
            token = self.api_client.oauth_client.authenticate(code)
            self.api_client.handle_access_token(token)
            print("🔓 Авторизация прошла успешно!")
            self.close()


class Operation(BaseOperation):
    """Авторизоваться на сайте"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: Namespace, api_client: ApiClient, *_) -> None:
        if not QT_IMPORTED:
            print_err(
                "❗Критиническая Ошибка: PyQt6 не был импортирован, возможно, вы долбоеб и забыли его установить, либо же криворукие разрабы этой либы опять все сломали..."
            )
            sys.exit(1)

        proxies = api_client.proxies
        if proxy_url := proxies.get("https"):
            logger.debug(f"{proxy_url = }")
            import os
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"--proxy-server={proxy_url}"

        app = QApplication(sys.argv)
        window = WebViewWindow(api_client=api_client)
        window.show()

        app.exec()

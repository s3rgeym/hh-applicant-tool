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
    from PyQt6.QtWebEngineCore import QWebEngineProxySettings, QWebEngineUrlSchemeHandler
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
        self._setup_proxy()
        
        self.setCentralWidget(self.web_view)
        self.setWindowTitle("Авторизация на HH.RU")
        self.hhandroid_handler = HHAndroidUrlSchemeHandler(self)
        
        profile = self.web_view.page().profile()
        profile.installUrlSchemeHandler(b"hhandroid", self.hhandroid_handler)
        
        self.web_view.page().acceptNavigationRequest = self._filter_http_requests

        self.resize(480, 800)
        self.web_view.setUrl(QUrl(api_client.oauth_client.authorize_url))

    def _setup_proxy(self):
        proxies = self.api_client.proxies
        if not proxies:
            return

        # Приоритет HTTPS
        proxy_url = proxies.get("https") or proxies.get("http")
        if not proxy_url:
            return

        proxy_qurl = QUrl(proxy_url)
        
        # В PyQt6 используется QWebEngineProxySettings через профиль
        profile = self.web_view.page().profile()
        proxy_settings = profile.proxySettings()

        # Настраиваем тип
        scheme = proxy_qurl.scheme().lower()
        if "socks5" in scheme:
            proxy_settings.setType(QWebEngineProxySettings.ProxyType.Socks5Proxy)
        else:
            proxy_settings.setType(QWebEngineProxySettings.ProxyType.HttpProxy)

        # Хост и порт
        proxy_settings.setHostName(proxy_qurl.host())
        if proxy_qurl.port() != -1:
            proxy_settings.setPort(proxy_qurl.port())
        else:
            # Стандартные порты, если не указаны
            proxy_settings.setPort(1080 if "socks" in scheme else 8080)

        # Авторизация
        if proxy_qurl.userName():
            proxy_settings.setUserName(proxy_qurl.userName())
        if proxy_qurl.password():
            proxy_settings.setPassword(proxy_qurl.password())

        # ВАЖНО: В некоторых версиях изменения применяются автоматически,
        # но для надежности можно переприсвоить настройки (если это поддерживает API)
        # либо просто убедиться, что мы меняли объект, полученный из профиля.
        logger.debug(f"Proxy configured for profile: {proxy_url}")

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

        app = QApplication(sys.argv)
        window = WebViewWindow(api_client=api_client)
        window.show()

        app.exec()

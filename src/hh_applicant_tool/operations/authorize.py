from __future__ import annotations

import argparse
import asyncio
import logging
import typing
from datetime import datetime
from http.cookiejar import Cookie
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

try:
    from playwright.async_api import async_playwright
except ImportError:
    pass

from ..main import BaseOperation
from ..utils.terminal import print_kitty_image, print_sixel_mage

if TYPE_CHECKING:
    from ..main import HHApplicantTool


HH_ANDROID_SCHEME = "hhandroid"

logger = logging.getLogger(__name__)


class Operation(BaseOperation):
    """Авторизация через Playwright"""

    __aliases__: list = ["authenticate", "auth", "login"]

    # Селекторы
    SEL_LOGIN_INPUT = 'input[data-qa="login-input-username"]'
    SEL_EXPAND_PASSWORD = 'button[data-qa="expand-login-by_password"]'
    SEL_PASSWORD_INPUT = 'input[data-qa="login-input-password"]'
    SEL_CODE_CONTAINER = 'div[data-qa="account-login-code-input"]'
    SEL_PIN_CODE_INPUT = 'input[data-qa="magritte-pincode-input-field"]'
    SEL_CAPTCHA_IMAGE = 'img[data-qa="account-captcha-picture"]'
    SEL_CAPTCHA_INPUT = 'input[data-qa="account-captcha-input"]'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool: HHApplicantTool | None = None

    @property
    def is_headless(self) -> bool:
        return not self._tool.args.no_headless and self.is_automated

    @property
    def is_automated(self) -> bool:
        return not self._tool.args.manual

    @property
    def selector_timeout(self) -> int | None:
        return None if self.is_headless else 5000

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("username", nargs="?", help="Email или телефон")
        parser.add_argument("--password", "-p", help="Пароль для входа")
        parser.add_argument(
            "--no-headless",
            "-n",
            action="store_true",
            help="Показать окно браузера",
        )
        parser.add_argument(
            "-m", "--manual", action="store_true", help="Ручной режим ввода"
        )
        parser.add_argument(
            "-k",
            "--use-kitty",
            "--kitty",
            action="store_true",
            help="Вывод капчи в kitty",
        )
        parser.add_argument(
            "-s",
            "--use-sixel",
            "--sixel",
            action="store_true",
            help="Вывод капчи в sixel",
        )

    def run(self, tool: HHApplicantTool) -> int | None:
        self._tool = tool
        try:
            asyncio.run(self._run())
        except (KeyboardInterrupt, asyncio.TimeoutError):
            logger.warning("Операция прервана пользователем или по таймауту")
            return 1
        return 0

    async def _run(self) -> None:
        args = self._tool.args
        api_client = self._tool.api_client
        storage = self._tool.storage

        if self.is_automated:
            username = (
                args.username
                or storage.settings.get_value("auth.username")
                or (
                    await asyncio.to_thread(
                        input, "👤 Введите email или телефон: "
                    )
                )
            ).strip()
            if not username:
                raise RuntimeError("Empty username")
            logger.debug(f"authenticate with: {username}")

        proxies = api_client.proxies
        proxy_url = proxies.get("https")
        chromium_args: list[str] = []
        if proxy_url:
            chromium_args.append(f"--proxy-server={proxy_url}")
            logger.debug(f"Используется прокси: {proxy_url}")

        if self.is_headless:
            logger.debug("Headless режим активен")

        async with async_playwright() as pw:
            logger.debug("Запуск браузера...")
            browser = await pw.chromium.launch(
                headless=self.is_headless, args=chromium_args
            )

            try:
                android_device = pw.devices["Galaxy A55"]
                context = await browser.new_context(**android_device)
                page = await context.new_page()

                code_future: asyncio.Future[str | None] = asyncio.Future()

                def handle_request(request):
                    url = request.url
                    if url.startswith(f"{HH_ANDROID_SCHEME}://"):
                        logger.info(f"Перехвачен OAuth redirect: {url}")
                        if not code_future.done():
                            sp = urlsplit(url)
                            code = parse_qs(sp.query).get("code", [None])[0]
                            code_future.set_result(code)

                page.on("request", handle_request)

                logger.debug(
                    f"Переход на страницу OAuth: {api_client.oauth_client.authorize_url}"
                )
                await page.goto(
                    api_client.oauth_client.authorize_url,
                    timeout=30000,
                    wait_until="load",
                )

                if self.is_automated:
                    await page.wait_for_selector(
                        self.SEL_LOGIN_INPUT, timeout=self.selector_timeout
                    )
                    await page.fill(self.SEL_LOGIN_INPUT, username)
                    logger.debug("Логин введен")

                    password = args.password or storage.settings.get_value(
                        "auth.password"
                    )
                    if password:
                        await self._direct_login(page, password)
                    else:
                        await self._onetime_code_login(page)

                logger.debug("Ожидание OAuth-кода...")
                auth_code = await asyncio.wait_for(
                    code_future, timeout=[None, 60.0][self.is_automated]
                )

                page.remove_listener("request", handle_request)

                logger.debug("Код получен, пробуем получить токен...")
                token = await asyncio.to_thread(
                    api_client.oauth_client.authenticate, auth_code
                )
                api_client.handle_access_token(token)

                print("🔓 Авторизация прошла успешно!")

                if self.is_automated:
                    storage.settings.set_value("auth.username", username)
                    if args.password:
                        storage.settings.set_value(
                            "auth.password", args.password
                        )

                storage.settings.set_value("auth.last_login", datetime.now())
                cookies = await context.cookies()
                self._set_session_cookies(cookies)

            finally:
                logger.debug("Закрытие браузера")
                await browser.close()

    async def _direct_login(self, page, password: str) -> None:
        logger.info("Вход по паролю...")
        await page.click(self.SEL_EXPAND_PASSWORD)
        await self._handle_captcha(page)
        await page.wait_for_selector(
            self.SEL_PASSWORD_INPUT, timeout=self.selector_timeout
        )
        await page.fill(self.SEL_PASSWORD_INPUT, password)
        await page.press(self.SEL_PASSWORD_INPUT, "Enter")
        logger.debug("Форма с паролем отправлена")

    async def _onetime_code_login(self, page) -> None:
        logger.info("Вход по одноразовому коду...")
        await page.press(self.SEL_LOGIN_INPUT, "Enter")
        await self._handle_captcha(page)
        await page.wait_for_selector(
            self.SEL_CODE_CONTAINER, timeout=self.selector_timeout
        )

        print("📨 Код был отправлен. Проверьте почту или SMS.")
        code = (
            await asyncio.to_thread(input, "📩 Введите полученный код: ")
        ).strip()
        if not code:
            raise RuntimeError("Код подтверждения не может быть пустым.")

        await page.fill(self.SEL_PIN_CODE_INPUT, code)
        await page.press(self.SEL_PIN_CODE_INPUT, "Enter")
        logger.debug("Форма с кодом отправлена")

    async def _handle_captcha(self, page):
        try:
            captcha_element = await page.wait_for_selector(
                self.SEL_CAPTCHA_IMAGE,
                timeout=self.selector_timeout,
                state="visible",
            )
        except Exception:
            logger.debug("Капчи нет, продолжаем.")
            return

        args = self._tool.args
        if not (args.use_kitty or args.use_sixel):
            raise RuntimeError(
                "Требуется ввод капчи! Используйте --kitty или --sixel."
            )

        img_bytes = await captcha_element.screenshot()
        print("\n[!] Требуется ввод капчи.")
        if args.use_kitty:
            print_kitty_image(img_bytes)
        elif args.use_sixel:
            print_sixel_mage(img_bytes)

        captcha_text = (
            await asyncio.to_thread(input, "Введите текст с картинки: ")
        ).strip()
        await page.fill(self.SEL_CAPTCHA_INPUT, captcha_text)
        await page.press(self.SEL_CAPTCHA_INPUT, "Enter")
        logger.debug("Капча отправлена")

    def _set_session_cookies(self, cookies: list[dict[str, typing.Any]]):
        for c in cookies:
            cookie = Cookie(
                version=0,
                name=c["name"],
                value=c["value"],
                port=None,
                port_specified=False,
                domain=c["domain"],
                domain_specified=True,
                domain_initial_dot=c["domain"].startswith("."),
                path=c["path"],
                path_specified=True,
                secure=c["secure"],
                expires=int(c.get("expires") or 0),
                discard=False,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": str(c.get("httpOnly", False))},
                rfc2109=False,
            )
            self._tool.session.cookies.set_cookie(cookie)

from __future__ import annotations

import argparse
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

try:
    from playwright.async_api import async_playwright
except ImportError:
    pass

from ..main import BaseOperation, DEFAULT_DESKTOP_USER_AGENT
from ..utils.terminal import print_kitty_image, print_sixel_mage

if TYPE_CHECKING:
    from ..main import HHApplicantTool

HH_ANDROID_SCHEME = "hhandroid"

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor()


async def ainput(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, input, prompt)


class Operation(BaseOperation):
    """Авторизация через Playwright (Web -> OAuth)"""

    __aliases__: list = ["authenticate", "auth", "login"]

    # Селекторы
    SEL_SUBMIT = '[data-qa="submit-button"]'
    SEL_RADIO_PHONE = '[data-qa="credential-type-PHONE"]'
    SEL_RADIO_EMAIL = '[data-qa="credential-type-EMAIL"]'
    SEL_EMAIL_INPUT = '[data-qa="applicant-login-input-email"]'
    SEL_PHONE_INPUT = '[data-qa="magritte-phone-input-national-number-input"]'
    SEL_EXPAND_PASSWORD = '[data-qa="expand-login-by-password"]'
    SEL_PASSWORD_INPUT = '[data-qa="applicant-login-input-password"]'
    SEL_EXPAND_CODE = '[data-qa="expand-login-by-code-text"]'
    SEL_PIN_INPUT = '[data-qa="magritte-pincode-input-field"]'
    SEL_OAUTH_ALLOW = '[data-qa="oauth-grant-allow"]'

    # Селекторы капчи (на случай появления)
    SEL_CAPTCHA_IMAGE = 'img[data-qa="account-captcha-picture"]'
    SEL_CAPTCHA_INPUT = 'input[data-qa="account-captcha-input"]'

    LOGIN_URL = (
        "https://hh.ru/account/login?role=applicant&backurl=%2F&hhtmFrom=main"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool: HHApplicantTool | None = None

    @property
    def args(self):
        return self._tool.args

    @property
    def is_headless(self) -> bool:
        return not self.args.no_headless and self.is_automated

    @property
    def is_automated(self) -> bool:
        return not self.args.manual

    @property
    def selector_timeout(self) -> int | None:
        return None if self.is_headless else 5000

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("username", nargs="?", help="Email или телефон")
        parser.add_argument("--password", "-p", help="Пароль для входа")
        parser.add_argument(
            "--no-headless", action="store_true", help="Показать окно браузера"
        )
        parser.add_argument(
            "-m", "--manual", action="store_true", help="Ручной режим"
        )
        parser.add_argument(
            "-k",
            "--use-kitty",
            "--kitty",
            action="store_true",
            help="Kitty protocol",
        )
        parser.add_argument(
            "-s",
            "--use-sixel",
            "--sixel",
            action="store_true",
            help="Sixel protocol",
        )

    def run(self, tool: HHApplicantTool) -> None:
        self._tool = tool
        try:
            asyncio.run(self._main())
        except (KeyboardInterrupt, asyncio.TimeoutError):
            logger.warning("Операция прервана")
            return 1

    async def _main(self) -> None:
        api_client = self._tool.api_client
        storage = self._tool.storage

        if self.is_automated:
            username = (
                self.args.username
                or storage.settings.get_value("auth.username")
                or (await ainput("👤 Введите email или телефон: "))
            ).strip()
            if not username:
                raise RuntimeError("Empty username")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.is_headless)
            context = await browser.new_context(
                user_agent=DEFAULT_DESKTOP_USER_AGENT
            )
            page = await context.new_page()

            # 1. Переход на страницу входа
            logger.debug(f"Переход на {self.LOGIN_URL}")
            await page.goto(self.LOGIN_URL, wait_until="load")

            # 2. Нажимаем на сабмит
            await page.click(self.SEL_SUBMIT)

            # 3. Ждем 3 секунды (не полагаемся на селекторы, так как HH может менять дефолтный ввод)
            await asyncio.sleep(3)

            # 4. Выбор типа логина и ввод
            if "@" in username:
                logger.debug(f"Переключение на ввод email и ввод: {username}")
                await page.check(self.SEL_RADIO_EMAIL, force=True)
                await page.fill(self.SEL_EMAIL_INPUT, username)
            else:
                logger.debug(f"Вводим телефон: {username}")
                await page.fill(self.SEL_PHONE_INPUT, username)

            # 5. Клик по кнопке пароля
            await page.click(self.SEL_EXPAND_PASSWORD)

            password = self.args.password or storage.settings.get_value(
                "auth.password"
            )

            if password:
                # 6а. Ввод пароля и сабмит
                await page.wait_for_selector(self.SEL_PASSWORD_INPUT)
                await page.fill(self.SEL_PASSWORD_INPUT, password)
                await page.click(self.SEL_SUBMIT)
            else:
                # 6б. Вход по коду
                await page.click(self.SEL_EXPAND_CODE)
                await page.wait_for_selector(self.SEL_PIN_INPUT)
                print("📨 Код отправлен. Проверьте почту или SMS.")
                code = (await ainput("📩 Введите полученный код: ")).strip()
                await page.fill(self.SEL_PIN_INPUT, code)
                await page.press(self.SEL_PIN_INPUT, "Enter")

            # 7. Проверка авторизации (редирект на главную)
            try:
                await page.wait_for_url(
                    lambda url: "/account/login" not in url, timeout=3000
                )
                logger.info("Успешная авторизация в веб-интерфейсе")
            except Exception as ex:
                raise RuntimeError(
                    "Авторизация не удалась: редирект на hh.ru не выполнен"
                ) from ex

            await self._save_cookies(context)

            # 8. OAuth этап
            code_future: asyncio.Future[str | None] = asyncio.Future()

            def handle_request(request):
                if request.url.startswith(f"{HH_ANDROID_SCHEME}://"):
                    if not code_future.done():
                        sp = urlsplit(request.url)
                        code = parse_qs(sp.query).get("code", [None])[0]
                        code_future.set_result(code)

            page.on("request", handle_request)

            logger.debug("Переход на страницу OAuth")
            await page.goto(
                api_client.oauth_client.authorize_url, wait_until="load"
            )

            # 9. Нажимаем "Разрешить"
            await page.wait_for_selector(self.SEL_OAUTH_ALLOW)
            await page.click(self.SEL_OAUTH_ALLOW)

            # 10. Ждем код
            auth_code = await asyncio.wait_for(code_future, timeout=30.0)

            # Финализация
            token = await asyncio.to_thread(
                api_client.oauth_client.authenticate, auth_code
            )
            api_client.handle_access_token(token)

            print("🔓 Авторизация прошла успешно!")

            if self.is_automated:
                storage.settings.set_value("auth.username", username)
                if self.args.password:
                    storage.settings.set_value(
                        "auth.password", self.args.password
                    )
                storage.settings.set_value("auth.last_login", datetime.now())

            await browser.close()

    async def _handle_captcha(self, page):
        try:
            captcha_element = await page.wait_for_selector(
                self.SEL_CAPTCHA_IMAGE, timeout=2000, state="visible"
            )
        except Exception:
            return

        if not (self.args.use_kitty or self.args.use_sixel):
            raise RuntimeError(
                "Требуется ввод капчи! Используйте --kitty или --sixel."
            )

        img_bytes = await captcha_element.screenshot()
        if self.args.use_kitty:
            print_kitty_image(img_bytes)
        elif self.args.use_sixel:
            print_sixel_mage(img_bytes)

        captcha_text = (await ainput("Введите текст с капчи: ")).strip()
        await page.fill(self.SEL_CAPTCHA_INPUT, captcha_text)
        await page.press(self.SEL_CAPTCHA_INPUT, "Enter")

    async def _save_cookies(self, context):
        filename = self._tool.cookies_file
        cookies = await context.cookies()

        with open(filename, "w", encoding="utf-8") as f:
            # Обязательный заголовок Netscape-формата
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file! Do not edit.\n")

            for c in cookies:
                domain = c["domain"]

                # HttpOnly поддержка
                if c.get("httpOnly"):
                    domain = "#HttpOnly_" + domain

                include_subdomains = (
                    "TRUE" if c["domain"].startswith(".") else "FALSE"
                )

                secure = "TRUE" if c.get("secure") else "FALSE"

                # 0 означает session cookie (как ожидает MozillaCookieJar)
                expires = int(c["expires"]) if c.get("expires") else 0

                line = (
                    f"{domain}\t"
                    f"{include_subdomains}\t"
                    f"{c['path']}\t"
                    f"{secure}\t"
                    f"{expires}\t"
                    f"{c['name']}\t"
                    f"{c['value']}\n"
                )

                f.write(line)

        logger.info(f"Куки сохранены в {filename}")

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from ..main import BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


HH_ANDROID_SCHEME = "hhandroid"

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor()


async def ainput(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, input, prompt)


class Operation(BaseOperation):
    """Авторизация через Playwright"""

    __aliases__: list = ["auth", "authenticate"]

    # Селекторы
    SEL_LOGIN_INPUT = 'input[data-qa="login-input-username"]'
    SEL_EXPAND_PASSWORD_BTN = 'button[data-qa="expand-login-by_password"]'
    SEL_PASSWORD_INPUT = 'input[data-qa="login-input-password"]'
    SEL_CODE_CONTAINER = 'div[data-qa="account-login-code-input"]'
    SEL_PIN_CODE_INPUT = 'input[data-qa="magritte-pincode-input-field"]'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._args = None

    @property
    def is_headless(self) -> bool:
        """Свойство, определяющее режим работы браузера"""
        return not self._args.no_headless

    @property
    def selector_timeout(self) -> int | None:
        """Вспомогательное свойство для таймаутов: None если headless, иначе 500мс"""
        return None if self.is_headless else 5000

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "username",
            nargs="?",
            help="Email или телефон",
        )
        parser.add_argument(
            "--password",
            "-p",
            help="Пароль для входа (если не указать, то вход будет по одноразовому коду)",
        )
        parser.add_argument(
            "--no-headless",
            action="store_true",
            help="Показать окно браузера для отладки (отключает headless режим).",
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        self._args = applicant_tool.args
        last_login_success = False
        try:
            asyncio.run(self._main(applicant_tool))
            last_login_success = True
        except (KeyboardInterrupt, asyncio.TimeoutError):
            logger.warning("Что-то пошло не так")
            os._exit(1)
        finally:
            applicant_tool.storage.settings.set_value(
                "auth.last_login", datetime.now()
            )
            applicant_tool.storage.settings.set_value(
                "auth.last_login_success", last_login_success
            )

    async def _main(self, applicant_tool: HHApplicantTool) -> None:
        args = applicant_tool.args
        api_client = applicant_tool.api_client
        storage = applicant_tool.storage
        username = (
            args.username
            or storage.settings.get_setting("auth.username")
            or (await ainput("👤 Введите email или телефон: "))
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
                headless=self.is_headless,
                args=chromium_args,
            )

            try:
                # https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/deviceDescriptorsSource.json
                android_device = pw.devices["Galaxy A55"]
                context = await browser.new_context(**android_device)
                page = await context.new_page()

                # async def route_handler(route):
                #      req = route.request
                #      url = req.url.lower()

                #      # Блокировка сканирования локальных портов
                #      if any(d in url for d in ["localhost", "127.0.0.1", "::1"]):
                #           logger.debug(f"🛑 Блокировка запроса на локальный порт: {url}")
                #           return await route.abort()

                #      # Оптимизация трафика в headless
                #      if is_headless and req.resource_type in [
                #           "image",
                #           "stylesheet",
                #           "font",
                #           "media",
                #      ]:
                #           return await route.abort()

                #      await route.continue_()

                # почему-то добавление этого обработчика вешает все
                # await page.route("**/*", route_handler)

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

                # Шаг 1: Логин
                logger.debug(f"Ожидание поля логина {self.SEL_LOGIN_INPUT}")
                await page.wait_for_selector(
                    self.SEL_LOGIN_INPUT, timeout=self.selector_timeout
                )
                await page.fill(self.SEL_LOGIN_INPUT, username)
                logger.debug("Логин введен")

                # Шаг 2: Выбор метода входа
                if args.password:
                    await self._direct_login(page, args.password)
                else:
                    await self._onetime_code_login(page)

                # Шаг 3: Ожидание OAuth кода
                logger.debug(
                    "Ожидание появления OAuth кода в трафике (таймаут 30с)..."
                )
                auth_code = await asyncio.wait_for(code_future, timeout=30.0)

                page.remove_listener("request", handle_request)

                logger.debug("Код получен, обмен на токен...")
                token = await asyncio.to_thread(
                    api_client.oauth_client.authenticate,
                    auth_code,
                )
                api_client.handle_access_token(token)

                # Сохраняем логин и пароль
                storage.settings.set_value("auth.username", username)
                if args.password:
                    storage.settings.set_value("auth.password", args.password)

                print("🔓 Авторизация прошла успешно!")

            finally:
                logger.debug("Закрытие браузера")
                await browser.close()

    async def _direct_login(self, page, password: str) -> None:
        logger.info("Вход по паролю...")
        logger.debug(
            f"Клик по кнопке развертывания пароля: {self.SEL_EXPAND_PASSWORD_BTN}"
        )
        await page.click(self.SEL_EXPAND_PASSWORD_BTN)

        logger.debug(f"Ожидание поля пароля: {self.SEL_PASSWORD_INPUT}")
        await page.wait_for_selector(
            self.SEL_PASSWORD_INPUT, timeout=self.selector_timeout
        )
        await page.fill(self.SEL_PASSWORD_INPUT, password)
        await page.press(self.SEL_PASSWORD_INPUT, "Enter")
        logger.debug("Форма с паролем отправлена")

    async def _onetime_code_login(self, page) -> None:
        logger.info("Вход по одноразовому коду...")
        await page.press(self.SEL_LOGIN_INPUT, "Enter")

        logger.debug(
            f"Ожидание контейнера ввода кода: {self.SEL_CODE_CONTAINER}"
        )
        await page.wait_for_selector(
            self.SEL_CODE_CONTAINER, timeout=self.selector_timeout
        )

        print("📨 Код был отправлен. Проверьте почту или SMS.")
        code = (await ainput("📩 Введите полученный код: ")).strip()

        if not code:
            raise RuntimeError("Код подтверждения не может быть пустым")

        logger.debug(f"Ввод кода в {self.SEL_PIN_CODE_INPUT}")
        await page.fill(self.SEL_PIN_CODE_INPUT, code)
        await page.press(self.SEL_PIN_CODE_INPUT, "Enter")
        logger.debug("Форма с кодом отправлена")

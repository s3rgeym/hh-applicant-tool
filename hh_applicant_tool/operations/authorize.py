import argparse
import asyncio
import logging
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from ..api import ApiClient
from ..main import BaseOperation, Namespace

HH_ANDROID_SCHEME = "hhandroid"

logger = logging.getLogger(__name__)


class Operation(BaseOperation):
    """Авторизация через Playwright"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "username",
            nargs="?",
            help="Email или телефон",
        )
        parser.add_argument(
            "--no-headless",
            action="store_true",
            help="Показать окно браузера для отладки (отключает headless режим).",
        )

    def run(self, args: Namespace, api_client: ApiClient, *_):
        asyncio.run(self._main(args, api_client))

    async def _main(self, args: Namespace, api_client: ApiClient):
        username_prompt = "👤 Введите email или телефон: "
        username = (
            args.username or (await asyncio.to_thread(input, username_prompt))
        ).strip()

        if not username:
            raise RuntimeError("Empty username")

        proxies = api_client.proxies
        proxy_url = proxies.get("https")

        chromium_args: list[str] = []
        if proxy_url:
            chromium_args.append(f"--proxy-server={proxy_url}")
            logger.debug("Используется proxy: %s", proxy_url)

        is_headless = not args.no_headless
        if is_headless:
            logger.info("Включен headless-режим с серверными флагами.")
            chromium_args.extend(
                [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )

        oauth_url = api_client.oauth_client.authorize_url
        logger.debug("OAuth URL: %s", oauth_url)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=is_headless,
                args=chromium_args,
            )

            try:
                context = await browser.new_context()
                page = await context.new_page()

                code_future: asyncio.Future[str | None] = asyncio.Future()

                def handle_request(request):
                    url = request.url

                    if url.startswith(f"{HH_ANDROID_SCHEME}://"):
                        logger.info("Перехвачен redirect на: %s", url)

                        if not code_future.done():
                            sp = urlsplit(url)
                            code = parse_qs(sp.query).get("code", [None])[0]
                            code_future.set_result(code)

                page.on("request", handle_request)

                logger.info("Открываем страницу авторизации")
                await page.goto(oauth_url, wait_until="load")

                await self._login_step(page, username)
                await self._code_step(page)

                logger.info("Ожидание redirect hhandroid://")

                code = await code_future  # Wait indefinitely
                page.remove_listener("request", handle_request)

                if not code:
                    logger.error("Не удалось получить код из redirect URI")
                    return

                logger.debug("OAuth code: %s", code)

                token = await asyncio.to_thread(
                    api_client.oauth_client.authenticate,
                    code,
                )
                api_client.handle_access_token(token)

                print("🔓 Авторизация прошла успешно!")

            finally:
                await browser.close()

    async def _login_step(self, page, username: str) -> None:
        logger.info("Ожидание поля ввода логина")

        login_input_selector = 'input[data-qa="login-input-username"]'

        await page.wait_for_selector(login_input_selector)

        logger.debug("Ввод username: %s", username)
        await page.fill(login_input_selector, username)

        logger.debug("Отправка формы по Enter")
        await page.press(login_input_selector, "Enter")

    async def _code_step(self, page) -> None:
        logger.info("Ожидание поля ввода кода")

        await page.wait_for_selector('div[data-qa="account-login-code-input"]')

        print("📨 Код был отправлен. Проверьте почту или SMS.")
        print()

        code_prompt = "📩 Введите полученный код: "
        code = (await asyncio.to_thread(input, code_prompt)).strip()

        if not code:
            raise RuntimeError("Empty confirmation code")

        logger.debug("Ввод кода")

        code_input_selector = 'input[data-qa="magritte-pincode-input-field"]'
        await page.focus(code_input_selector)
        await page.fill(code_input_selector, code)

        logger.debug("Подтверждаем код по Enter")
        await page.press(code_input_selector, "Enter")

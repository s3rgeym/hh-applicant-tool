from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import typing
from pathlib import Path
from datetime import datetime
from http.cookiejar import Cookie
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

from ..main import BaseOperation
from ..utils.browser_cookies import (
    find_hh_browser_profiles,
    import_browser_cookies_to_session,
)
from ..utils.terminal import print_kitty_image, print_sixel_mage
from ..utils.ui import console, err, info, ok, section, warn

if TYPE_CHECKING:
    from ..main import HHApplicantTool


HH_ANDROID_SCHEME = "hhandroid"

logger = logging.getLogger(__name__)


class Operation(BaseOperation):
    """Авторизация через Playwright"""

    __aliases__: list = ["authenticate", "auth", "login"]
    __category__: str = "Авторизация"

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
        return not self._tool.args.no_headless

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "username",
            nargs="?",
            help="Email или телефон (если не указан — будет запрошен)",
        )
        parser.add_argument(
            "--password", "-p",
            help="Пароль (если не указан — будет запрошен)",
        )
        parser.add_argument(
            "--no-headless", "-n",
            action="store_true",
            help="Показать окно браузера",
        )
        parser.add_argument(
            "--from-browser", "-b",
            action="store_true",
            help="Импортировать сессию из установленных браузеров",
        )
        parser.add_argument(
            "--new", "--add",
            action="store_true",
            help="Принудительно создать новый профиль (не показывать существующие)",
        )

    def run(self, tool: HHApplicantTool) -> int | None:
        self._tool = tool
        try:
            return asyncio.run(self._run())
        except (KeyboardInterrupt, asyncio.TimeoutError):
            warn("Авторизация отменена.")
            return 1

    async def _run(self) -> int | None:
        args = self._tool.args

        # Если --from-browser — импортируем из браузера и выходим
        if args.from_browser:
            return await self._import_from_browser()

        # Если не --new — показываем существующие профили
        if not args.new:
            chosen = await self._maybe_pick_existing_profile()
            if chosen == "DONE":
                return 0  # пользователь выбрал существующий профиль

        # Авторизуем новый профиль через Playwright
        return await self._playwright_auth()

    # ------------------------------------------------------------------ #
    #  Выбор существующего профиля                                         #
    # ------------------------------------------------------------------ #

    async def _maybe_pick_existing_profile(self) -> str | None:
        """
        Показывает список существующих профилей.
        Если пользователь выбирает существующий — загружает его токен.
        Возвращает "DONE" если профиль выбран, None если надо продолжать.
        """
        from ..main import DEFAULT_CONFIG_DIR
        from ..operations.list_profiles import _find_local_profiles

        base_dir = Path(DEFAULT_CONFIG_DIR)
        profiles = _find_local_profiles(base_dir)
        active = [(n, i) for n, i in profiles if i["has_token"]]

        # Также ищем в браузерах
        browser_profiles = find_hh_browser_profiles()

        if not active and not browser_profiles:
            return None  # нечего показывать, идём авторизовываться

        section("Существующие профили hh.ru")

        options: list[tuple[str, typing.Any]] = []

        if active:
            console.print("[hh.muted]Локальные:[/]")
            for name, pinfo in active:
                idx = len(options) + 1
                last = pinfo["last_login"] or "никогда"
                console.print(
                    f"  [hh.label]\\[{idx}][/] [hh.profile]{name}[/]"
                    f"  [hh.dim](последний вход: {last})[/]"
                )
                options.append(("local", name))

        if browser_profiles:
            console.print("\n[hh.muted]Из браузеров:[/]")
            for bp in browser_profiles:
                idx = len(options) + 1
                console.print(
                    f"  [hh.label]\\[{idx}][/] [bold]{bp.browser}[/]"
                    f" — [hh.id]{bp.username}[/]"
                )
                options.append(("browser", bp))

        new_idx = len(options) + 1
        console.print(
            f"\n  [hh.label]\\[{new_idx}][/] Добавить новый профиль"
            f"\n  [hh.muted]\\[0][/]  Отмена\n"
        )

        while True:
            raw = await asyncio.to_thread(
                input, f"Выберите [0-{new_idx}]: "
            )
            raw = raw.strip()
            if raw == "0":
                return "DONE"
            if raw.isdigit() and 1 <= int(raw) <= new_idx:
                choice_idx = int(raw) - 1
                if choice_idx == len(options):
                    # "Добавить новый"
                    return None
                kind, payload = options[choice_idx]
                if kind == "local":
                    ok(f"Профиль '{payload}' уже авторизован.")
                    info(
                        f"Используйте: hh-applicant-tool --profile-id {payload} <команда>"
                    )
                    return "DONE"
                elif kind == "browser":
                    return await self._use_browser_profile(payload)
            warn("Введите число из списка.")

    async def _use_browser_profile(self, bp) -> str:
        """Импортирует куки из выбранного браузерного профиля."""
        info(f"Импортирую сессию из {bp.browser}...")
        count = import_browser_cookies_to_session(
            self._tool.session.cookies, bp.cookies
        )
        info(f"Импортировано {count} куки.")
        self._tool.save_cookies()

        result = await self._try_oauth_with_existing_session()
        if result:
            ok("Токен получен. Профиль активен.")
            self._tool.storage.settings.set_value(
                "auth.last_login", str(datetime.now())
            )
            return "DONE"
        else:
            warn("Не удалось получить токен через браузерную сессию. Попробуем обычную авторизацию...")
            return None

    async def _try_oauth_with_existing_session(self) -> bool:
        """Пытается получить OAuth code используя уже авторизованную сессию hh."""
        try:
            api_client = self._tool.api_client
            oauth_url = api_client.oauth_client.authorize_url

            # Делаем GET запрос к OAuth URL — если куки валидны,
            # hh.ru сразу редиректит на hhandroid:// без ввода логина
            resp = self._tool.session.get(
                oauth_url, allow_redirects=False, timeout=15
            )
            location = resp.headers.get("Location", "")
            if location.startswith(f"{HH_ANDROID_SCHEME}://"):
                code = parse_qs(urlsplit(location).query).get("code", [None])[0]
                if code:
                    token = await asyncio.to_thread(
                        api_client.oauth_client.authenticate, code
                    )
                    api_client.handle_access_token(token)
                    return True
        except Exception as e:
            logger.debug("OAuth через сессию не удался: %s", e)
        return False

    # ------------------------------------------------------------------ #
    #  Импорт из браузера (--from-browser)                                 #
    # ------------------------------------------------------------------ #

    async def _import_from_browser(self) -> int:
        profiles = find_hh_browser_profiles()
        if not profiles:
            err("Активных сессий hh.ru в браузерах не найдено.")
            try:
                import rookiepy  # noqa: F401
            except ImportError:
                warn("rookiepy не установлен: [bold]pip install rookiepy[/]")
            return 1

        if len(profiles) == 1:
            bp = profiles[0]
            info(f"Найдена сессия: {bp}")
        else:
            section("Браузерные сессии")
            for i, bp in enumerate(profiles, 1):
                console.print(
                    f"  [hh.label]\\[{i}][/] [bold]{bp.browser}[/]"
                    f" — [hh.id]{bp.username}[/]"
                )
            console.print()
            while True:
                raw = (
                    await asyncio.to_thread(
                        input, f"Выберите [1-{len(profiles)}]: "
                    )
                ).strip()
                if raw.isdigit() and 1 <= int(raw) <= len(profiles):
                    bp = profiles[int(raw) - 1]
                    break
                warn("Некорректный ввод.")

        count = import_browser_cookies_to_session(
            self._tool.session.cookies, bp.cookies
        )
        info(f"Импортировано {count} куки из {bp.browser}.")
        self._tool.save_cookies()

        result = await self._try_oauth_with_existing_session()
        if result:
            self._tool.storage.settings.set_value(
                "auth.last_login", str(datetime.now())
            )
            ok("Авторизация через браузерные куки прошла успешно!")
            return 0
        else:
            err("Не удалось получить токен. Сессия истекла или требует повторного входа.")
            info("Запустите: hh-applicant-tool authorize")
            return 1

    # ------------------------------------------------------------------ #
    #  Playwright авторизация                                              #
    # ------------------------------------------------------------------ #

    async def _playwright_auth(self) -> int:
        if not _PLAYWRIGHT_AVAILABLE:
            err("Playwright не установлен.")
            info(
                "Установите его командой:\n\n"
                "  hh-applicant-tool install\n\n"
                "или вручную:\n\n"
                "  pip install playwright && playwright install chromium"
            )
            return 1

        args = self._tool.args
        api_client = self._tool.api_client
        storage = self._tool.storage

        # Получаем логин
        username = (
            args.username
            or storage.settings.get_value("auth.username")
            or (
                await asyncio.to_thread(input, "Email или телефон: ")
            ).strip()
        )
        if not username:
            err("Логин не может быть пустым.")
            return 1

        # Получаем пароль
        password = args.password or storage.settings.get_value("auth.password")
        if not password:
            password = await asyncio.to_thread(
                getpass.getpass, "Пароль (Enter — войти по коду): "
            )

        logger.debug("Авторизация для: %s", username)

        proxies = api_client.proxies
        proxy_url = proxies.get("https")
        chromium_args: list[str] = []
        if proxy_url:
            chromium_args.append(f"--proxy-server={proxy_url}")

        async with async_playwright() as pw:
            logger.debug("Запуск браузера...")
            browser = await pw.chromium.launch(
                headless=self.is_headless,
                args=chromium_args,
            )
            try:
                android_device = pw.devices["Galaxy A55"]
                context = await browser.new_context(**android_device)
                page = await context.new_page()

                code_future: asyncio.Future[str | None] = asyncio.Future()

                def handle_request(request):
                    url = request.url
                    if url.startswith(f"{HH_ANDROID_SCHEME}://"):
                        logger.info("OAuth redirect: %s", url)
                        if not code_future.done():
                            sp = urlsplit(url)
                            code = parse_qs(sp.query).get("code", [None])[0]
                            code_future.set_result(code)

                page.on("request", handle_request)

                await page.goto(
                    api_client.oauth_client.authorize_url,
                    timeout=30000,
                    wait_until="load",
                )

                await page.wait_for_selector(self.SEL_LOGIN_INPUT, timeout=10000)
                await page.fill(self.SEL_LOGIN_INPUT, username)

                if password:
                    await self._direct_login(page, password)
                else:
                    await self._onetime_code_login(page)

                info("Ожидаю подтверждения...")
                auth_code = await asyncio.wait_for(code_future, timeout=120.0)

                page.remove_listener("request", handle_request)

                token = await asyncio.to_thread(
                    api_client.oauth_client.authenticate, auth_code
                )
                api_client.handle_access_token(token)

                ok("Авторизация прошла успешно!")

                storage.settings.set_value("auth.username", username)
                if args.password:
                    storage.settings.set_value("auth.password", args.password)
                storage.settings.set_value(
                    "auth.last_login", str(datetime.now())
                )

                cookies = await context.cookies()
                self._set_session_cookies(cookies)

            finally:
                await browser.close()

        return 0

    # ------------------------------------------------------------------ #
    #  Методы входа                                                        #
    # ------------------------------------------------------------------ #

    async def _direct_login(self, page, password: str) -> None:
        logger.info("Вход по паролю...")
        await page.click(self.SEL_EXPAND_PASSWORD)
        await self._handle_captcha(page)
        await page.wait_for_selector(self.SEL_PASSWORD_INPUT, timeout=10000)
        await page.fill(self.SEL_PASSWORD_INPUT, password)
        await page.press(self.SEL_PASSWORD_INPUT, "Enter")

    async def _onetime_code_login(self, page) -> None:
        logger.info("Вход по одноразовому коду...")
        await page.press(self.SEL_LOGIN_INPUT, "Enter")
        await self._handle_captcha(page)
        await page.wait_for_selector(self.SEL_CODE_CONTAINER, timeout=15000)

        info("Код отправлен на почту или телефон.")
        code = (
            await asyncio.to_thread(input, "Введите код: ")
        ).strip()
        if not code:
            raise RuntimeError("Код не может быть пустым.")

        await page.fill(self.SEL_PIN_CODE_INPUT, code)
        await page.press(self.SEL_PIN_CODE_INPUT, "Enter")

    async def _handle_captcha(self, page) -> None:
        try:
            captcha_element = await page.wait_for_selector(
                self.SEL_CAPTCHA_IMAGE,
                timeout=5000,
                state="visible",
            )
        except Exception:
            logger.debug("Капчи нет, продолжаем.")
            return

        img_bytes = await captcha_element.screenshot()
        warn("Требуется ввод капчи.")

        # Автодетект формата терминала
        displayed = False
        term = os.environ.get("TERM", "") + os.environ.get("TERM_PROGRAM", "")
        if "kitty" in term.lower():
            try:
                print_kitty_image(img_bytes)
                displayed = True
            except Exception:
                pass
        if not displayed:
            try:
                print_sixel_mage(img_bytes)
                displayed = True
            except Exception:
                pass
        if not displayed:
            # Сохраняем в файл как fallback
            captcha_path = self._tool.config_path / "captcha.png"
            captcha_path.write_bytes(img_bytes)
            info(f"Капча сохранена в файл: {captcha_path}")

        captcha_text = (
            await asyncio.to_thread(input, "Введите текст с картинки: ")
        ).strip()
        await page.fill(self.SEL_CAPTCHA_INPUT, captcha_text)
        await page.press(self.SEL_CAPTCHA_INPUT, "Enter")

    # ------------------------------------------------------------------ #
    #  Утилиты                                                             #
    # ------------------------------------------------------------------ #

    def _set_session_cookies(
        self, cookies: list[dict[str, typing.Any]]
    ) -> None:
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

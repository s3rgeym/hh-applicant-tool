from __future__ import annotations

import logging
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

HH_DOMAINS = [".hh.ru", ".hh.kz", ".hh.uz", ".hh.ua", ".hh.by"]

# Браузеры в порядке приоритета попытки
BROWSER_LOADERS: list[tuple[str, str]] = [
    ("Chrome", "chrome"),
    ("Firefox", "firefox"),
    ("Brave", "brave"),
    ("Edge", "edge"),
    ("Chromium", "chromium"),
    ("Opera", "opera"),
    ("Safari", "safari"),
    ("Arc", "arc"),
    ("LibreWolf", "librewolf"),
    ("Vivaldi", "vivaldi"),
]


@dataclass
class BrowserProfile:
    """Профиль hh.ru, найденный в браузере."""

    browser: str
    username: str  # значение hhuid или email из куки
    cookie_count: int
    cookies: list[dict]

    def __str__(self) -> str:
        return f"{self.browser} — {self.username} ({self.cookie_count} куки)"


def _rookiepy_available() -> bool:
    try:
        import rookiepy  # noqa: F401

        return True
    except ImportError:
        return False


def find_hh_browser_profiles() -> list[BrowserProfile]:
    """
    Сканирует установленные браузеры и возвращает профили с куками hh.ru.
    Требует rookiepy.
    """
    if not _rookiepy_available():
        logger.debug("rookiepy не установлен, пропускаем импорт из браузеров")
        return []

    import rookiepy

    profiles: list[BrowserProfile] = []

    for browser_name, func_name in BROWSER_LOADERS:
        loader = getattr(rookiepy, func_name, None)
        if loader is None:
            continue
        try:
            cookies = loader(domains=[".hh.ru"])
            if not cookies:
                continue
            # Ищем hhuid как идентификатор пользователя
            hhuid = next(
                (c["value"] for c in cookies if c["name"] == "hhuid"), None
            )
            # Ищем hhtoken — признак что пользователь залогинен
            has_token = any(
                c["name"] in ("hhtoken", "crypted_id") for c in cookies
            )
            if not has_token:
                logger.debug(
                    "%s: куки hh.ru есть, но сессия не активна (нет hhtoken)",
                    browser_name,
                )
                continue
            username = hhuid or f"пользователь #{len(profiles) + 1}"
            profiles.append(
                BrowserProfile(
                    browser=browser_name,
                    username=username,
                    cookie_count=len(cookies),
                    cookies=cookies,
                )
            )
            logger.debug("%s: найден профиль %s", browser_name, username)
        except Exception as e:
            logger.debug("Ошибка при чтении куки из %s: %s", browser_name, e)

    return profiles


def browser_cookies_to_cookiejar(
    cookies: list[dict],
) -> CookieJar:
    """Конвертирует список куки rookiepy в стандартный CookieJar."""
    import rookiepy

    return rookiepy.to_cookiejar(cookies)


def import_browser_cookies_to_session(
    session_cookies: CookieJar,
    browser_cookies: list[dict],
) -> int:
    """
    Импортирует куки из браузера в сессию requests.
    Возвращает количество импортированных куки.
    """
    count = 0
    for c in browser_cookies:
        domain = c.get("domain", "")
        if not any(domain.endswith(hh.lstrip(".")) for hh in HH_DOMAINS):
            continue
        expires_raw = c.get("expires", 0) or 0
        # rookiepy возвращает expires в миллисекундах у Firefox
        # и в секундах у Chrome — нормализуем
        if expires_raw > 1e10:
            expires_raw = int(expires_raw / 1000)
        cookie = Cookie(
            version=0,
            name=c["name"],
            value=c["value"],
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith("."),
            path=c.get("path", "/"),
            path_specified=True,
            secure=c.get("secure", False),
            expires=int(expires_raw),
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": str(c.get("http_only", False))},
            rfc2109=False,
        )
        session_cookies.set_cookie(cookie)
        count += 1
    return count

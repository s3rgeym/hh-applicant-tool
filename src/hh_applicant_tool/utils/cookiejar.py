import re
from collections.abc import Iterable
from http.cookiejar import Cookie, MozillaCookieJar
from typing import Any

from ..constants import SITE_LANGUAGE_COOKIE, SITE_LANGUAGE_COOKIE_DOMAIN


class HHOnlyCookieJar(MozillaCookieJar):
    """Хранилище, которое сохраняет куки только с хх"""

    def set_cookie(self, cookie: Cookie):
        # Регулярное выражение для проверки доменов hh.ru, hh.kz, hh.uz и т.д.
        pattern = r"^(?!israel\.)(?:.*?\.)?hh\.(ru|kz|uz|by|net|com)\.?$"

        if re.search(pattern, cookie.domain):
            super().set_cookie(cookie)

    # def save(
    #     self,
    #     filename: str | None = None,
    #     ignore_discard: bool = False,
    #     ignore_expires: bool = False,
    # ) -> None:
    #     return super(MozillaCookieJar).save(
    #         filename, ignore_discard, ignore_expires
    #     )

    def set_site_language(self, language: str) -> bool:
        """Выставляет язык сайта hh.ru (кука session_language).

        Язык картинки капчи hh.ru берет именно из этой куки, и он
        фиксируется в момент выдачи captcha_url (403 на запрос отклика),
        а не при разгадывании. Поэтому куку нужно иметь в сессии заранее,
        иначе задание придет кириллицей.

        Домен ставим с ведущей точкой, чтобы кука уезжала и на hh.ru,
        и на api.hh.ru, где ходит отклик.
        """
        self.set_cookie(
            Cookie(
                version=0,
                name=SITE_LANGUAGE_COOKIE,
                value=language,
                port=None,
                port_specified=False,
                domain=SITE_LANGUAGE_COOKIE_DOMAIN,
                domain_specified=True,
                domain_initial_dot=True,
                path="/",
                path_specified=True,
                secure=False,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )

        # Зачем эта проверка?
        return any(
            cookie.name == SITE_LANGUAGE_COOKIE and cookie.value == language
            for cookie in self
        )

    def cookies_to_playwright(self) -> list[dict[str, Any]]:
        """Куки из http.cookiejar в формате playwright (context.add_cookies).

        Нужно, чтобы браузер работал с той же сессией hh.ru, что и requests,
        иначе куки, полученные в браузере, ничего не решают.
        """
        rv: list[dict[str, Any]] = []

        for cookie in self:
            # В http.cookiejar cookie.domain уже хранится с ведущей точкой
            # для доменных кук (".hh.ru"), а playwright ждет ровно одну,
            # иначе он отвергает весь add_cookies с Invalid cookie fields
            domain = (cookie.domain or "").strip(".")
            if not domain:
                continue
            rv.append(
                {
                    "name": cookie.name,
                    "value": cookie.value or "",
                    "domain": (
                        f".{domain}" if cookie.domain_initial_dot else domain
                    ),
                    "path": cookie.path or "/",
                    # playwright ждет -1 для сессионных кук
                    "expires": int(cookie.expires) if cookie.expires else -1,
                    # MozillaCookieJar хранит HttpOnly как флаг в rest
                    "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
                    "secure": bool(cookie.secure),
                }
            )

        return rv

    def set_cookies_from_playwright(
        self,
        cookies: Iterable[dict[str, Any]],
    ) -> int:
        """Кладёт куки из playwright (словари) в обычный http.cookiejar.

        У jar из requests есть requests.Cookies.set(), но у http.cookiejar
        есть только set_cookie(), поэтому конвертируем руками.

        Возвращает количество разобранных кук (сколько из них реально
        попало в jar, решает уже сам jar, например HHOnlyCookieJar
        выкидывает все домены, кроме hh).
        """
        parsed = 0

        for raw in cookies:
            name, value = raw.get("name"), raw.get("value")
            domain = str(raw.get("domain") or "")
            if not name or value is None or not domain:
                continue
            path = raw.get("path") or "/"
            expires = raw.get("expires")
            # playwright отдает -1 для сессионных кук, а requests считает
            # такие куки протухшими и не отправляет их вообще
            expires = int(expires) if expires and int(expires) > 0 else None
            # Ведущую точку в domain сохраняем: MozillaCookieJar пишет
            # ее в файл, и без нее доменная кука hh.ru после
            # перезагрузки перестает уезжать на поддомены вроде api.hh.ru
            self.set_cookie(
                Cookie(
                    version=0,
                    name=name,
                    value=str(value),
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=domain.startswith("."),
                    domain_initial_dot=domain.startswith("."),
                    path=path,
                    path_specified=True,
                    secure=bool(raw.get("secure")),
                    expires=expires,
                    discard=expires is None,
                    comment=None,
                    comment_url=None,
                    rest={"HttpOnly": ""} if raw.get("httpOnly") else {},
                    rfc2109=False,
                )
            )
            parsed += 1

        return parsed

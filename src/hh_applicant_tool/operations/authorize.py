from __future__ import annotations

import argparse
import base64
import json
import logging
import random
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urljoin, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..errors import OperationError, XHRError
from ..tool import BaseOperation

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger(__name__.split(".")[0])

# Заголовки, специфичные для POS
_LOGIN_HEADERS = {
    "X-Hhtmfrom": "",
    "X-Hhtmsource": "account_login",
}


class OtpConfirmError(Exception):
    """Не удалось подтвердить OTP-код. Внутренняя, наружу превращается в OperationError."""


class Operation(BaseOperation):
    """Авторизация на сайте и через мобильное приложение. Ранее введенный логин и пароль запоминаются и будут использованы, если не указать их."""

    __aliases__: list = ["authenticate", "auth", "login"]

    # Состояние текущей авторизации, заполняется в run()
    tool: HHApplicantTool
    username: str
    password: str | None
    is_email: bool
    redirect_url: str
    xsrf: str
    pubkey: str

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("username", nargs="?", help="Email или телефон")
        parser.add_argument("password", nargs="?", help="Пароль")

    def run(self, tool: HHApplicantTool, args) -> int | None:
        self.tool = tool
        api_client = tool.api_client
        session = tool.session

        username = (
            args.username or input("👤 Введите email или телефон: ")
        ).strip()
        if not username:
            raise OperationError("Empty username")
        logger.debug("authenticate with: %s", username)

        # Пароль необязателен: если его нет, авторизуемся по одноразовому коду
        password = args.password

        self.is_email = "@" in username
        if not self.is_email:
            username = self._normalize_phone_number(username)

        self.tool = tool

        # https://api.hh.ru/openapi/redoc#section/Avtorizaciya/Zapros-avtorizacii-pod-drugim-polzovatelem
        # Если аккаунт еще и как работодатель может войти, то по умолчанию перекидывает на авторизацию
        # в качестве employer
        authorize_url = api_client.oauth_client.authorize_url(
            force_login="true",
            role="applicant",
            force_role="true",
            skip_choose_account="true",
        )
        logger.info(
            f"Эту ссылку можно открыть в браузере для изучения процесса авторизации: {authorize_url}"
        )
        # Переход на страницу нужен для установки cookie xsrf_token
        r = session.get(authorize_url)
        self._log_response(r)
        self.redirect_url = r.url
        logger.debug(self.redirect_url)

        backurl = parse_qs(urlsplit(self.redirect_url).query)["backurl"][0]

        data = tool.parse_initial_state(r)

        xsrf = data["xsrfToken"]

        # На всякий случай проверим, что значение из cookie совпадает с тем, что на странице
        assert xsrf == tool.xsrf_token

        self.pubkey = data["loginTrustFlagsSecret"]
        logger.debug("Публичный ключ для подписи запроса:\n%s", self.pubkey)

        time.sleep(random.uniform(5.0, 10.0))

        # Капчу при входе решает и повторяет запрос сам xhr_request.
        # Любая другая ошибка запроса прерывает авторизацию.
        try:
            # Вход по паролю или запрос OTP-кода
            self.login(username, password)

            # По паролю мы уже вошли, а для OTP нужно еще ввести полученный код
            if not password:
                self._confirm_otp(username)
        except XHRError as ex:
            raise OperationError(
                f"Ошибка запроса при авторизации: {ex}"
            ) from ex
        except OtpConfirmError as ex:
            raise OperationError(str(ex)) from ex

        # Теперь нужно проверить заголовки
        r = session.get(
            urljoin(self.redirect_url, backurl),
            headers={"Referer": self.redirect_url},
            allow_redirects=False,
        )

        if r.status_code != 302 or not (location := r.headers.get("location")):
            raise OperationError(
                "Ответ не вляется редиректом или не содержит заголовка Location!"
            )

        sp = urlsplit(location)
        logger.debug(sp)

        if sp.scheme != "hhandroid" or sp.netloc != "oauthresponse":
            raise OperationError(
                f"Неправильный формат URI для получения кода авторизации: {location}"
            )

        auth_code = parse_qs(sp.query)["code"][0]

        # 5. Обмен кода на токен
        token = api_client.oauth_client.authenticate(auth_code)
        api_client.handle_access_token(token)
        # Куки уже лежат в tool.session — копировать ничего не нужно.
        print("🎉 Авторизация прошла успешно!")

    def login(self, username: str, password: str | None = None) -> None:
        """Одна попытка входа.

        С паролем — вход по логину и паролю, без пароля — запрос OTP-кода.
        Бросает OperationError, если вход невозможен.
        """
        if password:
            self._login_by_password(username, password)
        else:
            self._request_otp(username)

    @staticmethod
    def _log_response(r) -> None:
        logger.debug(f"{r.request.method} {r.url} {r.status_code}")

    @staticmethod
    def _check_no_captcha(res: dict[str, Any]) -> None:
        if (res.get("hhcaptcha") or {}).get("captchaState"):
            raise OperationError("Сервер вернул капчу в ответе!!!")

    def _login_by_password(self, username: str, password: str) -> None:
        """Вход по паролю.

        После успеха в tool.session лежат авторизационные cookie, чтобы
        run() мог пройти редирект на hhandroid://oauthresponse.
        """
        # Шлем на тот же URL страницы логина, в failUrl — он же без хоста
        sp = urlsplit(self.redirect_url)
        fail_url = f"{sp.path}?{sp.query}"

        params = {
            "accountType": "APPLICANT",
            "failUrl": fail_url,
            "remember": "true",
            # Пароль был предложен менеджером паролей
            # А юзернейм типа из LocalStorage
            "loginTrustFlags": self._login_trust_flags(
                {"password": {"suggest": True, "paste": False}}
            ),
            "username": username,
            "password": password,
            # Браузер всегда шлет это поле, при капче его перезапишет xhr_request
            "captchaText": "",
        }
        logger.debug("password login params: %r", {**params, "password": "***"})

        res = self.tool.xhr_request(
            "POST",
            self.redirect_url,
            data=params,
            referer_url=self.redirect_url,
            additional_headers=_LOGIN_HEADERS,
        )

        logger.debug("response keys: %s", list(res))

        if login_error := res.get("loginError"):
            code = login_error.get("code", "unknown")
            raise OperationError(f"Ошибка авторизации: {code}")

        self._check_no_captcha(res)
        # TODO: следующие запросы

    def _request_otp(self, username: str) -> None:
        """Запрос OTP-кода (SMS/Email)."""
        params = {
            "login": username,
            "otpType": ["phone", "email"][self.is_email],
            "operationType": "applicant_otp_auth",
            "authScenario": "APPLICANT_AUTH",
            "formatPhone": "true",
            "isSignupPage": "false",
            # Данные подставлены менеджером паролей
            "loginTrustFlags": self._login_trust_flags(
                {"emailOrPhone": {"paste": False, "suggest": True}}
            ),
            # Браузер всегда шлет это поле, при капче его перезапишет xhr_request
            "captchaText": "",
        }

        logger.debug("otp generate params: %r", params)
        res = self.tool.xhr_request(
            "POST",
            urljoin(self.redirect_url, "/account/otp_generate"),
            data=params,
            referer_url=self.redirect_url,
            additional_headers=_LOGIN_HEADERS,
        )
        logger.debug(res)

        if res.get("success"):
            logger.info("Код авторизации был выслан!")
            return

        self._check_no_captcha(res)
        raise OperationError("Неправильный запрос!")

    def _confirm_otp(self, username) -> None:
        """Ввод кода из SMS/Email и подтверждение входа."""
        code_from = ["SMS", "Email"][self.is_email]
        code_icon = ["📱", "📧"][self.is_email]
        code = input(
            f"{code_icon} Введите полученный код из {code_from}: "
        ).strip()

        if not code:
            raise OtpConfirmError("Код подтверждения не может быть пустым.")

        params = {
            "username": username,
            "code": code,
            "backurl": self.redirect_url,
            "operationType": "applicant_otp_auth",
            "isApplicantSignup": "false",
            "remember": "true",
            # Не знаю от чего их вычислять и нужны ли они тут
            "loginTrustFlags": self._login_trust_flags(),
            "authScenario": "APPLICANT_AUTH",
        }

        res = self.tool.xhr_request(
            "POST",
            urljoin(self.redirect_url, "/account/login/by_code"),
            data=params,
            referer_url=self.redirect_url,
            additional_headers=_LOGIN_HEADERS,
        )

        logger.debug(
            "by_code response: keys=%s success=%s error=%s",
            list(res),
            res.get("success"),
            res.get("error"),
        )

        if not res.get("success"):
            error_key = res.get("error", {}).get("key", "UNKNOWN_ERROR")
            raise OtpConfirmError(f"Ошибка авторизации: {error_key}")

        if not res.get("verification", {}).get("success"):
            raise OtpConfirmError("Верификация не пройдена!")

    @staticmethod
    def _normalize_phone_number(phone: str) -> str:
        # Удаляем всякий мусор типа (, ) и -
        phone = re.sub(r"\D", "", phone)
        if len(phone) == 11 and phone[0] == "8":
            phone = "7" + phone[1:]
        return phone

    def _login_trust_flags(self, payload: dict[str, Any] | None = None) -> str:
        payload = {
            **(payload or {}),
            # Временная метка при шифровании на фронте устанавливается принудительно
            "ts": int(time.time() * 1000),
        }
        logger.debug(
            "Данные для кодирования в JSON и шифрования публичным ключом: %r",
            payload,
        )
        # JSON.stringify -> компактный вывод, без пробелов
        plaintext = json.dumps(payload, separators=(",", ":")).encode()
        public_key = serialization.load_pem_public_key(self.pubkey.encode())
        ciphertext = public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode()

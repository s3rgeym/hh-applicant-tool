from __future__ import annotations

import argparse
import base64
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urljoin, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..tool import BaseOperation, OperationError

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


MAX_RETRIES = 10

logger = logging.getLogger("hh-applicant-tool")


@dataclass
class LoginResult:
    """Результат одной попытки входа (логин+пароль или запрос OTP-кода)."""

    # Попытка прошла без ошибок и капчи
    success: bool = False
    # Текст ошибки, если вход невозможен и капча не поможет
    error_message: str | None = None
    # Состояние капчи, если ее нужно решить перед повтором
    captcha_state: str | None = None
    # Предыдущая капча была введена неверно
    captcha_error: bool = False


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
        api_client = tool.api_client
        storage = tool.storage
        session = tool.session

        username = (
            args.username
            or storage.settings.get_value("auth.username")
            or input("👤 Введите email или телефон: ")
        ).strip()
        if not username:
            raise OperationError("Empty username")
        logger.debug("authenticate with: %s", username)

        # Пароль необязателен: если его нет, авторизуемся по одноразовому коду
        self.password = args.password or storage.settings.get_value(
            "auth.password"
        )

        self.is_email = "@" in username
        if not self.is_email:
            username = self._normalize_phone_number(username)

        self.tool = tool
        self.username = username

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

        self.xsrf = data["xsrfToken"]

        # На всякий случай проверим, что значение из cookie совпадает с тем, что на странице
        assert self.xsrf == tool.xsrf_token

        self.pubkey = data["loginTrustFlagsSecret"]

        # Вход по паролю или запрос OTP-кода, с повторами при капче
        captcha: dict[str, Any] = {}
        tries = 0

        while True:
            time.sleep(random.uniform(3.0, 5.0))

            result = self.login(username, self.password, **captcha)

            if result.success:
                break

            if not result.captcha_state:
                raise OperationError(
                    result.error_message or "Не удалось авторизоваться!"
                )

            if result.captcha_error:
                logger.warning("Капча была введена неверно!")

            tries += 1
            if tries >= MAX_RETRIES:
                raise OperationError("Исчерпано количество неверных попыток!")

            solution = tool.solve_captcha(
                captcha_state=result.captcha_state,
                referer_url=self.redirect_url,
            )

            captcha = {
                "captcha_text": solution.text,
                "captcha_key": solution.key,
                "captcha_state": solution.state,
            }

        # По паролю мы уже вошли, а для OTP нужно еще ввести полученный код
        if not self.password:
            try:
                self._confirm_otp()
            except OtpConfirmError as ex:
                raise OperationError(str(ex)) from ex

        # Теперь нужно проверить заголовки
        r = session.get(
            urljoin(self.redirect_url, backurl),
            headers={"Referer": self.redirect_url},
            allow_redirects=False,
        )

        self._log_response(r)

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
        storage.settings.set_value("auth.username", username)
        storage.settings.set_value("auth.last_login", datetime.now())
        # Куки уже лежат в tool.session — копировать ничего не нужно.
        print("🎉 Авторизация прошла успешно!")

    def login(
        self,
        username: str,
        password: str | None = None,
        *,
        captcha_text: str = "",
        captcha_key: str | None = None,
        captcha_state: str | None = None,
    ) -> LoginResult:
        """Одна попытка входа.

        С паролем — вход по логину и паролю, без пароля — запрос OTP-кода.
        Ничего не бросает на ожидаемых ответах сервера: о капче и ошибках
        сообщает через LoginResult.
        """
        captcha = {"captchaText": captcha_text}
        if captcha_key is not None:
            captcha["captchaKey"] = captcha_key
        if captcha_state is not None:
            captcha["captchaState"] = captcha_state

        if password:
            return self._login_by_password(username, password, captcha)
        return self._request_otp(username, captcha)

    @staticmethod
    def _log_response(r) -> None:
        # r.url и r.request.url у финального ответа совпадают, а вот
        # промежуточные редиректы лежат в r.history, их и выводим отдельно
        for h in r.history:
            logger.debug(
                f"{h.request.method} {h.url} {h.status_code} "
                f"-> {h.headers.get('location')}"
            )
        logger.debug(f"{r.request.method} {r.url} {r.status_code}")

    def _login_headers(self) -> dict[str, str]:
        # Эти заголовки у всех POST-запросов при авторизации (и по паролю, и по OTP)
        # У них referer не отличается, но наврядли его кто проверяет
        return {
            "Accept": "application/json",
            "X-Hhtmfrom": "",
            "X-Hhtmsource": "account_login",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": self.xsrf,
            "Referer": self.redirect_url,
        }

    def _login_by_password(
        self,
        username: str,
        password: str,
        captcha: dict[str, str],
    ) -> LoginResult:
        """Вход по паролю.

        После успеха в tool.session лежат авторизационные cookie, чтобы
        run() мог пройти редирект на hhandroid://oauthresponse.
        """
        # Шлем на тот же URL страницы логина, в failUrl — он же без хоста
        sp = urlsplit(self.redirect_url)
        fail_url = f"{sp.path}?{sp.query}" if sp.query else sp.path

        params = {
            "accountType": "APPLICANT",
            "failUrl": fail_url,
            "remember": "true",
            "loginTrustFlags": self._login_trust_flags(),
            "username": username,
            "password": password,
            **captcha,
        }
        logger.debug("password login params: %r", {**params, "password": "***"})

        r = self.tool.session.post(
            self.redirect_url,
            files={k: (None, v) for k, v in params.items()},
            headers=self._login_headers(),
        )
        self._log_response(r)

        res = r.json()
        logger.debug("response keys: %s", list(res))

        if login_error := res.get("loginError"):
            code = login_error.get("code", "unknown")
            message = login_error.get("trl", "")
            return LoginResult(
                error_message=f"Ошибка авторизации: {code}. {message}".strip()
            )

        hhcaptcha = res.get("hhcaptcha") or {}

        # hhcaptcha.get("isBot") == True
        if not hhcaptcha.get("captchaState"):
            # TODO: следующие запросы
            return LoginResult(success=True)

        return LoginResult(
            captcha_state=hhcaptcha["captchaState"],
            captcha_error=bool(hhcaptcha.get("captchaError")),
        )

    def _request_otp(
        self,
        username: str,
        captcha: dict[str, str],
    ) -> LoginResult:
        """Запрос OTP-кода (SMS/Email)."""
        params = {
            "login": username,
            "otpType": ["phone", "email"][self.is_email],
            "operationType": "applicant_otp_auth",
            "authScenario": "APPLICANT_AUTH",
            "formatPhone": "true",
            "isSignupPage": "false",
            "loginTrustFlags": self._login_trust_flags(),
            **captcha,
        }

        otp_url = urljoin(self.redirect_url, "/account/otp_generate")
        headers = self._login_headers()

        logger.debug("otp generate params: %r | headers: %r", params, headers)
        r = self.tool.session.post(
            otp_url,
            # Просто как образец отправки force multipart
            files={k: (None, v) for k, v in params.items()},
            headers=headers,
        )
        self._log_response(r)

        res = r.json()

        if res.get("success"):
            logger.info("Код авторизации был выслан!")
            return LoginResult(success=True)

        # logger.debug(res)
        hhcaptcha = res.get("hhcaptcha") or {}

        if "captchaState" not in hhcaptcha:
            return LoginResult(error_message="Неправильный запрос!")

        # isBot еще интересное значение
        return LoginResult(
            captcha_state=hhcaptcha["captchaState"],
            captcha_error=bool(hhcaptcha.get("captchaError")),
        )

    def _confirm_otp(self) -> None:
        """Ввод кода из SMS/Email и подтверждение входа."""
        code_from = ["SMS", "Email"][self.is_email]
        code_icon = ["📱", "📧"][self.is_email]
        code = input(
            f"{code_icon} Введите полученный код из {code_from}: "
        ).strip()

        if not code:
            raise OtpConfirmError("Код подтверждения не может быть пустым.")

        params = {
            "username": self.username,
            "code": code,
            "backurl": self.redirect_url,
            "operationType": "applicant_otp_auth",
            "isApplicantSignup": "false",
            "remember": "true",
            # Не знаю от чего их вычислять и нужны ли они тут
            "loginTrustFlags": self._login_trust_flags(),
            "authScenario": "APPLICANT_AUTH",
        }

        by_code_url = urljoin(self.redirect_url, "/account/login/by_code")
        r = self.tool.session.post(
            by_code_url,
            data=params,
            headers=self._login_headers(),
        )

        self._log_response(r)

        res = r.json()
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
        logger.debug("trust login data: %r", payload)
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

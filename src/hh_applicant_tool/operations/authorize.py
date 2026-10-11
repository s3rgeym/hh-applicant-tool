from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..tool import BaseOperation, OperationError

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger(__name__.split(".")[0])


class Operation(BaseOperation):
    """Авторизация на сайте и через мобильное приложение"""

    __aliases__: list = ["authenticate", "auth", "login"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("username", nargs="?", help="Email или телефон")

    def run(self, tool: HHApplicantTool, args) -> int | None:
        self._tool = tool
        self._args = args
        try:
            self._run()
        except KeyboardInterrupt:
            logger.warning("Операция прервана пользователем")
            return 1
        return 0

    def _run(self) -> None:
        tool = self._tool
        args = self._args
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

        is_email = "@" in username
        if not is_email:
            username = self._normalize_phone_number(username)

        # https://api.hh.ru/openapi/redoc#section/Avtorizaciya/Zapros-avtorizacii-pod-drugim-polzovatelem
        authorize_url = api_client.oauth_client.authorize_url(
            force_login="true",
            role="applicant",
            force_role="true",
            skip_choose_account="true",
        )
        logger.debug(f"{authorize_url=}")
        # 1. Страница авторизации -> xsrf и публичный ключ
        r = session.get(authorize_url)
        # Если куки не протушли, то авторизация не пройдет

        redirect_url = r.url
        logger.debug(redirect_url)

        data = tool.parse_initial_state(r)
        xsrf = data["xsrfToken"]

        try:
            pubkey = data["loginTrustFlagsSecret"]
        except KeyError as ex:
            raise OperationError("Что-то пошло не так!") from ex

        # Эти заголовки у всех POST-запросов при авторизации
        # У них referer отличается только, но наврядли его гикто не проверяет
        login_headers = {
            "Accept": "application/json",
            "X-Hhtmfrom": "",
            "X-Hhtmsource": "account_login",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": xsrf,
            "Referer": redirect_url,
        }

        # 2. Запрос кода
        params = {
            "login": username,
            "otpType": ["phone", "email"][is_email],
            "operationType": "applicant_otp_auth",
            "authScenario": "APPLICANT_AUTH",
            "formatPhone": "true",
            "isSignupPage": "false",
            "loginTrustFlags": self._login_trust_flags(pubkey),
            "captchaText": "",
        }

        otp_url = urljoin(redirect_url, "/account/otp_generate")

        while True:
            logger.debug(
                "otp generate params: %r | headers: %r", params, login_headers
            )
            r = session.post(
                otp_url,
                files={k: (None, v) for k, v in params.items()},
                headers=login_headers,
            )
            logger.debug(f"{r.request.method} {r.url} {r.status_code}")

            res = r.json()

            if res.get("success"):
                logger.info("Код авторизации был выслан!")
                break

            # logger.debug(res)
            captcha = res.get("hhcaptcha") or {}

            if "captchaState" not in captcha:
                raise OperationError("Неправильный запрос!")

            # isBot еще интересное значение
            if captcha.get("captchaError"):
                logger.warning("Капча была введена неверно!")

            captcha_state = captcha["captchaState"]

            solution = tool.solve_captcha(
                xsrf_token=xsrf,
                captcha_state=captcha_state,
                referer_url=redirect_url,
            )

            params["captchaText"] = solution.text
            params["captchaKey"] = solution.key
            params["captchaState"] = solution.state

        # 3. Ввод кода
        code_from = ["SMS", "Email"][is_email]
        code_icon = ["📱", "📧"][is_email]
        code = input(
            f"{code_icon} Введите полученный код из {code_from}: "
        ).strip()

        if not code:
            raise OperationError("Код подтверждения не может быть пустым.")

        params = {
            "username": username,
            "code": code,
            "backurl": redirect_url,
            "operationType": "applicant_otp_auth",
            "isApplicantSignup": "false",
            "remember": "true",
            # Не знаю от чего их вычислять и нужны ли они тут
            "loginTrustFlags": self._login_trust_flags(pubkey),
            "authScenario": "APPLICANT_AUTH",
        }

        by_code_url = urljoin(redirect_url, "/account/login/by_code")
        r = session.post(
            by_code_url,
            data=params,
            headers=login_headers,
        )

        logger.debug(f"{r.request.method} {r.url} {r.status_code}")

        try:
            res = r.json()
        except json.JSONDecodeError as ex:
            raise OperationError("Неизвестная ошибка!") from ex

        logger.debug(res)

        if not res.get("success"):
            error_key = res.get("error", {}).get("key", "UNKNOWN_ERROR")
            raise OperationError(f"Ошибка авторизации: {error_key}")

        assert res.get("verification", {}).get("success")

        # Теперь нужно проверить заголовки
        backurl = parse_qs(urlsplit(redirect_url).query)["backurl"][0]
        r = session.get(
            urljoin(redirect_url, backurl),
            headers={"Referer": redirect_url},
            allow_redirects=False,
        )

        logger.debug(f"{r.url} {r.status_code}")

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

    @staticmethod
    def _normalize_phone_number(phone: str) -> str:
        # Удаляем всякий мусор типа (, ) и -
        phone = re.sub(r"\D", "", phone)
        if len(phone) == 11 and phone[0] == "8":
            phone = "7" + phone[1:]
        return phone

    @staticmethod
    def _login_trust_flags(pubkey: str, payload: dict[str, Any] = {}) -> str:
        public_key = serialization.load_pem_public_key(pubkey.encode())
        payload = {
            **payload,
            "ts": int(time.time() * 1000),
        }
        logger.debug("trust login data: %r", payload)
        # JSON.stringify -> компактный вывод, без пробелов
        plaintext = json.dumps(payload, separators=(",", ":")).encode()
        ciphertext = public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode()

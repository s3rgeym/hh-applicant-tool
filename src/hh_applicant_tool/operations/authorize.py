from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..tool import BaseOperation, OperationError

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger(__name__)


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

        authorize_url = api_client.oauth_client.authorize_url
        logger.debug(authorize_url)

        backurl = authorize_url + "&skip_choose_account=true"
        fail_url = (
            "/account/login?backurl="
            + quote(backurl, safe="")
            + "&oauth=true&response_type=code"
        )

        # 1. Страница авторизации -> xsrf и публичный ключ
        r = session.get(authorize_url)
        # Если куки не протушли, то авторизация не пройдет

        redirect_url = r.url
        data = tool.parse_initial_state(r)
        xsrf = data["xsrfToken"]

        try:
            pubkey = data["loginTrustFlagsSecret"]
        except KeyError as ex:
            raise OperationError(
                "Что-то пошло не так, возможно, вы уже авторизованы."
            ) from ex

        # Эти заголовки у всех POST-запросов при авторизации
        # У них referer отличается только, но наврядли его гикто не проверяет
        ajax_headers = {
            "x-hhtmfrom": "",
            "x-hhtmsource": "account_login",
            "x-requested-with": "XMLHttpRequest",
            "x-xsrftoken": xsrf,
        }

        # 2. Запрос кода
        params = {
            "_xsrf": xsrf,
            "failUrl": fail_url,
            "remember": "yes",
            "username": username,
            "password": "",
            "isBot": "false",
            "login": username,
            "otpType": ["phone", "email"][is_email],
            "operationType": "applicant_otp_auth",
            "authScenario": "APPLICANT_AUTH",
            "loginTrustFlags": self._login_trust_flags(pubkey),
        }
        otp_url = urljoin(redirect_url, "/account/otp_generate")

        while True:
            logger.debug("Пробуем авторизоваться: POST %s %r", otp_url, params)
            r = session.post(otp_url, params, ajax_headers)
            res = r.json()

            if res.get("success"):
                logger.info("Код авторизации был выслан!")
                break

            captcha = res.get("hhcaptcha") or {}

            if "captchaState" not in captcha:
                raise OperationError("Ошибка авторизации!")

            # isBot еще интересное значение
            if captcha.get("captchaError"):
                logger.warning("Капча была введена неверно!")

            captcha_state = captcha["captchaState"]

            while True:
                if tool.solve_captcha(
                    xsrf_token=xsrf,
                    captcha_state=captcha_state,
                    referer_url=otp_url,
                ):
                    logger.info("Капча принята")
                    params["captchaState"] = captcha_state
                    break
                logger.warning("Неправильная капча!")

        # 3. Ввод кода
        code_from = ["SMS", "Email"][is_email]
        code_icon = ["📱", "📧"][is_email]
        code = input(
            f"{code_icon} Введите полученный код из {code_from}: "
        ).strip()

        if not code:
            raise OperationError("Код подтверждения не может быть пустым.")

        params = {
            "_xsrf": xsrf,
            "failUrl": fail_url,
            "remember": "yes",
            "username": username,
            "password": "",
            "code": code,
            "backurl": backurl,
            "operationType": "applicant_otp_auth",
            "authScenario": "APPLICANT_AUTH",
        }

        by_code_url = urljoin(redirect_url, "/account/login/by_code")
        r = session.post(
            by_code_url,
            data=params,
            headers=ajax_headers,
        )

        logger.debug(f"{r.request.method} {r.url} {r.status_code}")

        try:
            res = r.json()
        except json.JSONDecodeError:
            raise OperationError("Неизвестная ошибка!")

        logger.debug(res)

        if not res.get("success"):
            error_key = res.get("error", {}).get("key", "UNKNOWN_ERROR")
            raise OperationError(f"Ошибка авторизации: {error_key}")

        assert res.get("verification", {}).get("success")

        # Теперь нужно проверить заголовки
        r = session.get(
            res["backurl"],
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
        storage.settings.set_value("auth.username", username)
        storage.settings.set_value("auth.last_login", datetime.now())
        # Куки уже лежат в tool.session — копировать ничего не нужно.
        print("🎉 Авторизация прошла успешно!")

    def _normalize_phone_number(self, phone: str) -> str:
        # Удаляем всякий мусор типа (, ) и -
        phone = re.sub(r"\D", "", phone)
        if len(phone) == 11 and phone[0] == "8":
            phone = "7" + phone[1:]
        return phone

    def _login_trust_flags(self, pubkey: str) -> str:
        public_key = serialization.load_pem_public_key(pubkey.encode())
        payload = {
            "emailOrPhone": {"suggest": True, "paste": False},
            "ts": int(time.time() * 1000),
        }
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

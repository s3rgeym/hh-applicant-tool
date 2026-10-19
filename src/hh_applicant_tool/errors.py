class Error(Exception):
    pass


# Используй эту ошибку для прерывания выполнения команд
class OperationError(Error):
    pass


class OperationCanceled(OperationError):
    pass


class XHRError(Error):
    pass


class CaptchaError(XHRError):
    def __init__(self, captcha_state: str):
        self.state = captcha_state
        super().__init__("Captcha required")


class ReCaptchaError(XHRError):
    def __init__(self, captcha_key: str):
        self.key = captcha_key
        super().__init__("RECAPTCHA required")

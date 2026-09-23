from __future__ import annotations

from . import utils

CONFIG_DIR = utils.get_config_path() / "hh-applicant-tool"
CONFIG_FILENAME = "config.json"
LOG_FILENAME = "log.txt"
DATABASE_FILENAME = "data"
COOKIES_FILENAME = "cookies.txt"
# Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
# Общий таймаут запроса к OpenAI: соединение + чтение ответа
DEFAULT_OPENAI_TIMEOUT = 30.0
# Отдельно на установку соединения, чтобы недоступный сервер не съедал
# весь таймаут
DEFAULT_OPENAI_CONNECT_TIMEOUT = 5.0

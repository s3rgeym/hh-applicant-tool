# Тут только константы, относящиеся к HHApplicantTool, необходимые для его работы
# Они не должны импорттироваться в api/client.py или другом "независимом"
# подмодуле
from __future__ import annotations

from . import utils

CONFIG_DIR = utils.get_config_path()
CONFIG_FILENAME = "config.toml"
LOG_FILENAME = "log.txt"
DATABASE_FILENAME = "data"
COOKIES_FILENAME = "cookies.txt"
HH_BASE_URL = "https://hh.ru"
# Та же страница капчи возвращает 404-ую, если юзер-агент не похож на
# десктопный
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 YaBrowser/26.8.0.0 Safari/537.36"

ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,"
    "application/signed-exchange;v=b3;q=0.7"
)

ACCEPT_LANGUAGE = "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"

REPO_URL = "https://github.com/s3rgeym/hh-applicant-tool/"

# Язык картинки капчи. Задаётся параметром lang у POST /captcha,
# значение приходит от hh.ru в верхнем регистре, но понимает и в
# нижнем
DEFAULT_CAPTCHA_LANGUAGE = "RU"
# Общий таймаут запроса к OpenAI: соединение + чтение ответа
DEFAULT_OPENAI_TIMEOUT = 60.0
# Отдельно на установку соединения, чтобы недоступный сервер не съедал
# весь таймаут
DEFAULT_OPENAI_CONNECT_TIMEOUT = 10.0

# Тут только константы, относящиеся к HHApplicantTool, необходимые для его работы
# Они не должны импорттироваться в api/client.py или другом "независимом"
# подмодуле
from __future__ import annotations

from . import utils

CONFIG_DIR = utils.get_config_directory()
CONFIG_FILENAME = "config.toml"
LOG_FILENAME = "log.txt"
DATABASE_FILENAME = "data"
COOKIES_FILENAME = "cookies.txt"
HH_BASE_URL = "https://hh.ru"
# Та же страница капчи возвращает 404-ую, если юзер-агент не похож на
# десктопный

# Хотя если к API со скрепного браузера запрос сделать, выскочит ошибка
DEFAULT_DESKTOP_USERAGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 YaBrowser/26.8.0.0 Safari/537.36"

ACCEPT_LANGUAGE = "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"

REPO_URL = "https://github.com/s3rgeym/hh-applicant-tool/"

# Язык картинки капчи. Задаётся параметром lang у POST /captcha,
# значение приходит от hh.ru в верхнем регистре, но понимает и в
# нижнем
DEFAULT_CAPTCHA_LANGUAGE = "RU"

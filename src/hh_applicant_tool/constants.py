# Тут только константы, относящиеся к HHApplicantTool, необходимые для его работы
# Они не должны импорттироваться в api/client.py или другом "независимом"
# подмодуле
from __future__ import annotations

import re

from .utils import config
from .utils.package import PACKAGE_NAME

CONFIG_DIR = config.get_config_directory()
CONFIG_FILENAME = "config.toml"
TOKEN_CONFIG_FILENAME = "token.json"
LOG_FILENAME = "log.txt"
COOKIES_FILENAME = "cookies.txt"
HH_BASE_URL = "https://hh.ru"

# Та же страница капчи возвращает 404-ую, если юзер-агент не похож на
# десктопный
# Хотя если к API со скрепного браузера запрос сделать, выскочит капча
DEFAULT_DESKTOP_USERAGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"

ACCEPT_HEADER = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
)

# Влияет на язык контента, поэтому проверяется
# По значениям от сюда показываются английские версии сайтов...
# На хх не знаю что делает, может их антибот его проверяет
ACCEPT_LANGUAGE_HEADER = "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"

# Юзер-агент для эмуляции открытия страницы капчи в мобильном виде приложения
ANDROID_WEBVIEW_USERAGENT = "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230901.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/118.0.0.0 Mobile Safari/537.36"

# Используются в мобильном приложении для авторизации
ANDROID_CLIENT_ID = (
    "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD"
)

ANDROID_CLIENT_SECRET = (
    "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS"
)

# Язык картинки капчи. Задаётся параметром lang у POST /captcha,
# значение приходит от hh.ru в верхнем регистре, но понимает и в
# нижнем
DEFAULT_CAPTCHA_LANGUAGE = "RU"

# Android-приложение перенаправляет на данную ссылку.
# Не знаю учитывается ли.
CAPTCHA_SUCCESS_BACKURL = "hh://applicant/captchaSuccessBackUrl"

CAPTCHA_PROMPT = (
    "Если изображения не видно, значит ваш терминал не поддерживает вывод графики.\n"
    "Введите текст с картинки выше: "
)

# Миниммальное время которое должно пройти после решения капчи перед ее
# отправкой на проверку
CAPTCHA_MIN_SOLVE_DELAY = 10.0

MAX_CAPTCHA_ATTEMPTS = 5

HH_DOMAIN_RE = re.compile(
    r"^(?:.*\.)?(?:hh\.(?:ru|kz|uz|by|net|com)|rabota\.by)\.?$"
)

TELEGRAM_CHAT_URL = "https://t.me/s3rgeym_chat"

GITHUB_PROFILE_URL = "https://github.com/s3rgeym"
GITHUB_REPO_URL = f"{GITHUB_PROFILE_URL}/{PACKAGE_NAME}"

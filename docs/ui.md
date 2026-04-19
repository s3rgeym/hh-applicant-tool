# UI модуль (pywebview)

Локальный графический интерфейс для hh-applicant-tool. Запускается в нативном окне через [pywebview](https://pywebview.flowrl.com/) (Edge WebView2 на Windows, WebKit на macOS/Linux).

## Быстрый старт (для пользователей)

Кликните `start.py` в корне репо (или запустите `python start.py`). Скрипт:

1. Автоматически установит все зависимости (включая pywebview)
2. При первом запуске проведёт авторизацию на hh.ru
3. Предложит выбор: UI или CLI

Никаких ручных команд не нужно.

## Установка (для разработчиков)

pywebview — опциональная зависимость. Установите с extras `ui`:

```bash
pip install -e .[ui]
```

Или через poetry:

```bash
poetry install -E ui
```

## Запуск

Самый простой способ:

```bash
python start.py
```

Или напрямую:

```bash
hh-applicant-tool ui
```

С DevTools (для разработки):

```bash
hh-applicant-tool ui --debug
```

## Экраны

### Главная

Статус авторизации и имя пользователя. Показывает зелёный/красный индикатор подключения к hh.ru.

### Поиск вакансий

Все ~30 параметров операции `apply-vacancies` в виде форм:

- **Основные**: строка поиска, ID резюме, сортировка, опыт, график, зарплата, валюта, период
- **Фильтры**: регион, занятость, метро, проф. роли, индустрии, работодатели, метки, поля поиска
- **AI**: фильтр (heavy/light), rate limit, системный промпт, промпт для письма
- **Опции**: use_ai, force_message, only_with_salary, dry_run, send_email, skip_tests и др.
- **Гео**: координаты для фильтрации по расстоянию (скрытая секция)

**Пресеты** — сохранение/загрузка наборов параметров поиска. Пресеты хранятся в SQLite (таблица `settings` с префиксом `_ui_preset:`). Последний использованный набор параметров автоматически восстанавливается при открытии.

### Резюме

Таблица всех резюме пользователя: ID, название, статус (published/blocked).

### Настройки

Редактирование `config.json`. Секретные поля (`client_secret`, `token`) замаскированы (`***`) и недоступны для редактирования через UI.

## Архитектура

```
src/hh_applicant_tool/
  ui/
    __init__.py          # create_window() — точка входа
    api.py               # class Api — Python<->JS мост (pywebview js_api)
    presets.py            # PresetsManager — CRUD пресетов через SettingsRepository
    templates/
      index.html         # SPA — единая HTML страница с навигацией
      css/app.css        # Кастомные стили
      js/app.js          # JS логика — вызовы pywebview.api.*
  operations/
    ui.py                # CLI команда: hh-applicant-tool ui [--debug]
```

### Как работает мост Python <-> JS

1. `Api` класс передаётся в `webview.create_window(js_api=api)`
2. Каждый публичный метод `Api` доступен из JS как `pywebview.api.method_name(args)`
3. Все вызовы автоматически выполняются pywebview в отдельных потоках
4. Результаты возвращаются как Promise в JS
5. Обратная связь Python -> JS через `window.evaluate_js("updateProgress(...)")`

### Пресеты

`PresetsManager` использует `SettingsRepository` (SQLite) для хранения:
- Именованные пресеты: ключ `_ui_preset:<name>`, значение — JSON с параметрами
- Последний использованный: ключ `_ui_last_used_params`

Модель `SettingModel` автоматически сериализует/десериализует JSON (`store_json=True`).

## Разработка

### Добавление нового метода в Api

1. Добавьте публичный метод в `ui/api.py` — он автоматически станет доступен в JS
2. Вызывайте из JS: `const result = await pywebview.api.new_method(args)`
3. Напишите тест в `tests/test_ui_api.py`

### Добавление нового экрана

1. Добавьте `<div id="new-screen" class="section">` в `index.html`
2. Добавьте ссылку в sidebar: `<a class="sidebar-link" data-section="new-screen" onclick="navigate('new-screen')">`
3. Добавьте логику загрузки в `app.js`

### Тесты

```bash
pytest tests/test_ui_presets.py tests/test_ui_api.py -v
```

Тесты используют in-memory SQLite и не требуют pywebview.

## Ограничения

- pywebview использует системный WebView (Edge WebView2 на Windows 11). На старых системах может потребоваться установка WebView2 Runtime.
- Tailwind CSS загружается через CDN — требуется интернет при первом открытии (далее кэшируется браузером).
- Операция `apply-vacancies` запускается синхронно в отдельном потоке pywebview. Параллельный запуск нескольких операций не поддерживается.

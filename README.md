## HH Applicant Tool

![Publish to PyPI](https://github.com/s3rgeym/hh-applicant-tool/actions/workflows/publish.yml/badge.svg) 
[![PyPi Version](https://img.shields.io/pypi/v/hh-applicant-tool)]() 
[![Python Versions](https://img.shields.io/pypi/pyversions/hh-applicant-tool.svg)]() 
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/s3rgeym/hh-applicant-tool)]()
[![PyPI - Downloads](https://img.shields.io/pypi/dm/hh-applicant-tool)]()
[![Total Downloads](https://static.pepy.tech/badge/hh-applicant-tool)]()

<div align="center">
  <img src="https://github.com/user-attachments/assets/29d91490-2c83-4e3f-a573-c7a6182a4044" width="500">
</div>

### Описание

> Утилита для генерации сопроводительного письма может использовать AI

Утилита для успешных волчат и старых волков с опытом, служащая для автоматизации действий на HH.RU таких как рассылка откликов на подходящие вакансии и обновление всех резюме (бесплатный аналог услуги на HH). Но данная утилита больше чем просто спамилка откликами, вы так же выступаете в роли тайного агента, и если в списке подходящих вакансий встречается отказ, она возвращает ссылку на обсуждение работодателя в группе [Отзывы о работодателях с HH.RU](https://t.me/otzyvy_headhunter). Там вы можете написать отзыв о работодателе и почитать чужие. Для этого собираются данные о работодателях и их вакансиях (персональные данные пользователя не передаются ни в каком виде). Отправку данных на сервер разработчика можно отключить, но тогда вы не получите ссылку на обсуждение, а так же не сможете пожаловаться на неадекватного мудака, выкатившего отказ после "небольшого" тестового задания на недельку. Через сайты на таких жаловаться бесполезно: владелец сайта за деньги или после угроз судом удаляют отзывы. Единственное место где можно написать отзыв — это **Telegram**. 

Работает с Python >= 3.10. Нужную версию Python можно поставить через
asdf/pyenv/conda и что-то еще.

Данная утилита написана для Linux, но будет работать и на Ga..Mac OS, и в Windows, но с WSL не будет, так как для авторизации требуются оконный сервер X11 либо Wayland — только прямая установка пакета через pip в Windows. После авторизации вы можете перенести конфиг на сервер и запускать утилиту через systemd или cron. Столь странный процесс связан с тем, что на странице авторизации запускается море скриптов, которые шифруют данные на клиенте перед отправкой на сервер, а так же выполняется куча запросов чтобы проверить не бот ли ты. Хорошо, что после авторизации никаких проверок по факту нет, даже айпи не проверяется на соответсвие тому с какого была авторизация. В этой лапше мне лень разбираться. Так же при наличии рутованного телефона можно вытащить `access` и `refresh` токены из официального приложения и добавить их в конфиг.

Пример работы:

![image](https://github.com/user-attachments/assets/a0cce1aa-884b-4d84-905a-3bb207eba4a3)

> Если в веб-интерфейсе выставить фильтры, то они будут применяться в скрипте при отклике на подходящие

### Предыстория

Долгое время я делал массовые заявки с помощью консоли браузера:

```js
$$('[data-qa="vacancy-serp__vacancy_response"]').forEach((el) => el.click());
```

Оно работает, хоть и не идеально. Я даже пробовал автоматизировать рассылки через `p[yu]ppeeter`, пока не прочитал [документацию](https://github.com/hhru/api). И не обнаружил, что **API** (интерфейс) содержит все необходимые мне методы. Headhunter позволяет создать свое приложение, но там ручная модерация, и наврядли кто-то разрешит мне создать приложение для спама заявками. Я [декомпилировал](https://gist.github.com/s3rgeym/eee96bbf91b04f7eb46b7449f8884a00) официальное приложение для **Android** и получил **CLIENT_ID** и **CLIENT_SECRET**, необходимые для работы через **API**.

### Установка

```bash
# Версия с поддержкой авторизации через запуск окна с браузером (эта версия очень много весит)
# Можно использовать обычный pip
$ pipx install 'hh-applicant-tool[qt]'

# Если хочется использовать самую последнюю версию, то можно установить ее через git
$ pipx install git+https://github.com/s3rgeym/hh-applicant-tool

# Для обновления до новой версии
$ pipx upgrade hh-applicant-tool
```

Отдельно я распишу процесс установки в **Windows** в подробностях:

* Для начала поставьте последнюю версию **Python 3** любым удобным способом.
* Запустите **Terminal** или **PowerShell** от Администратора и выполните:
  ```ps
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy Unrestricted
  ```
  Данная политика разрешает текущему пользователю (от которого зашли) запускать скрипты. Без нее не будут работать виртуальные окружения.
* Создайте и активируйте виртуальное окружение:
  ```ps
  PS> python -m pip venv hh-applicant-venv
  PS> .\hh-applicant-venv\Scripts\activate
  ```
* Поставьте все пакеты в виртуальное окружение `hh-applicant-venv`:
  ```ps
  (hh-applicant-venv) PS> pip install hh-applicant-tool[qt]
  ```
* Проверьте работает ли оно:
  ```ps
  (hh-applicant-venv) PS> hh-applicant-tool -h
  ```
* В случае неудачи вернитесь к первому шагу.
* Для последующих запусков сначала активируйте виртуальное окружение.

### Авторизация

```bash
$ hh-applicant-tool -vv authorize
```

![image](https://github.com/user-attachments/assets/88961e31-4ea3-478f-8c43-914d6785bc3b)

> В Windows не забудьте разрешить доступ к сети (Allow access) в всплывающем окне.

Проверка авторизации:

```bash
$ hh-applicant-tool whoami
{
  "auth_type": "applicant",
  "counters": {
    "new_resume_views": 1488,
    "resumes_count": 1,
    "unread_negotiations": 228
  },
  "email": "vasya.pupkin@gmail.com",
  "employer": null,
  "first_name": "Вася",
  "id": "1234567890",
  "is_admin": false,
  "is_anonymous": false,
  "is_applicant": true,
  "is_application": false,
  "is_employer": false,
  "is_in_search": true,
  "last_name": "Пупкин",
  "manager": null,
  "mid_name": null,
  "middle_name": null,
  "negotiations_url": "https://api.hh.ru/negotiations",
  "personal_manager": null,
  "phone": "79012345678",
  "profile_videos": {
    "items": []
  },
  "resumes_url": "https://api.hh.ru/resumes/mine"
}
```

В случае успешной авторизации токены будут сохранены в `config.json`:

```json
{
  "token": {
    "access_token": "...",
    "created_at": 1678151427,
    "expires_in": 1209599,
    "refresh_token": "...",
    "token_type": "bearer"
  }
}
```

Токен доступа выдается на две недели. После его нужно обновить:

```bash
$ hh-applicant-tool refresh-token
```

### Пути до файла config.json

| OS                         | Путь                                                                |
|----------------------------|---------------------------------------------------------------------|
| **Windows**                | `C:\Users\%username%\AppData\Roaming\hh-applicant-tool\config.json` |
| **macOS**                  | `~/Library/Application Support/hh-applicant-tool/config.json`       |
| **Linux**                  | `~/.config/hh-applicant-tool/config.json`                           |

Полный путь до конфигурационного файла можно вывести с помощью команды:

```bash
hh-applicant-tool config -p
```

Через конфиг можно задать дополнительные настройки:

| Имя атрибута | Описание |
| --- | --- |
| `user_agent` | Кастомный юзерагент, передаваемый при кажом запросе, например, `Mozilla/5.0 YablanBrowser` |
| `proxy_url` | Прокси, используемый для всех запросов, например, `socks5h://127.0.0.1:9050` |
| `reply_message` | Сообщение для ответа работодателю при отклике на вакансии, см. формат сообщений |

### Описание команд

```bash
$ hh-applicant-tool [ GLOBAL_FLAGS ] [ OPERATION [ OPERATION_FLAGS  ] ]

# Справка по глобальным флагам и список операций
$ hh-applicant-tool -h

# Справка по операции
$ hh-applicant-tool apply-similar -h

# Авторизуемся
$ hh-applicant-tool authorize

# Рассылаем заявки
$ hh-applicant-tool apply-similar

# Поднимаем резюме
$ hh-applicant-tool update-resumes

# Чистим заявки и баним за отказы говноконторы
$ hh-applicant-tool clear-negotiations --blacklist-discard
```

Можно вызвать любой метод API:

```bash
$ hh-applicant-tool call-api /employers text="IT" only_with_vacancies=true | jq -r '.items[].alternate_url'
https://hh.ru/employer/1966364
https://hh.ru/employer/4679771
https://hh.ru/employer/8932785
https://hh.ru/employer/9451699
https://hh.ru/employer/766478
https://hh.ru/employer/4168187
https://hh.ru/employer/9274777
https://hh.ru/employer/1763330
https://hh.ru/employer/5926815
https://hh.ru/employer/1592535
https://hh.ru/employer/9627641
https://hh.ru/employer/4073857
https://hh.ru/employer/2667859
https://hh.ru/employer/4053700
https://hh.ru/employer/5190600
https://hh.ru/employer/607484
https://hh.ru/employer/9386615
https://hh.ru/employer/80660
https://hh.ru/employer/6078902
https://hh.ru/employer/1918903
```

Данная возможность полезна для написания Bash-скриптов.

Глобальные флаги:

- `-v` используется для вывода отладочной информации. Два таких флага, например, выводят запросы к **API**.
- `-c <path>` можно создать путь до конфига. С помощью этого флага можно одновременно использовать несколько профилей.

| Операция               | Описание                                                                                            |
| ---------------------- | --------------------------------------------------------------------------------------------------- |
| **authorize**          | Открывает сайт hh.ru для авторизации и перехватывает перенаправление на `hhadnroid://oauthresponse` |
| **whoami**             | Выводит информацию об авторизованном пользователе                                                   |
| **list-resumes**       | Список резюме                                                                                       |
| **update-resumes**     | Обновить все резюме. Аналогично нажатию кнопки «Обновить дату».                                     |
| **apply-similar**      | Откликнуться на все подходящие вакансии. Лимит = 200 в день. На HH есть спам-фильтры, так что лучше не рассылайте отклики со ссылками, иначе рискуете попасть в теневой бан. |
| **reply-employers** | Ответить во все чаты с работодателями, где нет ответа либо не прочитали ваш предыдущий ответ |
| **clear-negotiations** | Удаляет отказы и отменяет заявки, которые долго висят                                               |
| **call-api**           | Вызов произвольного метода API с выводом результата.                                                |
| **refresh-token**      | Обновляет access_token.                                                                             |
| **config**      | Редактировать конфигурационный файл. |
| **get-employer-contacts** | Получить список контактов работодателя, даже если тот не высылал приглашения. Это  функционал для избранных, но в группе есть бесплатный бот с тем же функционалом. |

### Формат текста сообщений

Команда `apply-similar` поддерживает специальный формат сообщений.

Так же в сообщении можно использовать плейсхолдеры:

- **`%(vacancy_name)s`**: Название вакансии.
- **`%(employer_name)s`**: Название работодателя.
- **`%(first_name)s`**: Имя пользователя.
- **`%(last_name)s`**: Фамилия пользователя.
- **`%(email)s`**: Email пользователя.
- **`%(phone)s`**: Телефон пользователя.

Эти плейсхолдеры могут быть использованы в сообщениях для отклика на вакансии, чтобы динамически подставлять соответствующие данные в текст сообщения. Например:

```
Меня заинтересовала ваша вакансия %(vacancy_name)s. Прошу рассмотреть мою кандидатуру. С уважением, %(first_name)s %(last_name)s.
```

Так же можно делать текст уникальным с помощью `{}`. Внутри них через `|` перечисляются варианты, один из которых будет случайно выбран:

```
{Здоров|Привет}, {как {ты|сам}|что делаешь}?
```

В итоге получится что-то типа:

```
Привет, как ты?
```

### Использование AI для генерации сопроводительного письма

* Перейдите на сайт [blackbox.ai](https://www.blackbox.ai) и создайте чат. 
* В первом сообщении опишите свой опыт и тп. 
* Далее откройте devtools, нажав `F12`. 
* Во вкладке `Network` последним должен быть POST-запрос на `https://www.blackbox.ai/api/chat`. 
* Запустите редактирование конфига:
    ```sh
    hh-applicant-tool config
    ```
* Измените конфиг:
    ```json
    {
        // ...
        "blackbox": {
            "session_id": "<В заголовках запроса найдите Cookie, скопируйте сюда значение sessionId до ;>",
            "chat_payload": <Сюда вставьте тело запроса типа {"messages":[{"id":"IXqdOx9","content":"Я программист fullstack-разработчик...","role":"user"}],"id":"IXqdOx9","previewToken":null,"userId":null,...,"webSearchModePrompt":false,"deepSearchMode":false}>
        }
    }
    ```
* Пример рассылки откликов с генерированным письмом:
    ```sh
    hh-applicant-tool apply-similar -f --ai
    ```

### Написание плагинов

Утилита использует систему плагинов. Все они лежат в [operations](https://github.com/s3rgeym/hh-applicant-tool/tree/main/hh_applicant_tool/operations). Модули расположенные там автоматически добавляются как доступные операции. За основу для своего плагина можно взять [whoami.py](https://github.com/s3rgeym/hh-applicant-tool/tree/main/hh_applicant_tool/operations/whoami.py).

Отдельные замечания у меня к API HH. Оно пиздец какое кривое. Например, при создании заявки возвращается пустой ответ либо редирект, хотя по логике должен возвраться созданный объект. Так же в ответах сервера нет `Content-Length`. Из-за этого нельзя узнать есть тело у ответа сервера нужно его пробовать прочитать. Я так понял там какой-то прокси оборачивает все запросы и отдает всегда `Transfer-Encoding: Chunked`. А еще он возвращает 502 ошибку, когда бекенд на Java падает либо долго отвечает (таймаут)? А вот [язык запросов](https://hh.ru/article/1175) мне понравился. Можно что-то типа этого использовать `NOT (!ID:123 OR !ID:456 OR !ID:789)` что бы отсеить какие-то вакансии.

Для создания своих плагинов прочитайте документацию:

* [HH.RU OpenAPI](https://api.hh.ru/openapi/redoc)

Для тестирования запросов к API используйте команду `call-api` и `jq` для вывода JSON в удобочитаемом формате.

# HH Applicant Tool

> ! Наложен мораторий на доработки/переработки

![Publish to PyPI](https://github.com/s3rgeym/hh-applicant-tool/actions/workflows/publish.yml/badge.svg) [![PyPi Version](https://img.shields.io/pypi/v/hh-applicant-tool)](https://img.shields.io/pypi/v/hh-applicant-tool) [![Python Versions](https://img.shields.io/pypi/pyversions/hh-applicant-tool.svg)](https://img.shields.io/pypi/pyversions/hh-applicant-tool.svg) [![PyPI - Downloads](https://img.shields.io/pypi/dm/hh-applicant-tool)](https://img.shields.io/pypi/dm/hh-applicant-tool)

Утилита для автоматизации действий на HH.RU таких как рассылка откликов на подходящие вакансии и обновление всех резюме.

Системные требования:

- socat
- python >= 3.10

Нужную версию можно поставить через asdf/pyenv, а вот socat придется доставить.

Данная утилита не может работать от root. Я не планирую добавлять поддержку Windows, но никто не мешает вам ее реализовать.

Предыстория.

Был один знакомый знакомого, который работал хером. Этот чувак не заморачивался с чтением резюме, а тупо скриптами рассылал предложения о работе... Бывают, конечно, филологини, которые не могут отлчить Java от JavaScript, но я думаю, что в значительном числе случаев, тут имеют место такие вот рассылки... И я перенял эту порочную практику. Мне уже просто лень читать весь этот бред, что пишут в описании вакансий. Там стандартное ООП, алгоритмы и прочая хуета... Вроде все подходят, а вроде хз — все не мое. Поэтому тупло спамлю в надежде на идеальную работу. Долгое время (пару недель в октябре 2022) я делал массовые заявки с помощью консоли браузера:

```js
$$('[data-qa="vacancy-serp__vacancy_response"]').forEach((el) => el.click());
```

И оно работает, хоть и не идеально. Я даже пробовал автоматизировать рассылки через `p[yu]ppeeter`, пока не прочитал [документацию](https://github.com/hhru/api). И не обнаружил, что **API** (интерфейс) содержит все необходимые мне методы. Headhunter позволяет создать свое приложение, но там ручная модерация, и наврядли кто-то разрешит мне создать приложение для спама заявками. Я [декомпилировал](https://gist.github.com/s3rgeym/eee96bbf91b04f7eb46b7449f8884a00) официальное приложение для **Android** и получил **CLIENT_ID** и **CLIENT_SECRET**, необходимые для работы через **API**.

Установка:

```bash
# Через pypi
# Можно использовать и обычный pip
$ pipx install hh-applicant-tool

# Если хочется использовать самую последнюю версию, то можно установить ее через git
$ pipx install git+https://github.com/s3rgeym/hh-applicant-tool
```

Использование:

```bash
$ hh-applicant-tool [ GLOBAL_FLAGS ] [ OPERATION [ OPERATION_FLAGS  ] ]

# Справка по глобальным флагам и список операций
$ hh-applicant-tool -h

# Справка по операции
$ hh-applicant-tool apply-similar -h

# Добавляем обработчик
$ hh-applicant-tool add-handler

# Авторизуемся
$ hh-applicant-tool authorize

# Рассылаем заявки
$ hh-applicant-tool apply-similar

# Поднимаем резюме
$ hh-applicant-tool update-resumes

# Чистим заявки и баним за отказы говноконторы, нанявших на работу филолохинь,
# астралохинь и прочих 3.14дарасов по блату, считающих, что погроммистом может
# быть только ДОЦЕНТ МАТЕМАТИЧЕСКИХ НАУК 🤡
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
| **add-handler**        | Добавляет обработчик протокола `hhandroid`                                                          |
| **authorize**          | Открывает сайт hh.ru для авторизации и перехватывает перенаправление на `hhadnroid://oauthresponse` |
| **whoami**             | Выводит информацию об авторизованном пользователе                                                   |
| **list-resumes**       | Список резюме                                                                                       |
| **update-resumes**     | Обновить все резюме. Аналогично нажатию кнопки «Обновить дату».                                     |
| **apply-similar**      | Откликнуться на все подходящие вакансии. Лимит = 200 в день                                         |
| **clear-negotiations** | Удаляет отказы и отменяет заявки, которые долго висят                                               |
| **call-api**           | Вызов произвольного метода API с вводом результата.                                                 |
| **refresh-token**      | Обновляет access_token.                                                                             |

Для начала нужно добавить обработчик протокола `hhandroid`, который используется Android-приложением для усложнения жизни честным автоматизаторам:

```bash
$ hh-applicant-tool -vv add-handler
[I] saved /home/sergey/.local/share/applications/hhandroid.desktop
✅ Обработчик добавлен!
```

Авторизуемся:

```bash
$ hh-applicant-tool -vv authorize
Пробуем открыть в браузере: https://hh.ru/oauth/authorize?client_id=HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD&response_type=code
Авторизуйтесь и нажмите <Подтвердить>
[I] 🚀 Запускаем TCP-сервер и слушаем unix:///tmp/hhandroid.sock
Gtk-Message: 20:52:59.280: Failed to load module "canberra-gtk-module"
Gtk-Message: 20:52:59.975: Failed to load module "canberra-gtk-module"
[54:54:0305/205300.038812:ERROR:gl_factory.cc(128)] Requested GL implementation (gl=desktop-gl,angle=none) not found in allowed implementations: [(gl=egl-angle,angle=default),(gl=egl-gles2,angle=none),(gl=egl-angle,angle=swiftshader)].
[54:54:0305/205300.041723:ERROR:viz_main_impl.cc(186)] Exiting GPU process due to errors during initialization
Opening in existing browser session.
[D] hhandroid://oauthresponse?code=99Q9G1RII75D8R2FTU06BF2FDNI7JF16MGBIB4OEQ973819OOJI90S69I1CL9U96
[D] 200 POST   https://hh.ru/oauth/token
[D] Сохраняем токен
🔓 Авторизация прошла успешно!
```

![image](https://user-images.githubusercontent.com/12753171/222978533-ed30a918-ed15-4a81-a8c2-f083e8469c16.png)

Тут надо выбирать `Open xdg-open`.

После смотрим в терминал и если видим сообщение об успехе, закрываем вкладку.

В случае успешной авторизации токены будут сохранены `~/.config/hh-applicant-tool/config.json`:

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

Через этот файл можно задать кастомный `user_agent`:

```json
{
  "user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/110.0"
}
```

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
zcnbvm@proton.me",
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

Далее идут заметки для разработчиков...

Токен выдается на две недели:

```python
Python 3.10.9 (main, Dec 19 2022, 17:35:49) [GCC 12.2.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> from datetime import datetime, timedelta
>>> datetime.now() + timedelta(seconds=1209599)
datetime.datetime(2023, 3, 23, 6, 36, 15, 596290)
>>>
```

После нужно вызвать `refresh-token`.

![](https://user-images.githubusercontent.com/12753171/222870516-b29f2417-d11a-4122-8291-7d440a422a31.png)

При авторизации можно указать `redirect_uri`, но любые адреса кроме того, что с протоколом `hhandroid`, будут приводить к ошибке. Поэтому и нужно добавление обработчика кастомного протокола. При котором создается desktop-файл, где в секции `Exec` всего пару команд для того чтобы записать полученный uri в сокет. TCP-сервер, который запускается при авторизации, как раз слушает этот сокет... Использование АВТОРИЗАЦИИ ДЛЯ САЙТОВ в мобильном приложении выглядит странной, так как десктопные и мобильные приложения обычно авторизуются напрямую, но у чуваков свое понимание не только протокола OAuth...

Удаление хвостов:

```bash
rm -rf ~/.config/hh-applicant-tool
rm -f ~/.local/share/applications/hhandroid.desktop
```

Утилита использует систему плагинов. Все они лежат в [operations](https://github.com/s3rgeym/hh-applicant-tool/tree/main/hh_applicant_tool/operations). Модули расположенные там автоматически добавляются как доступные операции. За основу для своего плагина можно взять [whoami.py](https://github.com/s3rgeym/hh-applicant-tool/tree/main/hh_applicant_tool/operations/whoami.py).

Отдельные замечания у меня к API HH. Оно пиздец какое кривое. Например, при создании заявки возвращается пустой ответ либо редирект, хотя по логике должен возвраться созданный объект. Так же в ответах сервера нет `Content-Length`. Из-за этого нельзя узнать есть тело у ответа сервера нужно его пробовать прочитать. Я так понял там какой-то прокси оборачивает все запросы и отдает всегда `Transfer-Encoding: Chunked`. А еще он возвращает 502 ошибку, когда бекенд на Java падает либо долго отвечает (таймаут)? А вот [язык запросов](https://hh.ru/article/1175) мне понравился. Можно что-то типа этого использовать `NOT (!ID:123 OR !ID:456 OR !ID:789)` что бы отсеить какие-то вакансии.

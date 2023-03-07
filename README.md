# HH Applicant Tool

Утилита для автоматизации действий на HH таких как отклик на подходящие вакансии.

Системные требования:

- socat
- python >= 3.10

Нужную версию можно поставить через asdf/pyenv, а вот socat придется доставить.

Данная утилита не может работать от root. Я не планирую добавлять поддержку Windows, но никто не мешает вам ее реализовать.

Предыстория.

Был один знакомый знакомого, который работал херкой. Этот чувак не заморачивался с чтением резюме, а тупо скриптами рассылал предложения о работе... Бывают, конечно, филологини, которые не могут отлчить Java от JavaScript, но я думаю, что в значительном числе случаев, тут имеют место такие вот рассылки... И я просто перенял эту порочную тактику. Мне лень читать весь бред, что там пишут. Долгое время я делал массовые заявки с помощью консоли браузера:

```js
$$('[data-qa="vacancy-serp__vacancy_response"]').forEach((el) => el.click());
```

И оно работает, хоть и не идеально. Я даже пробовал автоматизировать рассылки через `p[yu]ppeeter`, пока не прочитал [документацию](https://github.com/hhru/api). И не обнаружил, что в оно содержит все необходимые методы. Я [декомпилировал](https://gist.github.com/s3rgeym/eee96bbf91b04f7eb46b7449f8884a00) официальное приложение для Android и получил CLIENT_ID и CLIENT_SECRET, полученные мною путем.

Установка:

```bash
# Через pypi
# Можно использовать и обычный pip
$ pipx install hh-applicant-tool

# Если хочется использовать самую последнюю версию, то можно установить ее через git
$ pipx install git+https://github.com/s3rgeym/hh-applicant-tool
```

Помощь:

```bash
$ hh-applicant-tool
...

$ hh-applicant-tool apply-jobs -h
usage: hh-applicant-tool apply-jobs [-h] [--resume-id RESUME_ID] [--message-list MESSAGE_LIST]

Откликнуться на все подходящие вакансии

options:
  -h, --help            show this help message and exit
  --resume-id RESUME_ID
                        Идентефикатор резюме
  --message-list MESSAGE_LIST
                        Путь до файла, где хранятся сообщения для отклика на вакансии. Каждое сообщение — с новой строки. В сообщения можно использовать плейсхолдеры типа
                        %(name)s
```

Для начала нужно добавить обработчик протокола `hhandroid`, который используется Android-приложением для усложнения жизни честным автоматизаторам:

```bash
$ hh-applicant-tool -vv add-handler
[I] saved /home/sergey/.local/share/applications/hhandroid.desktop
✅ Обработчик добавлен!
```

Флаг `-v` используется для вывода отладочной информации. Два таких флага выводят всю возможную.

Авторизуемся:

```bash
$ hh_applicant_tool -vv authorize
Пробуем открыть в браузере: https://hh.ru/oauth/authorize?client_id=HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD&response_type=code
Авторизуйтесь и нажмите <<Подтвердить>>
[I] 🚀 Стартуем TCP-сервер по адресу unix:///tmp/hhandroid.sock
Gtk-Message: 20:52:59.280: Failed to load module "canberra-gtk-module"
Gtk-Message: 20:52:59.975: Failed to load module "canberra-gtk-module"
[54:54:0305/205300.038812:ERROR:gl_factory.cc(128)] Requested GL implementation (gl=desktop-gl,angle=none) not found in allowed implementations: [(gl=egl-angle,angle=default),(gl=egl-gles2,angle=none),(gl=egl-angle,angle=swiftshader)].
[54:54:0305/205300.041723:ERROR:viz_main_impl.cc(186)] Exiting GPU process due to errors during initialization
Opening in existing browser session.
[D] hhandroid://oauthresponse?code=99Q9G1RII75D8R2FTU06BF2FDNI7JF16MGBIB4OEQ973819OOJI90S69I1CL9U96
[D] POST https://hh.ru/oauth/token 200
[D] Сохраняем токен
🔓 Авторизация прошла успешно!
```

![image](https://user-images.githubusercontent.com/12753171/222978533-ed30a918-ed15-4a81-a8c2-f083e8469c16.png)

Тут надо выбирать `Open xdg-open`.

После смотрим в консоль и если видим сообщение об успехе, закрываем вкладку.

![](https://user-images.githubusercontent.com/12753171/222870516-b29f2417-d11a-4122-8291-7d440a422a31.png)

При авторизации можно указать `redirect_uri`, но любые адреса кроме того, что с протоколом `hhandroid`, будут приводить к ошибке. Поэтому и нужно добавление обработчика кастомного протокола. При котором создается desktop-файл, где в секции `Exec` всего пару команд для того чтобы записать полученный uri в сокет. TCP-сервер, который запускается при авторизации, как раз слушает этот сокет... Использование АВТОРИЗАЦИИ ДЛЯ САЙТОВ в мобильном приложении выглядит странной, так как десктопные и мобильные приложения обычно авторизуются напрямую, но у чуваков свое понимание не только протокола OAuth...

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

Утилита использует систему плагинов. Все они лежат в [operations](https://github.com/s3rgeym/hh-applicant-tool/tree/main/hh_applicant_tool/operations). Модули расположенные там автоматически добавляются как доступные операции. За основу для своего плагина можно взять [whoami.py](https://github.com/s3rgeym/hh-applicant-tool/tree/main/hh_applicant_tool/operations/whoami.py).

Отдельные замечания у меня к API HH. Оно пиздец какое кривое. Например, при создании заявки возвращается пустой ответ либо редирект, хотя по логике должен возвраться созданный объект. Так же в ответах сервера нет `Content-Length`. Из-за этого нельзя . Я так понял там какой-то прокси оборачивает все запросы и отдает всегда `Transfer-Encoding: Chunked`. А еще он возвращает 502 ошибку, когда бекенд на Java падает либо долго отвечает (таймаут)? А вот [язык запросов](https://hh.ru/article/1175) мне понравился. Можно что-то типа этого использовать `NOT (!ID:123 OR !ID:456 OR !ID:789)` что бы отсеить какие-то вакансии.

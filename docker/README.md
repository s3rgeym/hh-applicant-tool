Авторизуйтесь на хосте, а потом перенесите `config.json` (должен лежать в одной директории с `docker-compose.yml`) на сервер, а там через `docker compose up -d` можно все запустить.

Что делает:

* спамит заявками;
* обновляет токен;
* и все это делается через `cron`.
# Используем базовый образ Alpine с Python 3.12
FROM python:3.13-alpine

# Определяем аргументы для UID и GID
ARG UID=1000
ARG GID=1000

# Устанавливаем необходимые зависимости, включая пакет shadow
RUN apk add --no-cache gcc musl-dev linux-headers shadow dos2unix tzdata

# Устанавливаем библиотеку hh-applicant-tool
RUN pip install hh-applicant-tool

# Создаем группу и пользователя с указанными UID и GID
RUN groupadd -g $GID docker && \
  useradd -u $UID -g docker -m -s /bin/sh docker

# Указываем рабочую директорию
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . /app

# Копируем crontab файл в контейнер
COPY crontab /etc/crontabs/docker

# если crontab сохранен в windows из-за перевода каретки работать не будет
RUN dos2unix /etc/crontabs/docker

# Переключаемся на пользователя с указанными UID и GID
#USER docker

# Команда, которая будет выполнена при запуске контейнера
CMD ["crond", "-f", "-d", "0"]

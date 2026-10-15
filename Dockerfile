FROM python:3.13-alpine

# Системные зависимости
RUN apk add --no-cache tzdata less

# Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN addgroup -g $GID docker && \
    adduser -D -u $UID -G docker -s /bin/sh docker

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# Ставим утилиту (компилятор нужен только на время сборки) и готовим каталог конфига
RUN apk add --no-cache --virtual .build-deps gcc musl-dev && \
    pip install --no-cache-dir -e '.' && \
    apk del .build-deps && \
    mkdir -p ./config && chown -R docker:docker ./config

USER docker

ENTRYPOINT ["hh-applicant-tool"]

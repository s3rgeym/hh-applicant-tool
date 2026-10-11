# SLIM КАЛ ЕБУЧИЙ!!! ХВАТИТ ГАДИТЬ ВЫСЕРАМИ НЕЙРОПРИДУРКА! 
# ЕСЛИ НЕТ СВОИХ МОЗГОВ, ТО И ГОЛОВА НАХУЙ НЕ НУЖНА
# ЛЯЖЬ НА РЕЛЬСЫ, ПУСТЬ ТЕБЕ ЕЕ НАХУЙ ОТПИЛИТ
FROM python:3.13-slim

# Системные зависимости
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc \
      libc6-dev \
      procps \
      cron \
      dos2unix \
      tzdata \
      less && \
    rm -rf /var/lib/apt/lists/*

# Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID docker && \
    useradd -u $UID -g docker -m -s /bin/bash docker

WORKDIR /app

COPY pyproject.toml README.md ./

# Копируем исходный код
COPY src ./src

# Устанавливаем саму утилиту
# Подготовка cron
RUN pip install --no-cache-dir -e '.' && \
    touch /var/log/cron.log && chown docker:docker /var/log/cron.log && \
    mkdir -p ./config && chown -R docker:docker ./config

# Копируем остальное
COPY --chmod=755 crontab startup.sh ./

# Запускаем cron и читаем лог
# cron не видит переменные окружения, переданные главному процессу, точнее
# он начинает новую сессию, где тот же $CONFIG_DIR пуст
CMD printenv | grep -E '^(CONFIG_DIR|HH_PROFILE_ID)=' > /etc/environment; \
    chown -R docker:docker ./config && \
    dos2unix -n ./crontab /tmp/crontab && \
    crontab -u docker /tmp/crontab && \
    cron && \
    exec tail -f /var/log/cron.log

FROM python:3.13-slim

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
  gcc \
  libc6-dev \
  procps \
  cron \
  dos2unix \
  tzdata \
  && rm -rf /var/lib/apt/lists/*

# Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID docker && \
  useradd -u $UID -g docker -m -s /bin/bash docker

WORKDIR /app

# Копируем файлы описания проекта
COPY pyproject.toml poetry.lock* README.md /app/

# Копируем исходники и скрипты
COPY src /app/src
COPY config /app/config
COPY crontab /app/crontab
COPY startup.sh /app/startup.sh

# Установка проекта
RUN pip install --no-cache-dir -e '.[playwright]' && \
  playwright install chromium --with-deps

# Базовая настройка прав (для образа)
RUN touch /var/log/cron.log && chown docker:docker /var/log/cron.log && \
  dos2unix /app/startup.sh /app/crontab && \
  chmod +x /app/startup.sh && \
  chmod 0644 /app/crontab && \
  crontab -u docker /app/crontab

# ЗАПУСК: Исправляем права на примонтированный volume и стартуем
CMD chown -R docker:docker /app/config && cron && tail -f /var/log/cron.log

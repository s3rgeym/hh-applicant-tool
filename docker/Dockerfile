FROM python:3.13-slim

# 1. Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
  gcc \
  libc6-dev \
  procps \
  cron \
  dos2unix \
  tzdata \
  && rm -rf /var/lib/apt/lists/*

# 2. Установка инструмента
RUN pip install --no-cache-dir 'hh-applicant-tool[playwright]'
RUN playwright install chromium --with-deps

# 3. Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID docker && \
  useradd -u $UID -g docker -m -s /bin/bash docker

WORKDIR /app

# 4. Копирование файлов и настройка прав
COPY . /app
RUN touch /var/log/cron.log && chown docker:docker /var/log/cron.log && \
  chown -R docker:docker /app

# 5. Делаем скрипты исполняемыми и чистим их от Windows-переносов
RUN dos2unix /app/startup.sh /app/crontab && \
  chmod +x /app/startup.sh && \
  chmod 0644 /app/crontab && \
  crontab -u docker /app/crontab

# 6. Запуск: демон cron + вывод лога
CMD cron && tail -f /var/log/cron.log

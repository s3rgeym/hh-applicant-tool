FROM python:3.13-slim

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
  gcc \
  libc6-dev \
  procps \
  cron \
  dos2unix \
  tzdata \
  less

# Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID docker && \
  useradd -u $UID -g docker -m -s /bin/bash docker

WORKDIR /app

COPY pyproject.toml poetry.lock* README.md /app/

# 1. Сначала ставим только playwright, чтобы получить доступ к его CLI
RUN pip install --no-cache-dir playwright

# 2. Скачиваем браузер и системные зависимости (этот тяжелый слой теперь закэшируется)
RUN playwright install-deps chromium && \
    su docker -c "playwright install chromium"

# 3. Теперь копируем исходный код
COPY src /app/src

# 4. Устанавливаем саму утилиту и остальные зависимости
RUN pip install --no-cache-dir -e '.[playwright,pillow]'

# Очистка кеша пакетов для уменьшения веса контейнера
RUN rm -rf /var/lib/apt/lists/*

# Fix: падение, если каталог config не существует
#RUN mkdir -p /app/config

# Копируем остальное (эти файлы мешают кешированию последующих слоев)
COPY config /app/config
COPY crontab /app/crontab
COPY startup.sh /app/startup.sh

# Настройка крона
RUN touch /var/log/cron.log && chown docker:docker /var/log/cron.log && \
  dos2unix /app/crontab && \
  chmod +x /app/startup.sh && \
  chmod 0644 /app/crontab && \
  crontab -u docker /app/crontab

# Запускаем крон и читаем лог
# cron не видит переменные окружения, переданные главному процессу, точнее
# он начинает новую сессию, где тот же $CONFIG_DIR пуст
CMD printenv | grep -E 'CONFIG_DIR|HH_PROFILE_ID' >> /etc/environment && \
  chown -R docker:docker /app/config && \
  cron && \
  tail -f /var/log/cron.log

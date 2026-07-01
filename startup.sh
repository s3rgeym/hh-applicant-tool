#!/bin/bash
echo "[$(date)] Running startup tasks..."

# echo "Current user: $(whoami)"
# echo "$CONFIG_DIR"

# Выполняем цепочку
/usr/local/bin/python -m hh_applicant_tool refresh-token
/usr/local/bin/python -m hh_applicant_tool update-resumes
# Раскомментируй, если нужно сразу рассылать отклики при старте контейнера
# Вынесено в отдельный скрипт, т.к. аргументы запуска не влезают в строку crontab
# /bin/bash /tmp/apply.sh

echo "[$(date)] Startup tasks finished."

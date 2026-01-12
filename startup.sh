#!/bin/bash
echo "[$(date)] Running startup tasks..."

# Выполняем цепочку
/usr/local/bin/python -m hh_applicant_tool -c /app/config refresh-token
sleep 10
/usr/local/bin/python -m hh_applicant_tool -c /app/config update-resumes
sleep 10
/usr/local/bin/python -m hh_applicant_tool -c /app/config apply-similar

echo "[$(date)] Startup tasks finished."

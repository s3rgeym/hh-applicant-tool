#!/bin/bash
echo "[$(date)] Running startup tasks..."

# Выполняем цепочку
/usr/local/bin/python -m hh_applicant_tool refresh-token
/usr/local/bin/python -m hh_applicant_tool update-resumes
/usr/local/bin/python -m hh_applicant_tool apply-similar

echo "[$(date)] Startup tasks finished."

#!/bin/bash
set -e

SYSTEM_PROMPT=$(cat /app/prompts/system.txt)
MESSAGE_PROMPT=$(cat /app/prompts/message.txt)

/usr/local/bin/python -m hh_applicant_tool apply-vacancies \
  -f \
  --use-ai \
  --ai-filter heavy \
  --ai-system "$SYSTEM_PROMPT" \
  --message-prompt "$MESSAGE_PROMPT" \
  --excluded-filter "продажи,sales,менеджер по продажам" \
  --experience noExperience

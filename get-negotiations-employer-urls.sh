#!/usr/bin/bash
# Я так раньше собирал ссылки на сайты работодателей, а теперь утилита сама все собирает
cd "$(dirname "$0")" || exit

page=0
per_page=100
while true; do
  output=$(hh-applicant-tool -vv call-api /negotiations "page=$page" "per_page=$per_page")
  jq -r '.items[].vacancy.employer.url' <<<"$output"
  pages=$(jq .pages <<<"$output")
  ((++page))
  if [ $page -ge "$pages" ]; then
    break
  fi
done

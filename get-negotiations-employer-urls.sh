#!/usr/bin/bash
cd "$(dirname "$0")"
. .venv/bin/activate

page=0
per_page=100
while true; do
  output=$(python -m hh_applicant_tool -vv call-api /negotiations "page=$page" "per_page=$per_page")
  jq -r '.items[].vacancy.employer.url' <<< "$output"
  pages=$(jq .pages <<< "$output")
  ((++page))
  if [ $page -ge $pages ]; then
    break
  fi
done

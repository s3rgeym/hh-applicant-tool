#!/usr/bin/bash
# ./get-negotiations-employer-site-urls.sh | grep -v '^$' | sort | uniq > sites.txt
# yay -S httpx-bin
# httpx -l sites.txt -json -o output.json -mr '\[branch "[^"]+"\]' -mc 200 -path /.git/config
# И кучу такого найдет https://sudo.team/.git/config
# Еще часто корень сайта в ХОМЯКЕ, БЛЕАТЬ, https://kub3.ru/.bash_history
cd "$(dirname "$0")"

page=0
per_page=100

while true; do
  output=$(hh-applicant-tool -vv call-api /negotiations \
    "page=$page" \
    "per_page=$per_page")
  urls=($(jq -r '.items[].vacancy.employer.url' <<< "$output"))
  total_pages=$(jq .pages <<< "$output")
  for url in "${urls[@]}"; do
    curl -s "$url" | jq -r .site_url
  done
  if ((++page >= total_pages)); then
    break
  fi
done

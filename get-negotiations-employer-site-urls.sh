#!/usr/bin/bash
# ./get-negotiations-employer-site-urls.sh | grep -v '^$' | sort | uniq > sites.txt
# yay -S httpx-bin
# httpx -l sites.txt -json -o output.json -mr '\[branch "[^"]+"\]' -mc 200 -path /.git/config
cd "$(dirname "$0")"
. .venv/bin/activate

page=0
per_page=100
while true; do
  output=$(python -m hh_applicant_tool -vv call-api /negotiations "page=$page" "per_page=$per_page")
  urls=($(jq -r '.items[].vacancy.employer.url' <<< "$output"))
  for url in "${urls[@]}"; do
    curl -s "$url" | jq -r .site_url
  done
  pages=$(jq .pages <<< "$output")
  ((++page))
  if [ $page -ge $pages ]; then
    break
  fi
done

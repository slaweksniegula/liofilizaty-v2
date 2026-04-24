#!/bin/bash
# Uruchamiany codziennie o 09:00 przez cron (lub ręcznie z cron_manager.py).
# Scrapuje ceny z Skalnika i importuje do API na VPS.

set -e

PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PROJECT="/Users/admin/Documents/Projekty N8N i Claude/Liofilizaty/liofilizaty-v2"
API_KEY="1f672643353f4389801f7212c4817e63274f013df3fbbb3f25647ef0300b5598"
API_URL="https://api.sniegula.com/prices/import"
JSON_TMP="/tmp/prices_liofilizaty.json"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === START ==="

cd "$PROJECT"
"$PYTHON" scraper.py --output-json "$JSON_TMP"

RESULT=$(curl -s -w "\nHTTP:%{http_code}" -X POST \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "@$JSON_TMP" \
  "$API_URL")

HTTP_CODE=$(echo "$RESULT" | grep "HTTP:" | cut -d: -f2)
BODY=$(echo "$RESULT" | grep -v "HTTP:")

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Import: HTTP $HTTP_CODE — $BODY"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === KONIEC ==="

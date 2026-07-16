#!/usr/bin/env bash
# Vex mesh monitor — polls inbox every 5s, prints new messages.
# Armed once per session. Keeps Vex listening.
set -euo pipefail

INBOX_URL="${VEX_MONITOR_URL:-http://localhost:8520/mesh/inbox}"
WHO="${VEX_MONITOR_WHO:-vex@bluce/uno}"
INTERVAL="${VEX_MONITOR_INTERVAL:-5}"
LAST_ID=0

echo "[monitor] armed — watching for $WHO every ${INTERVAL}s"

while true; do
  sleep "$INTERVAL"
  resp=$(curl -sf "$INBOX_URL?who=$WHO&n=5" 2>/dev/null) || continue
  msgs=$(echo "$resp" | python3 -c "
import sys,json
msgs=json.load(sys.stdin).get('messages',[])
for m in msgs:
    print(f'{m[\"id\"]}|[{m[\"at\"]}] {m[\"sender\"]}: {m[\"body\"][:150]}')
" 2>/dev/null) || continue
  if [ -n "$msgs" ]; then
    while IFS= read -r line; do
      id=$(echo "$line" | cut -d'|' -f1)
      if [ "$id" -gt "$LAST_ID" ] 2>/dev/null; then
        echo "[monitor] $(echo "$line" | cut -d'|' -f2-)"
        LAST_ID="$id"
      fi
    done <<< "$msgs"
  fi
done

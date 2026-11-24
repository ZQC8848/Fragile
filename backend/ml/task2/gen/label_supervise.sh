#!/usr/bin/env bash
# Run a resumable Claude labelling command until it finishes, waiting out the usage limit.
#   ml/task2/gen/label_supervise.sh <log file> -- uv run python -m ml.task2.gen.relabel_nora_v2
# Exit code 3 from the command = Claude's usage limit: probe `claude -p` every 10 minutes, restart when it answers.
# Any other non-zero exit: retry up to 5 times, then give up.
set -u
log="$1"; shift; [ "$1" = "--" ] && shift
fails=0
while true; do
  echo "[$(date '+%F %T')] start: $*" >> "$log"
  "$@" >> "$log" 2>&1
  code=$?
  echo "[$(date '+%F %T')] exit $code" >> "$log"
  if [ $code -eq 0 ]; then echo "[$(date '+%F %T')] DONE" >> "$log"; exit 0; fi
  if [ $code -eq 3 ]; then
    while true; do
      sleep 600
      if echo "Reply with OK." | claude -p --tools "" --no-session-persistence --model haiku 2>&1 | grep -qi "ok"; then
        echo "[$(date '+%F %T')] limit reset, restarting" >> "$log"; break
      fi
      echo "[$(date '+%F %T')] still limited" >> "$log"
    done
    continue
  fi
  fails=$((fails + 1))
  if [ $fails -ge 5 ]; then echo "[$(date '+%F %T')] GIVING UP after $fails failures" >> "$log"; exit $code; fi
  sleep 60
done

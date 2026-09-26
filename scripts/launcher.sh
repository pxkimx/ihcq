#!/bin/bash
# Launches the ihcq local UI and opens it in the default browser.
# Prefers the isolated "ihcq-dl" conda env (StarDist backend available);
# falls back to the base Anaconda Python (classical backend only).
PROJECT="${IHCQ_HOME:-@PROJECT@}"
LOG="$HOME/Library/Logs/ihcq.log"
if [ -x /opt/anaconda3/envs/ihcq-dl/bin/python3 ]; then
  PY=/opt/anaconda3/envs/ihcq-dl/bin/python3
else
  PY=/opt/anaconda3/bin/python3
fi
cd "$PROJECT" || { osascript -e 'display alert "IHCQ" message "Project folder not found: '"$PROJECT"'"'; exit 1; }
echo "[$(date '+%F %T')] starting with $PY" >> "$LOG"
"$PY" -m ihcq.app >> "$LOG" 2>&1 &
PID=$!
sleep 1.5
if ! kill -0 $PID 2>/dev/null; then
  osascript -e 'display alert "IHCQ could not start" message "Details are in ~/Library/Logs/ihcq.log"'
  exit 1
fi
wait $PID

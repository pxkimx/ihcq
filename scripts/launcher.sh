#!/bin/bash
# Launches the IHCq local UI and opens it in the default browser.
# Prefers the isolated .venv-dl (StarDist backend available);
# falls back to the base Anaconda Python (classical backend only).
# IHCq quits completely when its window is closed or this launcher is quit:
# the server watches this process (IHCQ_LAUNCHER_PID), and this process ends with the server.
# build_app.sh writes this checkout's folder in place of @PROJECT@ when it builds the app; IHCQ_HOME overrides it.
PROJECT="${IHCQ_HOME:-@PROJECT@}"
LOG="$HOME/Library/Logs/ihcq.log"
if [ -x "$PROJECT/.venv-dl/bin/python3" ]; then
  PY="$PROJECT/.venv-dl/bin/python3"
elif [ -x /opt/anaconda3/envs/ihcq-dl/bin/python3 ]; then
  PY=/opt/anaconda3/envs/ihcq-dl/bin/python3
else
  PY=/opt/anaconda3/bin/python3
fi
cd "$PROJECT" || { osascript -e 'display alert "IHCq" message "Project folder not found: '"$PROJECT"'"'; exit 1; }
echo "[$(date '+%F %T')] starting with $PY" >> "$LOG"
export IHCQ_LAUNCHER_PID=$$
"$PY" -m ihcq.app >> "$LOG" 2>&1 &
PID=$!
trap 'kill -TERM $PID 2>/dev/null; wait $PID 2>/dev/null; exit 0' TERM INT HUP
sleep 1.5
if ! kill -0 $PID 2>/dev/null; then
  wait $PID; [ $? -eq 0 ] && exit 0      # IHCq was already open: the browser was pointed at it
  osascript -e 'display alert "IHCq could not start" message "Details are in ~/Library/Logs/ihcq.log"'
  exit 1
fi
wait $PID

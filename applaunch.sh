#!/bin/bash
exec >>/tmp/whispertool_launcher.log 2>&1
echo "--- applet launch $(date '+%H:%M:%S') ---"
if /usr/bin/pgrep -f "main\.py$" >/dev/null 2>&1; then
  echo "already running"
  /usr/bin/touch "$HOME/whispertool/.show" 2>/dev/null || true
  exit 0
fi
PY="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
cd "$HOME/whispertool" || exit 1
export SSL_CERT_FILE="$("$PY" -c 'import certifi; print(certifi.where())' 2>/dev/null)"
export HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo "starting app (child of applet)..."
/usr/bin/arch -arm64 "$PY" -u main.py

#!/bin/zsh
set -e

APP_DIR="/Users/macb/Calendar-Scanner"
PORT="8510"
URL="http://localhost:${PORT}"

cd "$APP_DIR"

if command -v curl >/dev/null 2>&1 && curl -fsS "${URL}/_stcore/health" >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

python3 - <<'PY'
import importlib.util
import subprocess
import sys

required = {
    "streamlit": "streamlit",
    "ib_insync": "ib_insync",
    "pandas": "pandas",
    "numpy": "numpy",
    "plotly": "plotly",
    "scipy": "scipy",
    "toml": "toml",
    "nest_asyncio": "nest_asyncio",
}

missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
if missing:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
PY

open "$URL"
exec python3 -m streamlit run app.py --server.port "$PORT" --server.headless true

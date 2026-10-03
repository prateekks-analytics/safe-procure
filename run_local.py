"""Run Safe Procure locally.

Keys are read from environment variables GROQ_API_KEY / GEMINI_API_KEY, or from a
KEY=value file whose path is given in SAFE_PROCURE_KEYS (kept outside the project folder).

    python run_local.py            # http://127.0.0.1:8765
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

keys_file = os.environ.get("SAFE_PROCURE_KEYS")
if keys_file and Path(keys_file).exists():
    for line in Path(keys_file).read_text(encoding="utf-8").splitlines():
        k, _, v = line.strip().partition("=")
        if k and v and not os.environ.get(k):
            os.environ[k] = v

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run("safeprocure.server:app", host="127.0.0.1", port=port, log_level="warning")

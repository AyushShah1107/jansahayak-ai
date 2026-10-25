"""Boot the real Uvicorn server in-process and hit it over HTTP (no shell background jobs)."""
import sys, threading, time
from pathlib import Path
import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import main  # noqa

config = uvicorn.Config(main.app, host="127.0.0.1", port=8123, log_level="warning")
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()

for _ in range(50):
    if server.started:
        break
    time.sleep(0.1)

base = "http://127.0.0.1:8123"
with httpx.Client(timeout=10) as c:
    h = c.get(base + "/api/health")
    print("GET /api/health ->", h.status_code, "sarvam_configured=", h.json()["sarvam_configured"])
    idx = c.get(base + "/")
    print("GET / ->", idx.status_code, "| contains title:", "JanSahayak AI" in idx.text)
    css = c.get(base + "/styles.css")
    js = c.get(base + "/app.js")
    print("GET /styles.css ->", css.status_code, "| GET /app.js ->", js.status_code)
    print("JS bundle contains no key pattern:", "api-subscription-key" not in js.text and "SARVAM_API_KEY=" not in js.text)
    d = c.get(base + "/api/demo")
    print("GET /api/demo ->", d.status_code, "| sample:", d.json().get("is_sample"))
    a = c.post(base + "/api/ask", json={"question": "Which documents are required?", "language": "hi-IN", "doc_id": d.json()["doc_id"]})
    print("POST /api/ask ->", a.status_code, "| error:", a.json().get("error"))

server.should_exit = True
t.join(timeout=5)
print("server stopped cleanly")

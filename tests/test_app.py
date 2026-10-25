"""Functional tests for JanSahayak AI backend (run without a live server).

Run from the backend directory:  python ../tests/test_app.py
or:  cd backend && python -m pytest ../tests/test_app.py -q
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
TESTS = Path(__file__).resolve().parent

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


print("=== JanSahayak AI functional tests ===\n")

# 1. Health
r = client.get("/api/health")
h = r.json()
check("Health endpoint returns ok", r.status_code == 200 and h["status"] == "ok", str(h.get("version")))
check("Health does not leak secrets", "SARVAM_API_KEY" not in r.text and "api-subscription-key" not in r.text)
check("Health reports AI config status", "sarvam_configured" in h, f"sarvam_configured={h['sarvam_configured']}")
print(f"     AI configured on this server: {h['sarvam_configured']}\n")

# 2. Demo document
r = client.get("/api/demo")
demo = r.json()
check("Demo document loads", r.status_code == 200 and demo["status"] == "ok", demo.get("message", ""))
check("Demo flagged as sample data", demo.get("is_sample") is True)
doc_id = demo.get("doc_id")

# 3. TXT extraction
r = client.post(
    "/api/documents/extract",
    files={"file": ("notice.txt", (TESTS / ".." / "samples" / "demo_scholarship_notice.txt").read_bytes(), "text/plain")},
)
check("TXT extraction works", r.status_code == 200 and r.json()["status"] == "ok", r.json().get("message", ""))
txt_doc_id = r.json().get("doc_id")

# 4. PDF extraction
r = client.post("/api/documents/extract", files={"file": ("sample_notice.pdf", (TESTS / "sample_notice.pdf").read_bytes(), "application/pdf")})
pj = r.json()
check("PDF text extraction works", r.status_code == 200 and pj["status"] == "ok", pj.get("message", ""))

# 5. Invalid file type
r = client.post("/api/documents/extract", files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")})
check("Invalid file type rejected (415)", r.status_code == 415, r.json().get("detail", ""))

# 6. Empty/textless PDF
r = client.post("/api/documents/extract", files={"file": ("blank.pdf", (TESTS / "blank.pdf").read_bytes(), "application/pdf")})
check("Textless PDF handled honestly", r.status_code == 200 and r.json()["status"] == "no_text", r.json().get("message", "")[:70])

# 7. Empty file
r = client.post("/api/documents/extract", files={"file": ("empty.txt", b"", "text/plain")})
check("Empty file rejected (400)", r.status_code == 400, r.json().get("detail", ""))

# 8. Ask (needs key). Without a key we expect a clear 503, not a fake answer.
r = client.post("/api/ask", json={"question": "Which documents are required?", "language": "hi-IN", "doc_id": doc_id})
if h["sarvam_configured"]:
    ok = r.status_code == 200 and len(r.json().get("answer", "")) > 0
    check("Ask returns a grounded answer", ok, (r.json().get("answer", "")[:80] + "...") if ok else r.text[:120])
else:
    j = r.json()
    check("Ask returns clear config error when no key", r.status_code == 503 and j.get("error") == "ai_not_configured", j.get("message", "")[:70])

# 9. Ask with unknown doc id
r = client.post("/api/ask", json={"question": "hi", "language": "hi-IN", "doc_id": "nope"})
check("Unknown document id -> 404", r.status_code == 404)

# 10. Bad language
r = client.post("/api/ask", json={"question": "hi", "language": "xx-XX", "doc_id": doc_id})
check("Unsupported language -> 400", r.status_code == 400)

# 11. Content generate
r = client.post("/api/content/generate", json={"format": "whatsapp", "language": "hi-IN", "doc_id": doc_id})
if h["sarvam_configured"]:
    check("WhatsApp content generated", r.status_code == 200 and len(r.json().get("content", "")) > 0)
else:
    check("Content generate config error when no key", r.status_code == 503, r.json().get("message", "")[:60])

# 12. Bad format
r = client.post("/api/content/generate", json={"format": "novel", "language": "hi-IN", "doc_id": doc_id})
check("Unsupported format -> 400", r.status_code == 400)

# 13. Voice endpoints
r = client.post("/api/voice/speak", json={"text": "नमस्ते", "language": "hi-IN"})
check("Speak endpoint responds (200 audio or 503 no-key)", r.status_code in (200, 503), f"status={r.status_code}")
r = client.post("/api/voice/transcribe", files={"file": ("a.webm", b"notreal", "audio/webm")}, data={"language": "hi-IN"})
check("Transcribe endpoint responds (200 or clear error)", r.status_code in (200, 422, 502, 503), f"status={r.status_code}")

# 14. Static frontend served
r = client.get("/")
check("Frontend served at /", r.status_code == 200 and "JanSahayak AI" in r.text)

print("\n=== Summary ===")
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)

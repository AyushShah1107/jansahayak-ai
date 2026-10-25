# JanSahayak AI

**Government information, explained in your language.**

An AI assistant for Indian citizens: upload a government or public document, ask a
question in your own language, understand a grounded answer, and turn it into
something you can share — a WhatsApp message, an announcement, a checklist, FAQs or
an audio script.

> This is an independent AI tool for a hackathon. It is **not** an official
> government service and is not affiliated with any government body. Always verify
> important decisions with the relevant official source.

---

## Problem

Government notices, scheme circulars and public announcements are long, formal and
often only in English. Many citizens — farmers, students, workers and families —
find them hard to read and harder to act on, and would rather ask a question in
Hindi or another Indian language than type a formal query.

## Solution

JanSahayak AI does three tightly integrated things on top of one shared pipeline:

1. **Voice agent** — ask a question by voice or text, in your language, and listen to the answer.
2. **Document agent** — upload a PDF/TXT, extract the text, and get answers grounded only in that document.
3. **Content studio** — turn the document into a WhatsApp message, announcement, checklist, FAQ set or audio script.

The uploaded document is the single source of factual information. If something is
not in the document, the app says so instead of inventing it.

## Intended users

Farmers reading scheme notices, students reading scholarship notices, families reading
public-service announcements, workers reading official notifications, and anyone who
prefers speaking in Hindi or another Indian language.

## Features

- Upload **PDF or TXT** (validated type and size, max 10 MB) with drag-and-drop.
- **Text extraction** via `pypdf` (PDF) and the standard library (TXT), with an honest
  message for scanned/empty PDFs (no fake "extracted" state).
- **Document-grounded Q&A** in 6 languages, with suggested questions, source passage
  and page reference, and explicit "not in the document" behaviour.
- **Content Studio** with 6 output formats, editable output, **Copy** and **Download as TXT**.
- **Voice input**: Sarvam **Saaras** speech-to-text (recorded in the browser, transcribed server-side),
  with browser-native speech recognition as a clearly-labelled fallback when no key is set.
- **Voice output**: Sarvam **Bulbul** text-to-speech, with the browser's speech synthesis as a
  clearly-labelled fallback.
- **Sample demo notice** bundled locally (fictional data) so judges can explore without a file.
- Responsive, accessible UI (mobile / tablet / desktop), loading states, error states,
  disabled/blocked duplicate submissions, privacy notice and disclaimer.

## Languages

Hindi, English, Bengali, Tamil, Telugu, Marathi — all six are covered by Sarvam-105B (chat),
Saaras (STT) and Bulbul (TTS).

## Architecture

```
Browser (static SPA: index.html + styles.css + app.js)
        |  fetch()  (same origin; no API key in the browser)
        v
FastAPI backend (backend/main.py)
        |-- documents.py      extract + in-memory store + passage selection
        |-- prompts.py        grounded system prompt + content formats
        |-- sarvam_client.py  server-side Sarvam REST calls
        v
Sarvam AI  (api.sarvam.ai)
```

Single-origin deployment: FastAPI serves both the API and the static frontend, which
removes CORS problems. The frontend is plain HTML/CSS/JS (no build step) — a deliberate
choice for reliability and speed within the time limit; it can be swapped for a Vite/React
frontend later without changing the API.

### Sarvam AI integration (documented endpoints)

| Capability | Endpoint | Model |
|---|---|---|
| Chat / Q&A / content | `POST https://api.sarvam.ai/v1/chat/completions` | `sarvam-105b` |
| Speech to text | `POST https://api.sarvam.ai/speech-to-text` (multipart) | `saaras:v4`, mode `transcribe` |
| Text to speech | `POST https://api.sarvam.ai/text-to-speech` | `bulbul:v3`, speaker `shubh` |

Authentication uses the `api-subscription-key` header. All Sarvam calls are made
**server-side only**.

## Technology stack

- Backend: Python 3.12, FastAPI, Uvicorn, httpx, pypdf, python-multipart.
- Frontend: HTML5, CSS3, vanilla JavaScript (Web Speech API / MediaRecorder where relevant).
- AI: Sarvam AI REST APIs.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status + which features are configured (no secrets). |
| GET | `/api/demo` | Load the bundled sample notice, returns a `doc_id`. |
| POST | `/api/documents/extract` | Validate + extract text, returns `doc_id` and metadata. |
| POST | `/api/ask` | Grounded answer from a `doc_id` (or raw `text`). |
| POST | `/api/content/generate` | Generate one content format from the document. |
| POST | `/api/voice/transcribe` | Sarvam Saaras speech-to-text. |
| POST | `/api/voice/speak` | Sarvam Bulbul text-to-speech (returns WAV). |

## Local setup

```bash
git clone https://github.com/AyushShah1107/jansahayak-ai.git
cd jansahayak-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env          # then edit .env and add your key
set -a; source .env; set +a   # or: export SARVAM_API_KEY=...
uvicorn main:app --reload --app-dir backend --port 8000
```

Open http://localhost:8000 . The backend serves the frontend, so there is nothing else to run.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `SARVAM_API_KEY` | Yes for AI features | Server-side only. Get one at https://dashboard.sarvam.ai |
| `CORS_ORIGINS` | No | Comma-separated origins; defaults to `*`. |

The app runs without a key: upload, extraction, the demo document and the whole UI work;
AI-dependent actions return a clear configuration error. `.env` is git-ignored; only
`.env.example` (placeholders) is committed.

## Testing

```bash
cd backend
python ../tests/test_app.py        # 18 functional checks (no live server needed)
python ../tests/smoke_server.py    # boots real Uvicorn and hits it over HTTP
```

Test cases covered: health, demo load, TXT extraction, PDF extraction, invalid file type
(415), textless/empty PDF (honest message), empty file (400), ask with/without key,
unknown document id (404), unsupported language (400), content generation, unsupported
format (400), voice endpoints, static frontend serving, and a check that no key pattern
appears in the served JS.

To exercise AI features for real, set `SARVAM_API_KEY` and re-run.

## Deployment

The app is a single FastAPI service (API + static frontend). Any host that runs a Python
web process works — Render, Railway, Fly.io, or a container platform.

1. Push the repo to GitHub.
2. Create a web service; build command `pip install -r backend/requirements.txt`.
3. Start command `uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir backend`.
4. Set `SARVAM_API_KEY` in the host's environment settings (never in the repo).
5. Open the public URL; check `GET /api/health` returns `"status":"ok"`.

For a split frontend/backend deployment, set `CORS_ORIGINS` on the backend and set
`window.JANSAHAYAK_API_BASE` to the backend URL before `app.js` loads (see `index.html`).

## Known limitations

- **No Sarvam API key was available in the build environment**, so live AI requests were
  not executed here; AI paths were verified to fail cleanly with a clear configuration
  error and the code targets the documented endpoints. Set the key and re-test.
- Scanned image PDFs are not OCR'd (Sarvam Vision OCR was out of scope for the time budget);
  the app reports that no text was extracted instead of pretending otherwise.
- Passage selection for long documents uses simple keyword overlap, not embeddings/RAG.
- Documents are held in memory and expire after 1 hour; they are not persisted.
- The interface-language toggle switches the document `lang` and labels partially; full UI
  translation of every label is not yet implemented (response language is fully supported).

## Privacy and safety

- The Sarvam API key lives only in server environment variables and is never sent to the browser.
- Uploaded documents are processed in memory for the session and expire automatically; they are
  not written to permanent storage. Users are advised not to upload unnecessary sensitive data.
- Document text is sent to Sarvam AI to generate responses when AI features are used.
- Uploaded documents are treated as **untrusted input**: the system prompt instructs the model to
  ignore any instructions embedded in a document.
- The app never claims a benefit was approved or an application submitted, and reminds users to
  verify high-impact details with the official source.

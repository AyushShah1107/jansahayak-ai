"""JanSahayak AI backend - FastAPI application.

Serves the static frontend and a small JSON API. All Sarvam AI calls are made
server-side; the API key never leaves the server.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import documents as docs
import sarvam_client as sarvam
from prompts import FORMAT_LABELS, LANGUAGE_NAMES, content_messages, qa_messages

APP_VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

app = FastAPI(title="JanSahayak AI", version=APP_VERSION)

# CORS: allow configurable origins for split frontend/backend deployments.
_origins = os.environ.get("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",")] if _origins else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _lang(code: str) -> str:
    if code not in LANGUAGE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {code}")
    return code


def _ai_error(exc: sarvam.SarvamError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": exc.code,
            "message": exc.message,
            "ai_configured": sarvam.is_configured(),
        },
    )


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": "JanSahayak AI",
        "version": APP_VERSION,
        "sarvam_configured": sarvam.is_configured(),
        "chat_model": sarvam.CHAT_MODEL,
        "stt_model": sarvam.STT_MODEL,
        "tts_model": sarvam.TTS_MODEL,
        "languages": list(LANGUAGE_NAMES.keys()),
        "features": {
            "document_extraction": True,
            "question_answering": sarvam.is_configured(),
            "content_generation": sarvam.is_configured(),
            "speech_to_text": sarvam.is_configured(),
            "text_to_speech": sarvam.is_configured(),
        },
    }


# --------------------------------------------------------------------------- #
# Document extraction
# --------------------------------------------------------------------------- #
@app.post("/api/documents/extract")
async def extract_document(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "document"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in docs.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF or TXT file.",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > docs.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. Maximum size is {docs.MAX_FILE_BYTES // (1024*1024)} MB.",
        )

    try:
        pages = docs.extract_pages(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not pages:
        # Scanned PDF or empty text: be honest, do not pretend extraction worked.
        return {
            "status": "no_text",
            "filename": filename,
            "message": (
                "No readable text could be extracted from this file. It may be a scanned "
                "image PDF. Please upload a text-based PDF or a TXT file."
            ),
        }

    doc = docs.store_document(filename, pages)
    preview = doc.full_text[:600]
    return {
        "status": "ok",
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "char_count": doc.char_count,
        "page_count": len(pages),
        "preview": preview,
        "message": f"Extracted {doc.char_count:,} characters from {len(pages)} page(s).",
    }


# --------------------------------------------------------------------------- #
# Ask (document-grounded question answering)
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    language: str = "hi-IN"
    doc_id: str | None = None
    text: str | None = Field(default=None, max_length=docs.MAX_CONTEXT_CHARS)


@app.post("/api/ask")
async def ask(req: AskRequest):
    _lang(req.language)
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a question.")

    if req.doc_id:
        doc = docs.get_document(req.doc_id)
        if doc is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found or expired. Please upload it again.",
            )
        context, page_hint = docs.select_passages(doc, question)
        excerpt, excerpt_page = docs.excerpt_for(doc, "", question)
        analysed = (
            "full document" if doc.char_count <= docs.MAX_CONTEXT_CHARS else "selected relevant passages"
        )
    elif req.text:
        context, page_hint = req.text, ""
        excerpt, excerpt_page = req.text[:400], None
        analysed = "provided text"
    else:
        raise HTTPException(status_code=400, detail="No document or text provided.")

    if not context.strip():
        raise HTTPException(status_code=422, detail="There is no text to answer from.")

    try:
        answer = await sarvam.chat_completion(qa_messages(question, context, req.language, page_hint))
    except sarvam.SarvamError as exc:
        return _ai_error(exc)

    return {
        "status": "ok",
        "answer": answer,
        "language": req.language,
        "source_excerpt": excerpt,
        "source_page": excerpt_page,
        "analysed": analysed,
        "grounded": True,
    }


# --------------------------------------------------------------------------- #
# Content Studio
# --------------------------------------------------------------------------- #
class ContentRequest(BaseModel):
    format: str = "simple"
    language: str = "hi-IN"
    doc_id: str | None = None
    text: str | None = Field(default=None, max_length=docs.MAX_CONTEXT_CHARS)


@app.post("/api/content/generate")
async def content_generate(req: ContentRequest):
    _lang(req.language)
    if req.format not in FORMAT_LABELS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {req.format}")

    if req.doc_id:
        doc = docs.get_document(req.doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found or expired. Upload it again.")
        context, page_hint = docs.select_passages(doc, FORMAT_LABELS[req.format])
    elif req.text:
        context, page_hint = req.text, ""
    else:
        raise HTTPException(status_code=400, detail="No document or text provided.")

    if not context.strip():
        raise HTTPException(status_code=422, detail="There is no text to generate from.")

    try:
        out = await sarvam.chat_completion(
            content_messages(context, req.format, req.language, page_hint), max_tokens=1500
        )
    except sarvam.SarvamError as exc:
        return _ai_error(exc)

    return {
        "status": "ok",
        "format": req.format,
        "language": req.language,
        "content": out,
    }


# --------------------------------------------------------------------------- #
# Voice
# --------------------------------------------------------------------------- #
@app.post("/api/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...), language: str = Form("hi-IN")
) -> dict:
    _lang(language)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="No audio received.")
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio clip is too large (max 15 MB).")
    try:
        transcript = await sarvam.speech_to_text(file.filename or "audio.webm", content, language_code=language)
    except sarvam.SarvamError as exc:
        return _ai_error(exc)
    return {"status": "ok", "transcript": transcript, "language": language, "engine": "sarvam-saaras"}


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2400)
    language: str = "hi-IN"


@app.post("/api/voice/speak")
async def voice_speak(req: SpeakRequest):
    _lang(req.language)
    try:
        audio = await sarvam.text_to_speech(req.text, language_code=req.language)
    except sarvam.SarvamError as exc:
        return _ai_error(exc)
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"X-Voice-Engine": "sarvam-bulbul-v3"},
    )


# --------------------------------------------------------------------------- #
# Demo document (bundled locally, no network dependency)
# --------------------------------------------------------------------------- #
DEMO_FILE = BASE_DIR.parent / "samples" / "demo_scholarship_notice.txt"


@app.get("/api/demo")
def demo_document() -> dict:
    if not DEMO_FILE.exists():
        raise HTTPException(status_code=404, detail="Demo document is unavailable.")
    pages = docs.extract_pages(DEMO_FILE.name, DEMO_FILE.read_bytes())
    doc = docs.store_document("demo_scholarship_notice.txt (sample data)", pages)
    return {
        "status": "ok",
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "char_count": doc.char_count,
        "page_count": len(pages),
        "preview": doc.full_text[:600],
        "message": "Sample demonstration notice loaded (fictional data).",
        "is_sample": True,
    }


# --------------------------------------------------------------------------- #
# Self-test: proves the Sarvam AI path end-to-end over a simple GET.
# Runs ONE fixed question against the bundled demo notice and caches the result
# for 5 minutes, so a public GET cannot burn credits in a loop.
# --------------------------------------------------------------------------- #
_SELFTEST: dict = {}
_SELFTEST_QUESTION = "Which documents are required?"
_SELFTEST_TTL = 300


@app.get("/api/selftest")
async def selftest():
    now = time.time()
    cached = _SELFTEST.get("result")
    if cached and now - _SELFTEST.get("at", 0) < _SELFTEST_TTL:
        return {**cached, "cached": True}

    if not sarvam.is_configured():
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error": "ai_not_configured",
                "message": "No SARVAM_API_KEY configured on the server.",
                "ai_configured": False,
            },
        )
    if not DEMO_FILE.exists():
        raise HTTPException(status_code=500, detail="Demo document missing.")

    try:
        pages = docs.extract_pages(DEMO_FILE.name, DEMO_FILE.read_bytes())
        doc = docs.store_document("demo_scholarship_notice.txt (sample data)", pages)
        context, page_hint = docs.select_passages(doc, _SELFTEST_QUESTION)
        answer = await sarvam.chat_completion(
            qa_messages(_SELFTEST_QUESTION, context, "en-IN", page_hint)
        )
    except sarvam.SarvamError as exc:
        return _ai_error(exc)

    result = {
        "status": "ok",
        "question": _SELFTEST_QUESTION,
        "answer": answer,
        "language": "en-IN",
        "model": sarvam.CHAT_MODEL,
        "ai_configured": True,
    }
    _SELFTEST["result"] = result
    _SELFTEST["at"] = now
    return {**result, "cached": False}


# --------------------------------------------------------------------------- #
# Static frontend (single origin). Mounted last so /api routes win.
# --------------------------------------------------------------------------- #
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

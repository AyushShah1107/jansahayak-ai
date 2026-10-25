"""Thin async client for the Sarvam AI REST APIs.

All calls happen server-side. The API key is read from the SARVAM_API_KEY
environment variable and is never returned to clients or written to logs.

Documented endpoints used (docs.sarvam.ai):
  - Chat completion : POST https://api.sarvam.ai/v1/chat/completions   (model sarvam-105b)
  - Speech to text  : POST https://api.sarvam.ai/speech-to-text        (model saaras:v4, multipart)
  - Text to speech  : POST https://api.sarvam.ai/text-to-speech        (model bulbul:v3)
Auth header: `api-subscription-key`.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

BASE_URL = "https://api.sarvam.ai"
CHAT_MODEL = "sarvam-105b"
STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v3"
TTS_SPEAKER = "shubh"

# Language codes supported by the models we use (all 6 UI languages).
SUPPORTED_LANGUAGES = {
    "hi-IN": "Hindi",
    "en-IN": "English",
    "bn-IN": "Bengali",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "mr-IN": "Marathi",
}


class SarvamError(Exception):
    """Raised when Sarvam returns an error. Message is safe to show to users."""

    def __init__(self, message: str, status: int = 502, code: str = "sarvam_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def api_key() -> str | None:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    return key or None


def is_configured() -> bool:
    return api_key() is not None


def _headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise SarvamError(
            "AI features need a Sarvam API key. The server has no SARVAM_API_KEY configured.",
            status=503,
            code="ai_not_configured",
        )
    return {"api-subscription-key": key}


def _extract_error(resp: httpx.Response) -> str:
    """Turn an error response into a short, secret-free message."""
    if resp.status_code == 401 or resp.status_code == 403:
        return "Sarvam rejected the API key (authentication failed). Check SARVAM_API_KEY."
    if resp.status_code == 429:
        return "Sarvam rate limit reached. Please wait a moment and try again."
    if resp.status_code == 400:
        return "Sarvam could not process the request (bad request). Please adjust the input."
    return f"Sarvam API error (HTTP {resp.status_code}). Please try again shortly."


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    timeout: float = 60.0,
) -> str:
    """Call the Sarvam chat completion API and return the assistant text."""
    headers = {**_headers(), "Content-Type": "application/json"}
    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{BASE_URL}/v1/chat/completions", headers=headers, json=payload)
    except httpx.TimeoutException:
        raise SarvamError("The AI service timed out. Please try again.", status=504, code="timeout")
    except httpx.HTTPError:
        raise SarvamError("Could not reach the AI service. Check the network.", status=502)

    if resp.status_code != 200:
        raise SarvamError(_extract_error(resp), status=502, code="sarvam_http_error")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise SarvamError("The AI service returned an unexpected response.", status=502)
    if not content or not content.strip():
        raise SarvamError("The AI service returned an empty answer. Please try again.", status=502)
    return content.strip()


async def speech_to_text(
    filename: str, content: bytes, *, language_code: str = "hi-IN", timeout: float = 60.0
) -> str:
    """Transcribe audio using Saaras. Returns the transcript text."""
    headers = _headers()
    files = {"file": (filename, content)}
    data = {"model": STT_MODEL, "mode": "transcribe", "language_code": language_code}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{BASE_URL}/speech-to-text", headers=headers, files=files, data=data
            )
    except httpx.TimeoutException:
        raise SarvamError("Speech recognition timed out. Please try a shorter clip.", status=504)
    except httpx.HTTPError:
        raise SarvamError("Could not reach the speech service.", status=502)

    if resp.status_code != 200:
        raise SarvamError(_extract_error(resp), status=502)
    try:
        transcript = resp.json().get("transcript", "")
    except ValueError:
        raise SarvamError("The speech service returned an unexpected response.", status=502)
    if not transcript.strip():
        raise SarvamError("No speech could be recognised in the audio.", status=422)
    return transcript.strip()


async def text_to_speech(text: str, *, language_code: str = "hi-IN", timeout: float = 60.0) -> bytes:
    """Convert text to speech using Bulbul. Returns WAV audio bytes."""
    headers = {**_headers(), "Content-Type": "application/json"}
    payload = {
        "text": text[:2400],
        "language_code": language_code,
        "model": TTS_MODEL,
        "speaker": TTS_SPEAKER,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{BASE_URL}/text-to-speech", headers=headers, json=payload)
    except httpx.TimeoutException:
        raise SarvamError("Voice generation timed out. Please try again.", status=504)
    except httpx.HTTPError:
        raise SarvamError("Could not reach the voice service.", status=502)

    if resp.status_code != 200:
        raise SarvamError(_extract_error(resp), status=502)
    try:
        audios = resp.json().get("audios") or []
        if not audios:
            raise ValueError("no audio")
        return base64.b64decode("".join(audios))
    except ValueError:
        raise SarvamError("The voice service returned no audio.", status=502)

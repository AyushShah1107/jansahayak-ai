"""Document extraction, temporary storage and lightweight passage retrieval.

No vector database: text is extracted, split into bounded passages and the
passages most relevant to the question (by simple keyword overlap) are sent to
the model. What was actually sent is reported back, so the app never implies the
whole document was analysed when only part of it was.
"""

from __future__ import annotations

import io
import re
import time
import uuid
from dataclasses import dataclass, field

from pypdf import PdfReader

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".txt"}
PASSAGE_CHARS = 1200
MAX_CONTEXT_CHARS = 6000
DOC_TTL_SECONDS = 60 * 60  # in-memory documents live for one hour


@dataclass
class StoredDocument:
    doc_id: str
    filename: str
    pages: list[tuple[int, str]] = field(default_factory=list)  # (page_number, text)
    created_at: float = field(default_factory=time.time)

    @property
    def full_text(self) -> str:
        return "\n\n".join(t for _, t in self.pages).strip()

    @property
    def char_count(self) -> int:
        return sum(len(t) for _, t in self.pages)


_DOCS: dict[str, StoredDocument] = {}


def _cleanup() -> None:
    now = time.time()
    for doc_id in [k for k, v in _DOCS.items() if now - v.created_at > DOC_TTL_SECONDS]:
        _DOCS.pop(doc_id, None)


def store_document(filename: str, pages: list[tuple[int, str]]) -> StoredDocument:
    _cleanup()
    doc = StoredDocument(doc_id=uuid.uuid4().hex, filename=filename, pages=pages)
    _DOCS[doc.doc_id] = doc
    return doc


def get_document(doc_id: str) -> StoredDocument | None:
    _cleanup()
    return _DOCS.get(doc_id)


def extract_pages(filename: str, content: bytes) -> list[tuple[int, str]]:
    """Extract (page_number, text) tuples. Raises ValueError on unsupported/empty."""
    lower = filename.lower()
    if lower.endswith(".txt"):
        text = _decode_text(content)
        return [(1, text)] if text.strip() else []

    if lower.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception:
            raise ValueError("This PDF could not be opened. It may be corrupted.")
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password-protected and cannot be read.")
        pages: list[tuple[int, str]] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            if txt.strip():
                pages.append((i, _normalise(txt)))
        return pages

    raise ValueError("Unsupported file type. Please upload a PDF or TXT file.")


def _decode_text(content: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return _normalise(content.decode(enc))
        except UnicodeDecodeError:
            continue
    return _normalise(content.decode("utf-8", errors="ignore"))


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _tokenise(text: str) -> set[str]:
    words = re.findall(r"[\w\u0900-\u097F\u0980-\u09FF\u0B80-\u0BFF\u0C00-\u0C7F]+", text.lower())
    stop = {
        "the", "a", "an", "is", "are", "of", "to", "in", "on", "for", "and", "or", "what",
        "which", "who", "how", "this", "that", "it", "do", "does", "i", "my", "me", "ka",
        "ki", "ke", "hai", "kya", "kya", "he", "है", "का", "की", "के", "क्या",
    }
    return {w for w in words if w not in stop and len(w) > 1}


def select_passages(doc: StoredDocument, question: str) -> tuple[str, str]:
    """Return (context_text, page_hint) using keyword-overlap passage selection."""
    passages: list[tuple[int, str]] = []
    for page_no, text in doc.pages:
        for i in range(0, len(text), PASSAGE_CHARS):
            chunk = text[i : i + PASSAGE_CHARS].strip()
            if chunk:
                passages.append((page_no, chunk))

    if not passages:
        return "", ""

    if len(doc.full_text) <= MAX_CONTEXT_CHARS:
        pages_used = sorted({p for p, _ in passages})
        hint = _page_hint(pages_used)
        return doc.full_text[:MAX_CONTEXT_CHARS], hint

    q_tokens = _tokenise(question)
    scored = []
    for idx, (page_no, chunk) in enumerate(passages):
        overlap = len(q_tokens & _tokenise(chunk))
        scored.append((overlap, idx, page_no, chunk))

    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen, total, pages_used = [], 0, set()
    for overlap, _idx, page_no, chunk in scored:
        if total + len(chunk) > MAX_CONTEXT_CHARS and chosen:
            break
        chosen.append((_idx, page_no, chunk))
        total += len(chunk)
        pages_used.add(page_no)
        if len(chosen) >= 5:
            break

    chosen.sort(key=lambda x: x[0])
    context = "\n\n[...]\n\n".join(c for _, _, c in chosen)
    return context, _page_hint(sorted(pages_used))


def _page_hint(pages: list[int]) -> str:
    if not pages:
        return ""
    if len(pages) == 1:
        return f"page {pages[0]}"
    return "pages " + ", ".join(str(p) for p in pages)


def excerpt_for(doc: StoredDocument, answer_terms: str, question: str) -> tuple[str, int | None]:
    """Pick a short source excerpt most related to the question, plus its page."""
    q_tokens = _tokenise(question)
    best = (0, None, "")
    for page_no, text in doc.pages:
        for i in range(0, len(text), PASSAGE_CHARS):
            chunk = text[i : i + PASSAGE_CHARS].strip()
            if not chunk:
                continue
            score = len(q_tokens & _tokenise(chunk))
            if score > best[0]:
                best = (score, page_no, chunk)
    if best[2]:
        snippet = best[2][:400].strip()
        if len(best[2]) > 400:
            snippet += "…"
        return snippet, best[1]
    return "", None

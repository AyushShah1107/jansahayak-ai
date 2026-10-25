/* JanSahayak AI — frontend logic.
   All AI calls go to our own backend; the Sarvam key never reaches the browser. */
(() => {
  "use strict";

  const API = (window.JANSAHAYAK_API_BASE || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);

  const state = {
    docId: null,
    filename: null,
    sarvamConfigured: false,
    lastAnswer: "",
    busy: false,
    recording: false,
    mediaRecorder: null,
    chunks: [],
  };

  /* ----------------------------- helpers ----------------------------- */
  function toast(msg, isErr = false) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.className = "toast"), 3800);
  }

  function setBusy(btn, busy, label) {
    if (!btn) return;
    if (busy) {
      btn._orig = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spin"></span> ${label || "Working…"}`;
    } else {
      btn.disabled = false;
      if (btn._orig) btn.innerHTML = btn._orig;
    }
  }

  async function api(path, opts = {}) {
    const res = await fetch(API + path, opts);
    const ct = res.headers.get("content-type") || "";
    if (!res.ok) {
      let msg = `Request failed (${res.status}).`;
      if (ct.includes("application/json")) {
        try {
          const j = await res.json();
          msg = j.message || j.detail || msg;
          if (j.error === "ai_not_configured") {
            msg = "AI features are not configured on the server (no Sarvam API key). You can still upload documents and browse the interface.";
          }
        } catch (_) {}
      }
      const err = new Error(typeof msg === "string" ? msg : "Request failed.");
      err.status = res.status;
      throw err;
    }
    return ct.includes("application/json") ? res.json() : res;
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : s;
    return d.innerHTML;
  }

  /* ----------------------------- health ----------------------------- */
  async function loadHealth() {
    const pill = $("healthPill");
    try {
      const h = await api("/api/health");
      state.sarvamConfigured = !!h.sarvam_configured;
      if (state.sarvamConfigured) {
        pill.textContent = "AI ready";
        pill.className = "pill pill-ok";
        pill.title = `Sarvam ${h.chat_model} · STT ${h.stt_model} · TTS ${h.tts_model}`;
      } else {
        pill.textContent = "AI key needed";
        pill.className = "pill pill-warn";
        pill.title = "Server has no SARVAM_API_KEY. Upload and interface work; AI answers are disabled.";
      }
      updateMicNote();
    } catch (e) {
      pill.textContent = "Backend offline";
      pill.className = "pill pill-err";
    }
  }

  /* -------------------------- document upload -------------------------- */
  async function uploadFile(file) {
    if (!file) return;
    const okExt = /\.(pdf|txt)$/i.test(file.name);
    if (!okExt) {
      showDoc("err", file.name, "Unsupported file type. Please upload a PDF or TXT file.");
      toast("Only PDF or TXT files are supported.", true);
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      showDoc("err", file.name, "File is too large. Maximum size is 10 MB.");
      return;
    }
    const status = $("docStatus");
    status.hidden = false;
    status.className = "doc-status";
    status.innerHTML = `<span class="spin" style="border-color:rgba(0,0,0,.2);border-top-color:#374151"></span> Extracting text from ${esc(file.name)}…`;

    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api("/api/documents/extract", { method: "POST", body: fd });
      if (r.status === "no_text") {
        state.docId = null;
        showDoc("warn", file.name, r.message);
        toast("No readable text found in the file.", true);
        return;
      }
      state.docId = r.doc_id;
      state.filename = r.filename;
      showDoc("ok", r.filename, `${r.message} This document is now the source for answers.`);
      $("previewBox").hidden = false;
      $("previewText").textContent = r.preview + (r.char_count > r.preview.length ? "\n\n…" : "");
      toast("Document ready. Ask a question.");
    } catch (e) {
      state.docId = null;
      showDoc("err", file.name, e.message);
      toast(e.message, true);
    }
  }

  function showDoc(kind, name, msg) {
    const s = $("docStatus");
    s.hidden = false;
    s.className = "doc-status " + kind;
    s.innerHTML = `<span class="fname">${esc(name)}</span>${esc(msg)}`;
  }

  async function loadDemo() {
    const btn = $("demoBtn");
    setBusy(btn, true, "Loading…");
    try {
      const r = await api("/api/demo");
      state.docId = r.doc_id;
      state.filename = r.filename;
      showDoc("ok", r.filename, `${r.message} ${r.char_count} characters loaded.`);
      $("previewBox").hidden = false;
      $("previewText").textContent = r.preview + (r.char_count > r.preview.length ? "\n\n…" : "");
      toast("Sample notice loaded (fictional demo data).");
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(btn, false);
    }
  }

  /* ------------------------------- ask ------------------------------- */
  async function ask() {
    const q = $("question").value.trim();
    if (!q) {
      toast("Please type or speak a question first.", true);
      $("question").focus();
      return;
    }
    if (!state.docId) {
      toast("Please upload a document or load the sample first.", true);
      return;
    }
    const btn = $("askBtn");
    setBusy(btn, true, "Thinking…");
    const card = $("answerCard");
    card.hidden = false;
    $("emptyState").hidden = true;
    $("answerMeta").innerHTML = `<span>generating answer…</span>`;
    $("answerText").textContent = "";
    $("sourceBox").hidden = true;

    try {
      const r = await api("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, language: $("answerLang").value, doc_id: state.docId }),
      });
      state.lastAnswer = r.answer;
      $("answerText").textContent = r.answer;
      $("answerText").lang = (r.language || "hi").split("-")[0];
      $("answerMeta").innerHTML = [
        `<span>Language: ${esc(r.language)}</span>`,
        `<span>Source: ${esc(r.analysed)}</span>`,
        `<span>Grounded in your document</span>`,
      ].join("");
      if (r.source_excerpt) {
        $("sourceBox").hidden = false;
        $("sourceText").textContent = r.source_excerpt;
        $("sourcePage").textContent = r.source_page ? `Document page ${r.source_page}` : "";
      }
    } catch (e) {
      $("answerMeta").innerHTML = `<span style="background:#fef2f2;color:#b91c1c">error</span>`;
      $("answerText").textContent =
        e.status === 503
          ? "AI answers are unavailable because the server has no Sarvam API key configured. Upload and the rest of the interface still work. Add SARVAM_API_KEY to the server environment to enable answers."
          : e.message;
      toast(e.message, true);
    } finally {
      setBusy(btn, false);
    }
  }

  /* ------------------------------ voice ------------------------------ */
  function updateMicNote() {
    const note = $("micNote");
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (state.sarvamConfigured) {
      note.textContent = "🎙️ Voice input uses Sarvam Saaras speech-to-text (recorded on your device, transcribed on our server).";
    } else if (SR) {
      note.textContent = "Voice input will use your browser's built-in speech recognition (browser-native, not Sarvam) because no Sarvam key is configured. You can always type instead.";
    } else {
      note.textContent = "Voice input isn't available in this browser and no Sarvam key is configured. Please type your question.";
    }
  }

  async function toggleMic() {
    const btn = $("micBtn");
    if (state.recording) {
      state.mediaRecorder && state.mediaRecorder.stop();
      return;
    }
    if (state.sarvamConfigured && navigator.mediaDevices && window.MediaRecorder) {
      return startRecorder(btn);
    }
    return browserSpeech(btn);
  }

  async function startRecorder(btn) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      toast("Microphone permission denied. You can type your question instead.", true);
      return;
    }
    state.chunks = [];
    let mime = "audio/webm";
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) mime = "audio/webm;codecs=opus";
    const rec = new MediaRecorder(stream, { mimeType: mime });
    state.mediaRecorder = rec;
    state.recording = true;
    btn.classList.add("recording");
    $("micLabel").textContent = "Stop";
    rec.ondataavailable = (e) => e.data.size && state.chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      state.recording = false;
      btn.classList.remove("recording");
      $("micLabel").textContent = "Speak";
      const blob = new Blob(state.chunks, { type: mime });
      if (blob.size < 1200) {
        toast("Recording too short — please try again.", true);
        return;
      }
      setBusy(btn, true, "Transcribing…");
      const fd = new FormData();
      fd.append("file", blob, "question.webm");
      fd.append("language", $("answerLang").value);
      try {
        const r = await api("/api/voice/transcribe", { method: "POST", body: fd });
        $("question").value = r.transcript;
        toast("Transcribed with Sarvam Saaras. You can edit before asking.");
      } catch (e) {
        toast("Could not transcribe audio: " + e.message, true);
      } finally {
        setBusy(btn, false);
      }
    };
    rec.start();
    toast("Recording… tap Stop when you finish speaking.");
  }

  function browserSpeech(btn) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      toast("Speech recognition isn't supported in this browser. Please type your question.", true);
      return;
    }
    const rec = new SR();
    rec.lang = $("answerLang").value;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    btn.classList.add("recording");
    $("micLabel").textContent = "Listening…";
    rec.onresult = (e) => {
      $("question").value = e.results[0][0].transcript;
      toast("Transcribed with browser speech recognition (browser-native).");
    };
    rec.onerror = (e) => toast("Browser speech recognition error: " + e.error, true);
    rec.onend = () => {
      btn.classList.remove("recording");
      $("micLabel").textContent = "Speak";
    };
    rec.start();
  }

  async function speak(text, lang) {
    if (!text || !text.trim()) {
      toast("Nothing to read aloud yet.", true);
      return;
    }
    if (!state.sarvamConfigured) {
      if ("speechSynthesis" in window) {
        const u = new SpeechSynthesisUtterance(text.slice(0, 500));
        u.lang = lang || "hi-IN";
        speechSynthesis.speak(u);
        toast("Reading aloud with your browser's voice (browser-native, not Sarvam).");
      } else {
        toast("Audio isn't available: no Sarvam key and this browser has no speech synthesis.", true);
      }
      return;
    }
    try {
      const res = await api("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.slice(0, 2400), language: lang || "hi-IN" }),
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch (e) {
      toast("Could not generate voice: " + e.message, true);
    }
  }

  /* --------------------------- content studio --------------------------- */
  async function generateContent() {
    if (!state.docId) {
      toast("Please upload a document or load the sample first.", true);
      return;
    }
    const btn = $("genBtn");
    setBusy(btn, true, "Generating…");
    $("studioStatus").textContent = "Generating content from your document…";
    try {
      const r = await api("/api/content/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format: $("formatSel").value,
          language: $("studioLang").value,
          doc_id: state.docId,
        }),
      });
      $("studioOut").value = r.content;
      $("studioStatus").textContent = `Generated: ${$("formatSel").options[$("formatSel").selectedIndex].text} · ${r.language}`;
      toast("Content generated. You can edit, copy or download it.");
    } catch (e) {
      $("studioStatus").textContent = e.status === 503
        ? "Content generation needs a Sarvam API key on the server."
        : "Generation failed: " + e.message;
      toast(e.message, true);
    } finally {
      setBusy(btn, false);
    }
  }

  function copyText(text, label) {
    if (!text || !text.trim()) {
      toast("Nothing to copy yet.", true);
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => toast((label || "Content") + " copied."),
      () => toast("Copy failed — please select and copy manually.", true)
    );
  }

  function downloadTxt() {
    const text = $("studioOut").value;
    if (!text.trim()) {
      toast("Generate some content first.", true);
      return;
    }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "jansahayak-content.txt";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ------------------------------ wiring ------------------------------ */
  const SUGGESTIONS = [
    "What is this document about?",
    "Who is eligible?",
    "What benefits are mentioned?",
    "Which documents are required?",
    "What is the application procedure?",
    "What dates or deadlines are mentioned?",
    "Summarize this document in simple language.",
    "Which important details should I remember?",
  ];

  function initSuggestions() {
    const box = $("suggestions");
    SUGGESTIONS.forEach((q) => {
      const b = document.createElement("button");
      b.className = "chip";
      b.type = "button";
      b.textContent = q;
      b.onclick = () => {
        $("question").value = q;
        $("question").focus();
      };
      box.appendChild(b);
    });
  }

  function init() {
    initSuggestions();
    loadHealth();

    $("demoBtn").onclick = loadDemo;
    $("askBtn").onclick = ask;
    $("genBtn").onclick = generateContent;
    $("micBtn").onclick = toggleMic;
    $("listenBtn").onclick = () => speak(state.lastAnswer, $("answerLang").value);
    $("studioListenBtn").onclick = () => speak($("studioOut").value, $("studioLang").value);
    $("copyAnsBtn").onclick = () => copyText(state.lastAnswer, "Answer");
    $("copyStudioBtn").onclick = () => copyText($("studioOut").value, "Content");
    $("downloadBtn").onclick = downloadTxt;
    $("clearBtn").onclick = () => {
      $("question").value = "";
      $("answerCard").hidden = true;
      $("emptyState").hidden = false;
      state.lastAnswer = "";
    };

    const fileInput = $("fileInput");
    fileInput.onchange = (e) => uploadFile(e.target.files[0]);
    const dz = $("dropzone");
    ["dragenter", "dragover"].forEach((ev) =>
      dz.addEventListener(ev, (e) => {
        e.preventDefault();
        dz.classList.add("drag");
      })
    );
    ["dragleave", "drop"].forEach((ev) =>
      dz.addEventListener(ev, (e) => {
        e.preventDefault();
        dz.classList.remove("drag");
      })
    );
    dz.addEventListener("drop", (e) => {
      const f = e.dataTransfer.files[0];
      uploadFile(f);
    });
    dz.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") fileInput.click();
    });

    $("question").addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") ask();
    });

    // Simple interface-language toggle for the static labels.
    $("uiLang").onchange = (e) => {
      document.documentElement.lang = e.target.value === "hi" ? "hi" : "en";
      toast(e.target.value === "hi" ? "इंटरफ़ेस भाषा: हिन्दी (लेबल अनुवाद अगले संस्करण में)" : "Interface language: English");
    };
  }

  document.addEventListener("DOMContentLoaded", init);
})();

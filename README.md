# AI Assistant — Local Knowledge-Base Chat

**Version:** v2026.10.01
**Stack:** FastAPI · LangGraph · DeepSeek (streaming) · Chroma · Vue 3 + Vite

A desktop-oriented local RAG assistant that answers questions over uploaded PDFs,
optionally combines local retrieval with web search, and supports image (vision)
questions. The backend streams responses over SSE; the frontend is a Vue 3 SPA
served statically by the same FastAPI process.

---

## Features

- **Hybrid retrieval** — hand-written BM25 + semantic search fused with RRF, plus chapter-level expansion.
- **Intent routing** — LLM classifier with five intents: `chat`, `search`, `read_url`, `file_qa`, `kb_browse`; a deterministic URL gate and source planner decide which sources are used.
- **Multi-source orchestration** — local knowledge base and web search can be combined in one answer.
- **Knowledge base** — global / per-conversation scopes, priority filtering, SHA-256 de-duplication, filename numbering.
- **Document intelligence** — PDF → Markdown extraction, chapter skeleton, summary task dispatch, persistent memories.
- **Vision** — image questions via the DeepSeek Files API.
- **GPU acceleration** — optional DirectML execution provider for embeddings; selectable at runtime (CPU / GPU).
- **Bilingual** — English and Chinese queries and UI.

---

## Project layout

```
backend/
  backend.py              LLM client, intent routing, orchestration, tools
frontend/
  server.py               FastAPI app, SSE streaming, upload/settings endpoints
  db.py                   SQLite persistence (sessions, messages, files, memories, sections)
  rag_service.py          Embeddings (ONNX/DirectML or torch), Chroma, hybrid retrieval
  file_reader.py          PDF → Markdown/plain text
  enumerate_gpus.ps1      DXGI GPU enumeration (Windows)
  requirements.txt        Python dependencies
  vue-app/
    src/                  Vue 3 source
    dist/                 prebuilt frontend (tracked so the app runs without npm)
```

---

## Requirements

- Windows 10/11
- Python 3.11+ (tested with 3.13)
- Node.js 20+ *(only needed to rebuild the frontend)*
- Optional: a DirectML-capable GPU for faster embeddings

---

## Setup

### 1. Python environment

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r frontend\requirements.txt
```

### 2. Embedding model

The model is **not** included in this repository because of its size (~1 GB).
Download `BAAI/bge-base-zh-v1.5` and place it at:

```
localmodels\bge-base-zh-v1.5\
```

The runtime prefers ONNX (`model.fp16.onnx`, then `model.onnx`) and falls back to
the PyTorch weights (`pytorch_model.bin`). You may override the location:

```bat
set EMBED_MODEL_PATH=D:\path\to\bge-base-zh-v1.5
```

### 3. API configuration

Either copy the example file and fill in your keys:

```bat
copy backend\aiapi.env.example backend\aiapi.env
```

…or start the app and enter the keys in **Settings** (they are persisted to
`backend\aiapi.env`). Only `DEEPSEEK_API_KEY` is required; `BOCHA_API_KEY`
enables web search.

> `backend/aiapi.env` is git-ignored — never commit real keys.

### 4. Frontend

A prebuilt `frontend/vue-app/dist` is committed, so no build step is required.
To rebuild after changing the UI:

```bat
cd frontend\vue-app
npm install
npm run build
```

---

## Run

```bat
python frontend\server.py
```

Then open <http://localhost:8000>.

---

## Data & configuration notes

- Runtime data (SQLite database + Chroma vectors) is created under `frontend\data\` on first run. **This directory must be writable** — avoid installing the app under a read-only location such as `C:\Program Files`.
- `frontend\data\` (conversations, uploaded knowledge base) and `localmodels\` are excluded from version control.
- Useful environment overrides: `EMBED_MODEL_PATH`, `CHROMA_PERSIST_DIR`, `EMBED_DEVICE_ID`, `EMBED_DISABLE_ONNX`, `EMBED_BATCH_SIZE`, `CHAT_HISTORY_MAX_MESSAGES`, `CHAT_HISTORY_MAX_CHARS`.
- GPU execution providers are enumerated at runtime; the selection is stored in Settings and restored on startup.

---

## Version

`v2026.10.01` — see the bottom of the sidebar in the running application.

## Port

The server listens on port **8000** by default. If that port is reserved by
Windows (for example Hyper-V/WSL excluded ranges), set `APP_PORT` before starting:

```bat
set APP_PORT=8765
python frontend/server.py
```

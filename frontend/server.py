import os
import sys
import collections
import threading
import db
import asyncio
import json
import uuid
import hashlib
import subprocess
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

_HERE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE_DIR)
for _candidate in (os.path.join(_PROJECT_ROOT, "backend"), _PROJECT_ROOT, _HERE_DIR):
    if os.path.isfile(os.path.join(_candidate, "backend.py")):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break


from backend import async_stream_response, rag_service, RAG_AVAILABLE, upload_image_to_deepseek, delete_image_from_deepseek, get_api_config, update_api_config

# ── Server log capture (for the terminal panel) ──
_LOG_BUFFER = collections.deque(maxlen=500)
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_LOG_LOCK = threading.Lock()


class _LogStream:
    """Tee a stream: write to the original and buffer complete lines."""
    def __init__(self, original):
        self._original = original
        self._pending = []
    def write(self, msg):
        try:
            self._original.write(msg)
        except Exception:
            pass
        if not msg:
            return
        with _LOG_LOCK:
            self._pending.append(msg)
            if "\n" in msg:
                line = "".join(self._pending)
                _LOG_BUFFER.append(line.rstrip("\r\n"))
                self._pending = []
    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
    def isatty(self):
        return getattr(self._original, "isatty", lambda: False)()


sys.stdout = _LogStream(_ORIGINAL_STDOUT)
sys.stderr = _LogStream(_ORIGINAL_STDERR)

app = FastAPI()

# Serialises the document-upload critical section (dedup check -> name
# collision -> index -> persist). Single-worker deployment (uvicorn.run with
# no workers=) means one process handles every request, so an in-process lock
# is sufficient. Multiple worker processes would need cross-process
# coordination, which this lock does NOT provide.
_UPLOAD_LOCK = asyncio.Lock()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend", "vue-app", "dist")

ASSETS_DIR = os.path.join(FRONTEND_DIR, "assets")
if os.path.exists(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
else:
    print(f"[WARN] Build output not found: {ASSETS_DIR}")
    print("Run: cd vue-app && npm run build")

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

db.init_db()
db.migrate_db()

sessions: dict = {}
loaded = db.get_all_sessions()
for sid, data in loaded.items():
    sessions[sid] = data["messages"]
print(f"[OK] Loaded {len(sessions)} conversation(s)")


# =======================================Personal knowledge base=======================================


MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_MB", "10")) * 1024 * 1024
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _vendor_name(vendor_hex: str) -> str:
    """Map a DXGI vendor id to a short vendor name."""
    return {
        "10DE": "nvidia",
        "1002": "amd",
        "8086": "intel",
    }.get(vendor_hex.upper(), "other")


def enumerate_gpus() -> list:
    """Enumerate GPUs in DXGI order (device_id matches DirectML).

    Returns a list of dicts {device_id, name, vendor, vram_mb}. The software
    renderer (Microsoft Basic Render Driver) is filtered out.
    """
    script = os.path.join(_HERE_DIR, "enumerate_gpus.ps1")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception as exc:
        print(f"[GPU] enumeration failed: {exc}")
        return []
    gpus = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        device_id = int(parts[0])
        vendor = parts[1].upper()
        name = parts[2].strip()
        vram = parts[3].strip()
        if vendor == "1414":  # Microsoft Basic Render Driver
            continue
        try:
            vram_mb = int(vram)
        except ValueError:
            vram_mb = 0
        gpus.append({
            "device_id": device_id,
            "name": name,
            "vendor": _vendor_name(vendor),
            "vram_mb": vram_mb,
        })
    return gpus


def list_execution_providers() -> list:
    """Build the execution-provider list: CPU plus each available GPU."""
    providers = [{"id": "cpu", "name": "CPU (multi-threaded)", "vendor": "cpu", "vram_mb": 0}]
    for gpu in enumerate_gpus():
        providers.append({
            "id": f"gpu:{gpu['device_id']}",
            "name": gpu["name"],
            "vendor": gpu["vendor"],
            "vram_mb": gpu["vram_mb"],
        })
    return providers


def apply_execution_provider(provider: str):
    """Apply the selected execution provider to the RAG embedding backend."""
    if RAG_AVAILABLE and rag_service is not None:
        try:
            rag_service.set_execution_provider(provider)
        except Exception as exc:
            print(f"[RAG] apply execution provider failed: {exc}")


# Apply the saved execution provider at startup (so a restart keeps the choice).
try:
    _saved_provider = db.get_setting("execution_provider", "")
    if _saved_provider:
        apply_execution_provider(_saved_provider)
except Exception as exc:
    print(f"[RAG] startup execution provider apply failed: {exc}")


def _session_image_blocks(session: str, max_images: int = 8) -> list:
    """Return up to ``max_images`` vision content blocks for a session's images."""
    blocks = []
    for img in db.get_images(session)[-max_images:]:
        if img.get("deepseek_file_id"):
            blocks.append({"type": "file", "file_id": img["deepseek_file_id"]})
    return blocks

if RAG_AVAILABLE:
    print(f"[OK] Knowledge base ready (store: {rag_service.persist_dir})")
else:
    print("[WARN] Knowledge base unavailable: document Q&A is disabled")


# =======================================Save assistant reply (with metadata + reasoning)=======================================


def _save_assistant_reply(session: str, reply: str, intent_info: str = "",
                          tool_info: str = "", reasoning_content: str = ""):
    """
    Save assistant reply (with intent, tool output, reasoning) to database.
    Pure synchronous operation, unaffected by asyncio.CancelledError.
    """
    if not reply or session not in sessions:
        return

    # Dedup check
    already = any(
        m.get("role") == "assistant" and m.get("content") == reply
        for m in sessions[session]
    )
    if already:
        return

    # Build metadata JSON
    metadata = {}
    if intent_info:
        metadata["intentInfo"] = intent_info
    if tool_info:
        metadata["toolInfo"] = tool_info
    if reasoning_content:
        metadata["reasoningContent"] = reasoning_content
    metadata_str = json.dumps(metadata, ensure_ascii=False) if metadata else None

    # Update in-memory cache
    sessions[session].append({
        "role": "assistant",
        "content": reply,
        "metadata": metadata_str
    })

    try:
        db.add_message(session, "assistant", reply, metadata_str)

        # Update conversation title from first user message
        for m in sessions[session]:
            if m.get("role") == "user":
                content = m["content"]
                title = content[:20] + ("..." if len(content) > 20 else "")
                db.update_session_title(session, title)
                break

        info_log = f"[SAVE] session={session} ({len(reply)} chars)"
        if intent_info:
            info_log += f" | intent={intent_info}"
        if tool_info:
            info_log += f" | tool={len(tool_info)} chars"
        if reasoning_content:
            info_log += f" | reasoning={len(reasoning_content)} chars"
        print(info_log)
    except Exception as e:
        print(f"[ERROR] Save failed for session {session}: {e}")



# =======================================Upload: index a document into the knowledge base=======================================


def _rollback_failed_upload(session: str, file_id: str, scope: str) -> None:
    """Remove the artefacts a failed upload attempt created.

    Only rows/chunks tied to ``file_id`` (generated for this attempt) are
    touched, so pre-existing documents are never affected.
    """
    if not file_id:
        return
    if RAG_AVAILABLE and rag_service is not None:
        try:
            rag_service.delete_document(session, file_id=file_id, scope=scope)
        except Exception as exc:  # noqa: BLE001
            print(f"[ROLLBACK] vector cleanup failed ({file_id}): {exc}")
    for label, fn in (
        ("sections", lambda: db.delete_sections(file_id)),
        ("memories", lambda: db.delete_memories_by_file(file_id)),
        ("file_ref", lambda: db.delete_file_reference(session, file_id)),
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"[ROLLBACK] {label} cleanup failed ({file_id}): {exc}")


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session: str = Form("default"),
    scope: str = Form(""),
):
    """Index an uploaded PDF into the knowledge base.

    ``scope`` is "global" (default, shared across conversations) or "session"
    (visible only in this conversation). Re-uploading a filename in the same
    scope replaces the previous copy.
    """
    filename = file.filename or "document.pdf"
    ext = os.path.splitext(filename.lower())[1]

    file_content = await file.read()

    # ── Image branch (vision, independent of RAG) ──
    if ext in IMAGE_EXTS:
        if len(file_content) > MAX_IMAGE_BYTES:
            return JSONResponse(
                status_code=400,
                content={"status": "error",
                         "message": f"Image too large. Maximum size is {MAX_IMAGE_BYTES // (1024 * 1024)}MB"}
            )
        db.ensure_session(session)
        mime = IMAGE_MIME.get(ext, "image/jpeg")
        local_id = uuid.uuid4().hex
        try:
            deepseek_file_id = await asyncio.to_thread(
                upload_image_to_deepseek, file_content, filename, mime
            )
        except Exception as exc:
            print(f"[ERROR] Image upload to DeepSeek failed for '{filename}': {exc}")
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"Failed to upload image: {exc}"}
            )
        db.add_image(session, local_id, filename, mime, file_content, deepseek_file_id)

        notice = f"Image '{filename}' received. You can ask me questions about this image."
        sessions.setdefault(session, []).append({
            "role": "assistant", "content": notice,
            "metadata": json.dumps({"intentInfo": "Image Upload"})
        })
        db.add_message(session, "assistant", notice, json.dumps({"intentInfo": "Image Upload"}))

        print(f"[UPLOAD-IMAGE] {filename} -> {deepseek_file_id} (session {session})")
        return {
            "status": "ok",
            "file_id": local_id,
            "filename": filename,
            "mime_type": mime,
            "type": "image",
            "deepseek_file_id": deepseek_file_id,
            "message": f"'{filename}' uploaded",
        }

    # ── Document branch (RAG) ──
    if scope not in ("global", "session"):
        scope = db.get_setting("default_scope", "session")
    if not RAG_AVAILABLE or rag_service is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error",
                     "message": "Knowledge base unavailable: RAG dependencies are not installed."}
        )

    if ext != ".pdf":
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Only .pdf documents and images (jpg/png/gif/webp) are supported"}
        )

    if len(file_content) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            status_code=400,
            content={"status": "error",
                     "message": f"File too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB"}
        )

    db.ensure_session(session)

    # The whole check-then-act sequence must be atomic: a multi-file batch (or
    # any concurrent callers) would otherwise race the hash dedup and the
    # filename-collision numbering, duplicating content or overwriting each
    # other's file_refs. See _UPLOAD_LOCK for the single-worker assumption.
    async with _UPLOAD_LOCK:
        # 1) Hash-based dedup: identical bytes are skipped.
        file_hash = hashlib.sha256(file_content).hexdigest()
        existing = db.find_file_by_hash(file_hash)
        if existing:
            notice = f"'{filename}' is already in the knowledge base (identical content), skipped."
            sessions.setdefault(session, []).append({
                "role": "assistant", "content": notice,
                "metadata": json.dumps({"intentInfo": "File Upload"})
            })
            db.add_message(session, "assistant", notice, json.dumps({"intentInfo": "File Upload"}))
            return {"status": "ok", "duplicate": True, "file_id": existing.get("file_id"),
                    "filename": filename, "message": notice}

        # 2) Same name but different hash -> number the new file, higher priority.
        priority = 0
        if db.find_files_by_name(filename, scope):
            filename = db.next_numbered_filename(filename, scope)
            priority = 1

        # 3) Pre-generate the id so a failed index can be rolled back precisely.
        file_id = uuid.uuid4().hex

        # 4) Extraction and embedding are CPU bound; keep them off the loop.
        try:
            result = await asyncio.to_thread(
                rag_service.index_document, file_content, session, filename, file_id, scope
            )
        except Exception as exc:
            print(f"[ERROR] Indexing failed for '{filename}': {exc}")
            _rollback_failed_upload(session, file_id, scope)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"Failed to process the PDF: {exc}"}
            )

        # 5) Persist the record only after a successful index.
        db.add_file_reference(session, file_id, filename, len(file_content), scope, file_hash, priority)
        db.rebuild_file_list_memory()

    notice = (f"Knowledge base updated: '{filename}' indexed into "
              f"{result['chunk_count']} chunks. You can now ask questions about it.")
    sessions.setdefault(session, []).append({
        "role": "assistant",
        "content": notice,
        "metadata": json.dumps({"intentInfo": "File Upload"})
    })
    db.add_message(session, "assistant", notice, json.dumps({"intentInfo": "File Upload"}))

    print(f"[UPLOAD] {filename} -> {result['chunk_count']} chunks -> {scope} (session {session})")

    return {
        "status": "ok",
        "file_id": result["file_id"],
        "filename": filename,
        "chunk_count": result["chunk_count"],
        "char_count": result["char_count"],
        "scope": result["scope"],
        "elapsed": result["elapsed"],
        "message": f"'{filename}' indexed successfully ({result['chunk_count']} chunks)"
    }



# =======================================multimodal / vision=======================================


@app.get("/images/{session}")
async def get_session_images(session: str):
    """List images uploaded in a conversation (metadata, no bytes)."""
    return {"session": session, "images": db.get_images(session)}


@app.get("/image/{file_id}")
async def get_image_bytes(file_id: str):
    """Serve one image's raw bytes for display in the client."""
    img = db.get_image(file_id)
    if not img:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Image not found"})
    return Response(content=img["data"], media_type=img["mime_type"])


@app.delete("/image/{file_id}")
async def delete_image_endpoint(file_id: str):
    """Delete one image locally and from the DeepSeek Files API."""
    ds_id = db.delete_image(file_id)
    if ds_id:
        delete_image_from_deepseek(ds_id)
    return {"status": "ok", "deleted": True}


@app.get("/admin/resources")
async def admin_resources(session: str = "global"):
    """List the documents visible to a conversation (session + global) and all images."""
    documents = []
    target = session or "global"
    if RAG_AVAILABLE and rag_service is not None:
        try:
            docs = rag_service.list_documents(target)
            refs = {r["file_id"]: r for r in db.get_file_references(target)}
            for d in docs:
                ref = refs.get(d["file_id"], {})
                scope = d.get("scope", ref.get("scope", "global"))
                documents.append({
                    "file_id": d["file_id"],
                    "filename": d["filename"],
                    "chunk_count": d["chunk_count"],
                    "file_size": ref.get("file_size", 0),
                    "scope": scope,
                    "session_id": "global" if scope == "global" else target,
                    "priority": ref.get("priority", 0),
                    "hash": ref.get("hash", ""),
                })
        except Exception as exc:
            print(f"[ERROR] admin resources (documents) failed: {exc}")
    return {"documents": documents, "images": db.get_all_images()}


@app.post("/files/priority")
async def set_file_priority_endpoint(request: Request):
    """Set a document's retrieval priority (higher = ranked first)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    file_id = payload.get("file_id")
    priority = payload.get("priority")
    if not file_id or priority is None:
        return JSONResponse(status_code=400, content={"status": "error", "message": "file_id and priority are required"})
    ok = db.set_file_priority(file_id, int(priority))
    return {"status": "ok" if ok else "error", "file_id": file_id, "priority": int(priority)}


@app.get("/memories")
async def get_memories_endpoint():
    """List KB memory entries (file list + per-file summaries)."""
    return {"memories": db.get_all_memories(), "count": db.get_memory_count()}


@app.post("/memories")
async def write_memory_endpoint(request: Request):
    """Write a KB memory entry (admin helper; the model writes via tool)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    kind = payload.get("kind", "file_summary")
    content = payload.get("content", "")
    memory_id = payload.get("memory_id")
    mid = db.write_memory(kind, content, memory_id)
    return {"status": "ok" if mid >= 0 else "error", "memory_id": mid}


@app.get("/logs")
async def get_logs():
    """Return recent server logs for the terminal panel."""
    return {"logs": list(_LOG_BUFFER)}


@app.get("/settings")
async def get_settings_endpoint():
    settings = db.get_all_settings()
    api = get_api_config()
    settings["api_config"] = {
        "deepseek_base_url": api["deepseek_base_url"],
        "deepseek_model": api["deepseek_model"],
        "has_deepseek_key": bool(api["deepseek_api_key"]),
        "has_bocha_key": bool(api["bocha_api_key"]),
    }
    settings["execution_providers"] = list_execution_providers()
    settings["execution_provider"] = settings.get("execution_provider", "")
    return {"settings": settings}


@app.post("/settings")
async def update_settings_endpoint(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    api_config = payload.pop("api", None) or payload.pop("api_config", None)
    if isinstance(api_config, dict):
        update_api_config(api_config)

    for key, value in payload.items():
        db.set_setting(key, value)
    if "execution_provider" in payload:
        apply_execution_provider(payload["execution_provider"])
    return {"status": "ok", "settings": db.get_all_settings()}


@app.get("/files/{session}")
async def get_session_files(session: str):
    """List the documents indexed in a conversation."""
    documents = []
    if RAG_AVAILABLE and rag_service is not None:
        documents = rag_service.list_documents(session)

    refs = {r["file_id"]: r for r in db.get_file_references(session)}

    merged = []
    seen = set()
    for doc in documents:
        ref = refs.get(doc["file_id"], {})
        merged.append({
            "file_id": doc["file_id"],
            "filename": doc["filename"],
            "chunk_count": doc["chunk_count"],
            "file_size": ref.get("file_size", 0),
            "scope": doc.get("scope", ref.get("scope", "session")),
            "priority": ref.get("priority", 0),
        })
        seen.add(doc["file_id"])

    # References whose vectors are gone (e.g. after a manual store wipe)
    for file_id, ref in refs.items():
        if file_id not in seen:
            merged.append({
                "file_id": file_id,
                "filename": ref["filename"],
                "chunk_count": 0,
                "file_size": ref.get("file_size", 0),
                "scope": ref.get("scope", "global"),
            })

    return {
        "session": session,
        "document_count": len(merged),
        "chunk_count": sum(m["chunk_count"] for m in merged),
        "has_content": any(m["chunk_count"] > 0 for m in merged),
        "documents": merged,
    }


@app.delete("/files/{session}/{file_id}")
async def delete_session_file(session: str, file_id: str):
    """Remove a single document from a conversation's knowledge base."""
    removed = 0
    if RAG_AVAILABLE and rag_service is not None:
        removed = rag_service.delete_document(session, file_id=file_id)
    db.delete_file_reference(session, file_id)
    db.delete_memories_by_file(file_id)
    db.delete_sections(file_id)
    db.rebuild_file_list_memory()
    print(f"[DELETE] document {file_id} removed from {session} ({removed} chunks)")
    return {"status": "ok", "file_id": file_id, "chunk_count": removed}




# =======================================HTTP Endpoints=======================================


@app.delete("/conversations/{session_id}")
async def delete_conversation(session_id: str):
    sessions.pop(session_id, None)

    # Session-scoped artefacts that are not foreign-key linked must be
    # cleaned explicitly: chapter skeletons and per-file summary memories.
    for ref in db.get_file_references(session_id):
        if ref.get("scope") == "session":
            db.delete_memories_by_file(ref.get("file_id"))
            db.delete_sections(ref.get("file_id"))

    # Drop this session's images from the DeepSeek Files API too; the local
    # rows cascade away with the session row.
    for img in db.get_images(session_id):
        ds_id = img.get("deepseek_file_id")
        if ds_id:
            try:
                await asyncio.to_thread(delete_image_from_deepseek, ds_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[DELETE] remote image cleanup failed ({ds_id}): {exc}")

    db.delete_session(session_id)
    if RAG_AVAILABLE and rag_service is not None:
        rag_service.delete_session(session_id)
    db.rebuild_file_list_memory()
    print(f"[DELETE] Session removed: {session_id}")
    return {"status": "ok", "message": "Conversation deleted"}

@app.get("/conversations")
async def get_conversations():
    fresh = db.get_all_sessions()
    return fresh


# =======================================SSE Streaming Endpoint (supports thinking mode + knowledge base)=======================================

@app.get("/stream")
async def stream(msg: str, request: Request, session: str = "default"):
    async def event_generator():
        if session not in sessions:
            sessions[session] = []
        db.ensure_session(session)

        sessions[session].append({"role": "user", "content": msg})
        db.add_message(session, "user", msg)

        yield {"event": "message", "data": json.dumps({"type": "start"})}

        queue = asyncio.Queue()
        assistant_reply = [""]
        intent_info = [""]
        tool_info = [""]
        reasoning_content = [""]

        async def producer():
            """
            Consumer: consume events from async_stream_response,
            capture metadata (including reasoning_content) and save on done.
            """
            try:
                settings = db.get_all_settings()
                max_images = int(settings.get("max_images_per_turn", "8"))
                image_blocks = _session_image_blocks(session, max_images)
                priority_file_ids = db.get_priority_file_ids(session)
                async for event in async_stream_response(sessions[session], session_id=session, images=image_blocks, settings=settings, priority_file_ids=priority_file_ids):
                    event_type = event.get("type")
                    event_content = event.get("content", "")

                    # Capture metadata before putting in queue
                    if event_type == "intent_info":
                        intent_info[0] = event_content
                    elif event_type == "tool_info":
                        tool_info[0] = event_content
                    elif event_type == "reasoning_done":
                        reasoning_content[0] = event_content
                    elif event_type == "done":
                        assistant_reply[0] = event_content
                        rc = event.get("reasoning_content", reasoning_content[0])
                        _save_assistant_reply(
                            session,
                            assistant_reply[0],
                            intent_info[0],
                            tool_info[0],
                            rc
                        )

                    await queue.put(event)

            except asyncio.CancelledError:
                raise
            finally:
                # Protective save: if producer cancelled, try to save partial content
                if assistant_reply[0]:
                    _save_assistant_reply(
                        session,
                        assistant_reply[0],
                        intent_info[0],
                        tool_info[0],
                        reasoning_content[0]
                    )
                # Send end signal
                try:
                    await asyncio.shield(queue.put(None))
                except asyncio.CancelledError:
                    try:
                        queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass
                except Exception:
                    pass

        producer_task = asyncio.create_task(producer())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break

                event_type = event.get("type")
                event_content = event.get("content", "")

                if event_type == "intent_info":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "intent_info", "content": event_content}, ensure_ascii=False)}
                elif event_type == "tool_info":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "tool_info", "content": event_content}, ensure_ascii=False)}
                elif event_type == "usage_info":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "usage_info", "content": event_content}, ensure_ascii=False)}
                elif event_type == "needs_setup":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "needs_setup", "content": event_content}, ensure_ascii=False)}
                # Reasoning process events
                elif event_type == "reasoning_start":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "reasoning_start", "content": event_content}, ensure_ascii=False)}
                elif event_type == "reasoning_token":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "reasoning_token", "content": event_content}, ensure_ascii=False)}
                elif event_type == "reasoning_done":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "reasoning_done", "content": event_content}, ensure_ascii=False)}
                elif event_type == "prefix":
                    if event_content:
                        yield {"event": "message", "data": json.dumps(
                            {"type": "token", "content": event_content + " "}, ensure_ascii=False)}
                elif event_type == "token":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "token", "content": event_content}, ensure_ascii=False)}
                elif event_type == "error":
                    yield {"event": "message", "data": json.dumps(
                        {"type": "token", "content": f"Error: {event_content}"}, ensure_ascii=False)}

        except asyncio.CancelledError:
            print(f"[SSE] Connection closed, background save continues for session {session}...")
            raise
        finally:
            if not producer_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(producer_task),
                        timeout=120
                    )
                except asyncio.TimeoutError:
                    print(f"[WARN] LLM call timeout (120s) for session {session}, still running in background")
                except asyncio.CancelledError:
                    print(f"[SSE] Producer still running in background for session {session}")
                except Exception as e:
                    print(f"[WARN] Error waiting for producer: {e}")

        yield {"event": "message", "data": json.dumps({"type": "done"})}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    print("=" * 50)
    print(f"Frontend: {FRONTEND_DIR}")
    print(f"Database: {db.DB_FILE}")
    if RAG_AVAILABLE:
        print(f"Vectors:  {rag_service.persist_dir}")
    _PORT = int(os.getenv("APP_PORT", "8000"))
    print(f"Open:     http://localhost:{_PORT}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=_PORT)

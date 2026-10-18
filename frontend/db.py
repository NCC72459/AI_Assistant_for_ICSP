import sqlite3
import os
import json  
from typing import List, Dict, Optional  

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_FILE = os.path.join(DB_DIR, "conversations.db")

def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    # timeout / busy_timeout make concurrent writers wait for the lock instead
    # of failing straight away with "database is locked". These relieve lock
    # contention only - they are not a substitute for business-level locking.
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
    except Exception:
        pass
    return conn

def init_db():
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL lets readers proceed alongside a single writer, easing lock
        # contention under the upload queue (persisted in the DB header).
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'New Chat',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        # File references table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                scope TEXT DEFAULT 'global',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        # Images (multimodal) - bytes kept locally for display/persistence;
        # the model references them via the DeepSeek Files API id.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                data BLOB NOT NULL,
                deepseek_file_id TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        # Key-value settings for the management / settings UI.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
        print(f"[DB] Initialized: {DB_FILE}")
    except Exception as e:
        print(f"[DB] Init error: {e}")
    finally:
        conn.close()

def migrate_db():
    """Add metadata column and file_refs table to existing databases."""
    conn = get_connection()
    try:
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "metadata" not in columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN metadata TEXT DEFAULT NULL"
            )
            conn.commit()
            print("[DB] Migration: added metadata column")

        cursor = conn.execute("PRAGMA table_info(file_refs)")
        columns = [row["name"] for row in cursor.fetchall()]
        if not columns:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_refs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_size INTEGER DEFAULT 0,
                    scope TEXT DEFAULT 'global',
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            conn.commit()
            print("[DB] Migration: added file_refs table")
        elif "scope" not in columns:
            conn.execute("ALTER TABLE file_refs ADD COLUMN scope TEXT DEFAULT 'global'")
            conn.commit()
            print("[DB] Migration: added file_refs.scope column")

        cursor = conn.execute("PRAGMA table_info(images)")
        columns = [row["name"] for row in cursor.fetchall()]
        if not columns:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    data BLOB NOT NULL,
                    deepseek_file_id TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            conn.commit()
            print("[DB] Migration: added images table")

        cursor = conn.execute("PRAGMA table_info(settings)")
        columns = [row["name"] for row in cursor.fetchall()]
        if not columns:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()
            print("[DB] Migration: added settings table")

        # file_refs: hash (dedup) + priority (retrieval ordering)
        cursor = conn.execute("PRAGMA table_info(file_refs)")
        fcols = [row["name"] for row in cursor.fetchall()]
        if fcols and "hash" not in fcols:
            conn.execute("ALTER TABLE file_refs ADD COLUMN hash TEXT DEFAULT ''")
            conn.commit()
            print("[DB] Migration: added file_refs.hash column")
        cursor = conn.execute("PRAGMA table_info(file_refs)")
        fcols = [row["name"] for row in cursor.fetchall()]
        if fcols and "priority" not in fcols:
            conn.execute("ALTER TABLE file_refs ADD COLUMN priority INTEGER DEFAULT 0")
            conn.commit()
            print("[DB] Migration: added file_refs.priority column")

        # kb_memories: model-writable file list + per-file summaries (id 0..1023)
        cursor = conn.execute("PRAGMA table_info(kb_memories)")
        mcols = [row["name"] for row in cursor.fetchall()]
        if not mcols:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kb_memories (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                    file_id TEXT DEFAULT ''
                )
            """)
            conn.commit()
            print("[DB] Migration: added kb_memories table")

        # kb_memories.file_id: link a summary memory to its source file
        cursor = conn.execute("PRAGMA table_info(kb_memories)")
        mcols = [row["name"] for row in cursor.fetchall()]
        if mcols and "file_id" not in mcols:
            conn.execute("ALTER TABLE kb_memories ADD COLUMN file_id TEXT DEFAULT ''")
            conn.commit()
            print("[DB] Migration: added kb_memories.file_id column")

        # document_sections: per-file chapter skeleton (map-reduce style index)
        cursor = conn.execute("PRAGMA table_info(document_sections)")
        scols = [row["name"] for row in cursor.fetchall()]
        if not scols:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_sections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    scope TEXT DEFAULT 'global',
                    session_id TEXT DEFAULT 'global',
                    section_index INTEGER DEFAULT 0,
                    title TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    chunk_start INTEGER DEFAULT 0,
                    chunk_end INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            print("[DB] Migration: added document_sections table")

    except Exception as e:
        print(f"[DB] Migration error: {e}")
    finally:
        conn.close()

# ── Sessions ──

def get_all_sessions() -> Dict[str, dict]:
    """Get all sessions with their messages (including metadata)."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT id, title FROM sessions WHERE id != ? ORDER BY created_at DESC",
            (GLOBAL_SESSION_ID,),
        )
        rows = cursor.fetchall()
        
        result = {}
        for row in rows:
            session_id = row["id"]
            msg_cursor = conn.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,)
            )
            messages = []
            for m in msg_cursor.fetchall():
                msg = {"role": m["role"], "content": m["content"]}
                if m["metadata"]:
                    msg["metadata"] = m["metadata"]
                messages.append(msg)
            result[session_id] = {
                "title": row["title"],
                "messages": messages
            }
        return result
    except Exception as e:
        print(f"[DB] Read sessions error: {e}")
        return {}
    finally:
        conn.close()

def ensure_session(session_id: str):
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if not cursor.fetchone():
            conn.execute(
                "INSERT INTO sessions (id, title) VALUES (?, 'New Chat')",
                (session_id,)
            )
            conn.commit()
    except Exception as e:
        print(f"[DB] Create session error: {e}")
    finally:
        conn.close()

def update_session_title(session_id: str, title: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
            (title.replace("'", "''"), session_id)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Update title error: {e}")
    finally:
        conn.close()

def add_message(session_id: str, role: str, content: str, metadata: Optional[str] = None):
    conn = get_connection()
    try:
        if metadata:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata) VALUES (?, ?, ?, ?)",
                (session_id, role, content, metadata)
            )
        else:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content)
            )
        conn.execute(
            "UPDATE sessions SET updated_at = datetime('now', 'localtime') WHERE id = ?",
            (session_id,)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Add message error: {e}")
    finally:
        conn.close()

# Sentinel session that owns shared (global) document rows. Global docs
# outlive the conversation that uploaded them, so their rows are re-homed
# here before a session is deleted (see delete_session).
GLOBAL_SESSION_ID = "global"


def delete_session(session_id: str) -> bool:
    """Delete a conversation and everything strictly scoped to it.

    Global (shared) documents outlive the conversation that uploaded them,
    so their rows are re-homed to the ``global`` sentinel session first;
    otherwise the ON DELETE CASCADE on file_refs.session_id would silently
    drop shared knowledge. Session-scoped rows keep cascading as before.
    """
    if not session_id or session_id == GLOBAL_SESSION_ID:
        return False
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Sentinel row so re-homed global rows keep a valid session_id.
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title) VALUES (?, 'Knowledge Base')",
            (GLOBAL_SESSION_ID,),
        )
        # Re-home shared documents / section skeletons away from this session.
        conn.execute(
            "UPDATE file_refs SET session_id = ? WHERE session_id = ? AND scope = 'global'",
            (GLOBAL_SESSION_ID, session_id),
        )
        conn.execute(
            "UPDATE document_sections SET session_id = ? WHERE session_id = ? AND scope = 'global'",
            (GLOBAL_SESSION_ID, session_id),
        )
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"[DB] Delete session error: {e}")
        return False
    finally:
        conn.close()

# File References

def add_file_reference(session_id: str, file_id: str, filename: str, file_size: int, scope: str = "global",
                       file_hash: str = "", priority: int = 0):
    """
    Record a document. Global documents are shared across every conversation;
    session documents are visible only in their own conversation. Re-uploading
    a filename within the same scope supersedes the previous entry.
    """
    if scope not in ("global", "session"):
        scope = "global"
    conn = get_connection()
    try:
        # Supersede the previous copy of the same filename within a scope.
        # Callers rename on a name clash (next_numbered_filename), so the
        # target name is normally unique and this removes nothing; it exists
        # to keep the "re-upload replaces" rule. It is scoped to
        # (scope, filename) and never touches other documents' rows.
        conn.execute(
            "DELETE FROM file_refs WHERE scope = ? AND filename = ?",
            (scope, filename)
        )
        conn.execute(
            "INSERT INTO file_refs (session_id, file_id, filename, file_size, scope, hash, priority) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, file_id, filename, file_size, scope, file_hash, priority)
        )
        conn.commit()
        print(f"[DB] File ref saved: scope={scope}, file={filename} (hash={file_hash[:8]}, priority={priority})")
    except Exception as e:
        print(f"[DB] File ref save error: {e}")
    finally:
        conn.close()


def get_file_references(session_id: str) -> list:
    """
    List global documents plus this conversation's own session-scoped documents.
    Returns a list of {"file_id", "filename", "file_size", "scope"} dicts.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id, filename, file_size, scope, hash, priority FROM file_refs "
            "WHERE scope = 'global' OR (scope = 'session' AND session_id = ?) "
            "ORDER BY id ASC",
            (session_id,)
        )
        return [
            {
                "file_id": row["file_id"],
                "filename": row["filename"],
                "file_size": row["file_size"],
                "scope": row["scope"],
                "priority": row["priority"],
                "hash": row["hash"],
            }
            for row in cursor.fetchall()
        ]
    except Exception as e:
        print(f"[DB] File ref read error: {e}")
        return []
    finally:
        conn.close()


def get_file_reference(session_id: str) -> dict:
    """Latest document recorded for a conversation, or an empty dict."""
    references = get_file_references(session_id)
    return references[-1] if references else {}


def delete_file_reference(session_id: str, file_id: str = None):
    """Delete one document reference (by unique file_id), or all for a session."""
    conn = get_connection()
    try:
        if file_id:
            conn.execute("DELETE FROM file_refs WHERE file_id = ?", (file_id,))
        else:
            conn.execute("DELETE FROM file_refs WHERE session_id = ?", (session_id,))
        conn.commit()
    except Exception as e:
        print(f"[DB] File ref delete error: {e}")
    finally:
        conn.close()


def find_file_by_hash(file_hash: str) -> dict:
    """Return the file_refs row whose hash matches (empty dict if none)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT file_id, session_id, filename, file_size, scope, hash, priority "
            "FROM file_refs WHERE hash = ? ORDER BY id DESC",
            (file_hash,),
        ).fetchone()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB] find_file_by_hash error: {e}")
        return {}
    finally:
        conn.close()


def find_files_by_name(filename: str, scope: str = "global") -> list:
    """List file_refs rows sharing a filename in the given scope."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id, session_id, filename, file_size, scope, hash, priority "
            "FROM file_refs WHERE filename = ? AND scope = ? ORDER BY id ASC",
            (filename, scope),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DB] find_files_by_name error: {e}")
        return []
    finally:
        conn.close()


def next_numbered_filename(filename: str, scope: str = "global") -> str:
    """Return the next numbered filename after a hash-mismatch collision.

    "report.pdf" -> "report（2）.pdf", then "report（3）.pdf", etc.
    """
    base, ext = os.path.splitext(filename)
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT filename FROM file_refs WHERE scope = ?", (scope,))
        existing = {r["filename"] for r in cursor.fetchall()}
    except Exception:
        existing = set()
    finally:
        conn.close()
    n = 2
    while f"{base}（{n}）{ext}" in existing:
        n += 1
    return f"{base}（{n}）{ext}"


def set_file_priority(file_id: str, priority: int) -> bool:
    """Set a document's retrieval priority (higher = ranked first)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE file_refs SET priority = ? WHERE file_id = ?", (priority, file_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] set_file_priority error: {e}")
        return False
    finally:
        conn.close()


def get_priority_file_ids(session_id: str) -> set:
    """High-priority file_ids: user-selected (priority>0) plus this session's uploads."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id FROM file_refs WHERE priority > 0 OR session_id = ?",
            (session_id,),
        )
        return {r["file_id"] for r in cursor.fetchall()}
    except Exception as e:
        print(f"[DB] get_priority_file_ids error: {e}")
        return set()
    finally:
        conn.close()


# ── Images (multimodal) ──

def add_image(session_id: str, file_id: str, filename: str, mime_type: str, data: bytes, deepseek_file_id: Optional[str] = None):
    """Store an image's bytes locally plus its DeepSeek Files API id."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO images (session_id, file_id, filename, mime_type, data, deepseek_file_id) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, file_id, filename, mime_type, sqlite3.Binary(data), deepseek_file_id),
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Add image error: {e}")
    finally:
        conn.close()


def get_images(session_id: str) -> list:
    """List image metadata (no bytes) for a session, oldest first."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id, filename, mime_type, deepseek_file_id, created_at "
            "FROM images WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DB] List images error: {e}")
        return []
    finally:
        conn.close()


def get_image(file_id: str) -> dict:
    """Fetch one image including its raw bytes, for serving to the client."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id, filename, mime_type, data FROM images WHERE file_id = ?",
            (file_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {}
        return {
            "file_id": row["file_id"],
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "data": bytes(row["data"]),
        }
    except Exception as e:
        print(f"[DB] Get image error: {e}")
        return {}
    finally:
        conn.close()


def delete_image(file_id: str) -> Optional[str]:
    """Delete one image row, returning its DeepSeek file id for API cleanup."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT deepseek_file_id FROM images WHERE file_id = ?", (file_id,))
        row = cursor.fetchone()
        ds_id = row["deepseek_file_id"] if row else None
        conn.execute("DELETE FROM images WHERE file_id = ?", (file_id,))
        conn.commit()
        return ds_id
    except Exception as e:
        print(f"[DB] Delete image error: {e}")
        return None
    finally:
        conn.close()


# ── Settings (system configuration) ──

DEFAULT_SETTINGS = {
    "web_search_enabled": "1",
    "max_images_per_turn": "8",
    "default_scope": "session",
}


def get_setting(key: str, default=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else (DEFAULT_SETTINGS.get(key, default))
    except Exception:
        return DEFAULT_SETTINGS.get(key, default)
    finally:
        conn.close()


def set_setting(key: str, value) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] set_setting error: {e}")
        return False
    finally:
        conn.close()


def get_all_settings() -> dict:
    result = dict(DEFAULT_SETTINGS)
    conn = get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            result[row["key"]] = row["value"]
    except Exception:
        pass
    finally:
        conn.close()
    return result


# ── KB memories (model-writable file list + summaries) ──

KB_MEMORY_LIMIT = 1024


def write_memory(kind: str, content: str, memory_id: Optional[int] = None, file_id: str = "") -> int:
    """Write a memory entry. Append when memory_id is None, else upsert by id.

    Returns the entry id, or -1 on failure / when the 1024 limit is reached.
    """
    conn = get_connection()
    try:
        if memory_id is None:
            row = conn.execute("SELECT MAX(id) AS m FROM kb_memories").fetchone()
            memory_id = (row["m"] + 1) if (row and row["m"] is not None) else 0
            if memory_id >= KB_MEMORY_LIMIT:
                return -1
            conn.execute(
                "INSERT INTO kb_memories (id, kind, content, file_id) VALUES (?, ?, ?, ?)",
                (memory_id, kind, content, file_id),
            )
        else:
            conn.execute(
                "INSERT INTO kb_memories (id, kind, content, file_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, content = excluded.content, "
                "file_id = excluded.file_id, updated_at = datetime('now', 'localtime')",
                (memory_id, kind, content, file_id),
            )
        conn.commit()
        return memory_id
    except Exception as e:
        print(f"[DB] write_memory error: {e}")
        return -1
    finally:
        conn.close()


def get_memory(memory_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, kind, content, file_id FROM kb_memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}
    finally:
        conn.close()


def get_all_memories() -> list:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT id, kind, content, file_id FROM kb_memories ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def get_memory_count() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM kb_memories").fetchone()
        return row["c"] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def delete_memory(memory_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM kb_memories WHERE id = ?", (memory_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] delete_memory error: {e}")
        return False
    finally:
        conn.close()


def clear_memories() -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM kb_memories")
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] clear_memories error: {e}")
        return False
    finally:
        conn.close()


def delete_memories_by_file(file_id: str) -> int:
    """Delete all summary memories tied to a file_id. Returns the count."""
    if not file_id:
        return 0
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM kb_memories WHERE file_id = ? AND file_id != ''", (file_id,))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"[DB] delete_memories_by_file error: {e}")
        return 0
    finally:
        conn.close()


def rebuild_file_list_memory() -> int:
    """Rebuild memory id 0 (the file list) from current file_refs."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT file_id, filename, scope, priority FROM file_refs ORDER BY id ASC")
        rows = [dict(r) for r in cursor.fetchall()]
    except Exception:
        rows = []
    finally:
        conn.close()
    lines = []
    for r in rows:
        scope = "Global" if r["scope"] == "global" else "Session"
        prio = "high-priority" if r.get("priority", 0) > 0 else ""
        tag = f" [{prio}]" if prio else ""
        lines.append(f"- {r['filename']}{tag}（{scope}）[file_id={r['file_id']}]")
    content = "Knowledge base files:\n" + ("\n".join(lines) if lines else "(empty)")
    return write_memory("file_list", content, 0)


def save_sections(file_id: str, scope: str, session_id: str, sections: list) -> int:
    """Batch-save a document's chapter skeleton (list of dicts with
    title/summary/chunk_start/chunk_end)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_sections WHERE file_id = ?", (file_id,))
        for i, s in enumerate(sections):
            conn.execute(
                "INSERT INTO document_sections "
                "(file_id, scope, session_id, section_index, title, summary, chunk_start, chunk_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (file_id, scope, session_id, i,
                 s.get("title", ""), s.get("summary", ""),
                 int(s.get("chunk_start", 0)), int(s.get("chunk_end", 0))),
            )
        conn.commit()
        return len(sections)
    except Exception as e:
        print(f"[DB] save_sections error: {e}")
        return 0
    finally:
        conn.close()


def get_sections(session_id: str) -> list:
    """Return the chapter skeleton visible to a conversation (global + its own)."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id, scope, session_id, section_index, title, summary, chunk_start, chunk_end "
            "FROM document_sections "
            "WHERE scope = 'global' OR (scope = 'session' AND session_id = ?) "
            "ORDER BY file_id, section_index",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DB] get_sections error: {e}")
        return []
    finally:
        conn.close()


def delete_sections(file_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_sections WHERE file_id = ?", (file_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] delete_sections error: {e}")
        return False
    finally:
        conn.close()


def get_all_images() -> list:
    """List every image across all sessions (metadata, newest first)."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT file_id, session_id, filename, mime_type, deepseek_file_id, created_at "
            "FROM images ORDER BY id DESC"
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DB] get_all_images error: {e}")
        return []
    finally:
        conn.close()

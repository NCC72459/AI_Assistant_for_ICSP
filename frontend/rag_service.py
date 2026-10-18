import math
import os
import re
import threading
import time
import uuid

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from file_reader import extract_markdown_from_upload

# --------------------------------------------------------------------------
# Chunking configuration
# --------------------------------------------------------------------------
CHUNK_SIZE = 600
CHUNK_OVERLAP = 90
HEADERS_TO_SPLIT_ON = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
SEPARATORS = ["\n\n\n", "\n\n", "\n", "。", ". "]

# --------------------------------------------------------------------------
# Retrieval configuration
# --------------------------------------------------------------------------
TOP_K = 15
MAX_SECTION_CHUNKS = 15  # sections larger than this expand only a window around hits
CONTEXT_WINDOW = 5
MAX_TOTAL_CHUNKS = 50  # hard cap on expanded retrieval to protect the LLM context            # passages handed to the LLM
FETCH_K = 15         # candidates pulled from the index before MMR re-ranking
LAMBDA_MULT = 0.7    # 0 = pure diversity, 1 = pure similarity

# Calibration note: 0.5 was tuned on content-style questions only and silently
# rejected every meta question ("what is this document about?"). Measured
# cosine similarities: genuine meta questions land at 0.25-0.33, while
# irrelevant Chinese queries already reach 0.12-0.23, so the two ranges
# overlap and no safe cut-off exists between them. The value below therefore
# acts as a noise floor only, discarding obviously unrelated fragments; the
# final relevance judgement is delegated to the model via the prompt.
SCORE_THRESHOLD = 0.15   # cosine similarity below this is discarded

# Hybrid retrieval: fuse semantic (cosine) and keyword (BM25) rankings via
# reciprocal rank fusion, which only needs ranks and sidesteps the two sources'
# incompatible score scales.
RRF_K = 60
PRIORITY_BONUS = 0.5  # added to RRF score for high-priority (session/selected) files
BM25_K1 = 1.5
BM25_B = 0.75
HYBRID_ENABLED = os.getenv("HYBRID_ENABLED", "1").lower() not in ("0", "false", "no")

# Cosine distance is requested explicitly so that the relevance scores
# returned by Chroma are comparable with SCORE_THRESHOLD. With the default
# L2 space the same chunk would score noticeably lower.
COLLECTION_METADATA = {"hnsw:space": "cosine"}

# --------------------------------------------------------------------------
# Storage / model locations
# --------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)

DEFAULT_PERSIST_DIR = os.path.join(_HERE, "data", "chroma_db")
DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "localmodels", "bge-base-zh-v1.5")

# Overridable so the model or store can be relocated without code changes.
MODEL_PATH = os.getenv("EMBED_MODEL_PATH", DEFAULT_MODEL_PATH)
PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR)

EMBED_DEVICE = os.getenv("EMBED_DEVICE", "cpu")

_ADD_BATCH_SIZE = 128


class OnnxEmbeddings:
    """BGE embedding via ONNX Runtime, preferring DirectML (any GPU) with a
    CPU execution-provider fallback.

    Produces L2-normalised CLS vectors numerically identical to the torch
    sentence-transformers path (measured cosine similarity 1.0). Requires the
    pre-exported ``model.onnx`` / ``model.fp16.onnx`` next to the model dir.
    """

    def __init__(self, model_path, onnx_path, device_id=None, batch_size=64, max_seq_len=512):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.max_seq_len = max_seq_len
        self.batch_size = batch_size
        self._lock = threading.Lock()

        providers = []
        provider_options = []
        if "DmlExecutionProvider" in ort.get_available_providers():
            providers.append("DmlExecutionProvider")
            opts = {}
            if device_id is not None:
                opts["device_id"] = int(device_id)
            provider_options.append(opts)
        providers.append("CPUExecutionProvider")
        provider_options.append({})

        self.session = ort.InferenceSession(
            onnx_path, providers=providers, provider_options=provider_options
        )
        print(f"[RAG] ONNX embedding session: {self.session.get_providers()} ({onnx_path})")

    def _encode(self, texts):
        if not texts:
            return []

        import numpy as np

        vectors = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            enc = self.tokenizer(
                batch,
                padding="max_length",
                truncation=True,
                max_length=self.max_seq_len,
                return_tensors="np",
            )
            feed = {
                "input_ids": enc["input_ids"].astype(np.int64),
                "attention_mask": enc["attention_mask"].astype(np.int64),
            }
            with self._lock:
                hidden = self.session.run(None, feed)[0]
            cls = hidden[:, 0, :].astype(np.float32)
            norm = np.maximum(np.linalg.norm(cls, axis=1, keepdims=True), 1e-12)
            vectors.append(cls / norm)
        return np.vstack(vectors).tolist()

    def embed_documents(self, texts):
        return self._encode(texts)

    def embed_query(self, text):
        return self._encode([text])[0]


class _BM25:
    """Minimal Okapi BM25 keyword ranker, zero dependencies.

    Tokenises text into latin/digit words and individual CJK characters so it
    complements (rather than duplicates) the semantic BGE retriever: it is what
    makes exact codes, names and figures ("RR-2006", "CVN", "EPR", numbers)
    findable when their semantic embedding would be weak.
    """

    _TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")

    def __init__(self, corpus, k1=BM25_K1, b=BM25_B):
        self.k1 = k1
        self.b = b
        self.doc_tokens = [self._tokenize(t) for t in corpus]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.n_docs = len(self.doc_tokens)
        self.avgdl = sum(self.doc_len) / self.n_docs if self.n_docs else 0.0

        df = {}
        for tokens in self.doc_tokens:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1
        self.idf = {
            term: math.log((self.n_docs - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }

        self.tf = []
        for tokens in self.doc_tokens:
            tf_doc = {}
            for term in tokens:
                tf_doc[term] = tf_doc.get(term, 0) + 1
            self.tf.append(tf_doc)

    def _tokenize(self, text):
        return self._TOKEN_RE.findall((text or "").lower())

    def search(self, query, k=20):
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []
        scored = []
        for i, tf_doc in enumerate(self.tf):
            score = 0.0
            for term in q_tokens:
                freq = tf_doc.get(term, 0)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                score += idf * (freq * (self.k1 + 1)) / denom
            if score > 0:
                scored.append((i, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


class RagService:
    """Vector store backed personal knowledge base, one collection per session."""

    def __init__(self, persist_dir=None, model_path=None, device=None):
        self.persist_dir = persist_dir or PERSIST_DIR
        self.model_path = model_path or MODEL_PATH
        self.device = device or EMBED_DEVICE

        os.makedirs(self.persist_dir, exist_ok=True)

        self._embeddings = None
        self._stores = {}
        self._lock = threading.RLock()
        self._chroma = None
        self._bm25_cache = {}

        # The Chroma client is created eagerly (cheap, no model load) so that
        # existence checks and deletions never pull the embedding model in.
        import chromadb
        self._chroma = chromadb.PersistentClient(path=self.persist_dir)

        self._md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=HEADERS_TO_SPLIT_ON,
            strip_headers=False,
        )
        self._rec_splitter = RecursiveCharacterTextSplitter(
            separators=SEPARATORS,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
        )

    # ------------------------------------------------------------------
    # lazy resources
    # ------------------------------------------------------------------
    @property
    def embeddings(self):
        """Load the embedding backend on first use."""
        if self._embeddings is None:
            with self._lock:
                if self._embeddings is None:
                    self._embeddings = self._build_embeddings()
        return self._embeddings

    def set_execution_provider(self, provider: str):
        """Configure the embedding execution provider and reset the loaded backend.

        ``provider`` is "cpu" (torch CPU), "gpu:N" (DirectML device_id=N), or
        "" (auto: default DirectML device selection).
        """
        if provider == "cpu":
            os.environ["EMBED_DISABLE_ONNX"] = "1"
            os.environ.pop("EMBED_DEVICE_ID", None)
        elif provider and provider.startswith("gpu:"):
            os.environ.pop("EMBED_DISABLE_ONNX", None)
            os.environ["EMBED_DEVICE_ID"] = provider.split(":", 1)[1]
        else:
            os.environ.pop("EMBED_DISABLE_ONNX", None)
            os.environ.pop("EMBED_DEVICE_ID", None)
        # Reset the embedding backend AND drop the cached Chroma wrappers:
        # each wrapper captured the embedding function at construction time, so
        # without this an already-open collection would keep encoding with the
        # old device - the switch would only take effect for new collections.
        with self._lock:
            self._embeddings = None  # force reload on next use
            self._stores.clear()
        print(f"[RAG] execution provider set to: {provider or 'auto'}")

    def _build_embeddings(self):
        """Pick the fastest available embedding backend.

        Prefer a pre-exported ONNX model run through DirectML (any GPU, no
        CUDA/NVIDIA dependency) or the CPU execution provider; fall back to the
        torch sentence-transformers path when ONNX is unavailable. Set
        EMBED_DISABLE_ONNX=1 to force the torch path.
        """
        onnx_path = None
        fp16 = os.path.join(self.model_path, "model.fp16.onnx")
        fp32 = os.path.join(self.model_path, "model.onnx")
        if os.path.isfile(fp16):
            onnx_path = fp16
        elif os.path.isfile(fp32):
            onnx_path = fp32

        disable = os.getenv("EMBED_DISABLE_ONNX", "").lower()
        if onnx_path and disable not in ("1", "true", "yes"):
            try:
                device_id = os.getenv("EMBED_DEVICE_ID")
                batch_size = int(os.getenv("EMBED_BATCH_SIZE", "64"))
                return OnnxEmbeddings(
                    self.model_path,
                    onnx_path,
                    device_id=int(device_id) if device_id else None,
                    batch_size=batch_size,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[RAG] ONNX backend unavailable, falling back to torch CPU: {exc}")

        # Torch CPU fallback (the original sentence-transformers path).
        from langchain_huggingface import HuggingFaceEmbeddings

        threads = os.getenv("EMBED_THREADS")
        if threads:
            try:
                import torch

                torch.set_num_threads(int(threads))
                print(f"[RAG] torch threads capped at {threads}")
            except Exception as exc:  # noqa: BLE001
                print(f"[RAG] could not cap torch threads: {exc}")

        t0 = time.time()
        embeddings = HuggingFaceEmbeddings(
            model_name=self.model_path,
            model_kwargs={"device": self.device},
            encode_kwargs={"normalize_embeddings": True},
        )
        print(
            f"[RAG] embedding model loaded in {time.time() - t0:.1f}s "
            f"(device={self.device}, path={self.model_path})"
        )
        return embeddings

    def warmup(self):
        """Eagerly load the model; safe to call at start-up."""
        _ = self.embeddings
        return True

    # ------------------------------------------------------------------
    # naming
    # ------------------------------------------------------------------
    @staticmethod
    def _collection_name(session_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", str(session_id or "default"))
        name = f"kb_{safe}"
        # Chroma requires 3-63 chars and an alphanumeric start/end.
        name = name[:63].rstrip("_-")
        return name if len(name) >= 3 else "kb_default"

    def _get_store(self, session_id):
        """Return (and cache) the LangChain Chroma wrapper for a session."""
        from langchain_chroma import Chroma

        name = self._collection_name(session_id)
        with self._lock:
            store = self._stores.get(name)
            if store is None:
                store = Chroma(
                    client=self._chroma,
                    collection_name=name,
                    embedding_function=self.embeddings,
                    collection_metadata=COLLECTION_METADATA,
                )
                self._stores[name] = store
            return store

    def _scope_collections(self, session_id):
        """Collection identifiers to search: the session's own + the global KB."""
        sid = str(session_id)
        if sid == "global":
            return ["global"]
        return [sid, "global"]

    def _collection_file_ids(self, sid):
        """Distinct file_ids within a single collection."""
        if self._chroma is None:
            return []
        try:
            collection = self._chroma.get_collection(self._collection_name(sid))
            rows = collection.get(include=["metadatas"]).get("metadatas") or []
        except Exception:
            return []
        ids = []
        for meta in rows:
            fid = meta.get("file_id") if meta else None
            if fid and fid not in ids:
                ids.append(fid)
        return ids

    # ------------------------------------------------------------------
    # chunking
    # ------------------------------------------------------------------
    def _split_markdown(self, markdown):
        """Split Markdown into retrieval units.

        Sections delimited by headings are kept intact when they fit within
        CHUNK_SIZE; oversized sections are divided recursively while retaining
        their heading metadata. Documents with no headings fall back to a pure
        recursive split.
        """
        units = []
        for section in self._md_splitter.split_text(markdown):
            body = (section.page_content or "").strip()
            if not body:
                continue
            meta = {k: v for k, v in (section.metadata or {}).items() if v}
            if len(body) <= CHUNK_SIZE:
                units.append((body, meta))
            else:
                for piece in self._rec_splitter.split_text(body):
                    piece = piece.strip()
                    if piece:
                        units.append((piece, meta))

        if not units:
            for piece in self._rec_splitter.split_text(markdown):
                piece = piece.strip()
                if piece:
                    units.append((piece, {}))

        return units

    # ------------------------------------------------------------------
    # ingestion
    # ------------------------------------------------------------------
    def _build_sections(self, units):
        """Group consecutive chunks into sections by (h1, h2) heading.

        This is the "map" stage of a map-reduce style document index: each
        section gets a title plus a short preview (first chunk) that later lets
        retrieval locate the right section before reading it in full.
        """
        sections = []
        current = None
        for index, (text, meta) in enumerate(units):
            key = (meta.get("h1") or "", meta.get("h2") or "")
            if current is None or current["key"] != key:
                if current is not None:
                    sections.append(current)
                title = " > ".join(x for x in key if x) or "(Untitled)"
                current = {
                    "key": key,
                    "title": title,
                    "summary": (text or "")[:200],
                    "chunk_start": index,
                    "chunk_end": index,
                }
            else:
                current["chunk_end"] = index
        if current is not None:
            sections.append(current)
        return [
            {
                "title": s["title"],
                "summary": s["summary"],
                "chunk_start": s["chunk_start"],
                "chunk_end": s["chunk_end"],
            }
            for s in sections
        ]

    def index_document(self, file_content, session_id, filename=None, file_id=None, scope="global"):
        """Extract, chunk and embed one PDF into the knowledge base.

        ``scope`` is ``"global"`` (default) or ``"session"``. Global documents
        live in a shared collection visible to every conversation; session
        documents stay in the conversation's own collection. Re-uploading a
        filename within the same scope supersedes the previous copy.

        Returns a summary dict with ``file_id``, ``filename``, ``chunk_count``,
        ``char_count``, ``scope`` and ``elapsed``.
        """
        if scope not in ("global", "session"):
            scope = "global"
        target = "global" if scope == "global" else str(session_id)

        filename = filename or "document.pdf"
        started = time.time()

        markdown = extract_markdown_from_upload(file_content, filename)
        if not markdown:
            raise ValueError("no text could be extracted from the document")
        if markdown.startswith("Error"):
            raise ValueError(markdown)

        units = self._split_markdown(markdown)
        if not units:
            raise ValueError("the document produced no usable chunks")

        file_id = file_id or uuid.uuid4().hex

        # Build and persist the chapter skeleton (map-reduce "map" stage).
        try:
            import db
            sections = self._build_sections(units)
            if sections:
                db.save_sections(file_id, scope, target, sections)
        except Exception as exc:
            print(f"[RAG] build sections failed: {exc}")

        # A re-upload of the same filename in the same scope supersedes it.
        removed = self.delete_document(target, source=filename, scope=scope)
        if removed:
            print(f"[RAG] superseded {removed} existing chunk(s) of '{filename}'")

        store = self._get_store(target)

        texts = [u[0] for u in units]
        metadatas = []
        for index, (_, meta) in enumerate(units):
            md = {
                "source": filename,
                "file_id": file_id,
                "chunk_index": index,
                "session_id": target,
                "scope": scope,
            }
            for key in ("h1", "h2", "h3", "h4"):
                if meta.get(key):
                    md[key] = meta[key]
            metadatas.append(md)

        ids = [f"{file_id}-{i}" for i in range(len(units))]

        for start in range(0, len(texts), _ADD_BATCH_SIZE):
            stop = start + _ADD_BATCH_SIZE
            store.add_texts(
                texts=texts[start:stop],
                metadatas=metadatas[start:stop],
                ids=ids[start:stop],
            )

        self._bm25_cache.pop(self._collection_name(target), None)

        elapsed = time.time() - started
        print(
            f"[RAG] indexed '{filename}' -> {len(units)} chunks "
            f"in {elapsed:.1f}s (scope={scope})"
        )

        return {
            "file_id": file_id,
            "filename": filename,
            "chunk_count": len(units),
            "char_count": len(markdown),
            "scope": scope,
            "elapsed": round(elapsed, 1),
        }

    # ------------------------------------------------------------------
    # deletion
    # ------------------------------------------------------------------
    def delete_document(self, session_id, file_id=None, source=None, scope=None):
        """Remove one document's chunks.

        ``scope`` is "global", "session", or None (search both collections).
        Returns the number of chunks deleted.
        """
        if self._chroma is None or (file_id is None and source is None):
            return 0

        if scope == "global":
            sids = ["global"]
        elif scope == "session":
            sids = [str(session_id)]
        else:
            sids = self._scope_collections(session_id)

        where = {"file_id": file_id} if file_id else {"source": source}
        total = 0
        for sid in sids:
            name = self._collection_name(sid)
            try:
                collection = self._chroma.get_collection(name)
            except Exception:
                # Collection not created yet - nothing to delete.
                continue
            try:
                ids = collection.get(where=where, include=["metadatas"]).get("ids") or []
                if not ids:
                    continue
                collection.delete(ids=ids)
                total += len(ids)
                self._bm25_cache.pop(name, None)
            except Exception as exc:
                print(f"[RAG] delete_document failed ({name}): {exc}")
        return total

    def delete_session(self, session_id):
        """Drop the whole collection belonging to a conversation."""
        name = self._collection_name(session_id)
        with self._lock:
            self._stores.pop(name, None)
        if self._chroma is None:
            return False
        try:
            self._chroma.delete_collection(name)
            self._bm25_cache.pop(name, None)
            print(f"[RAG] collection dropped: {name}")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # inspection
    # ------------------------------------------------------------------
    def has_index(self, session_id):
        """True when the conversation or the global KB holds indexed chunks.

        Cheap: reads Chroma metadata only, never loads the embedding model.
        """
        if self._chroma is None or not session_id:
            return False
        for sid in self._scope_collections(session_id):
            try:
                collection = self._chroma.get_collection(self._collection_name(sid))
                if collection.count() > 0:
                    return True
            except Exception:
                continue
        return False

    def list_documents(self, session_id):
        """Aggregate indexed chunks per document across the session + global KB."""
        if self._chroma is None:
            return []

        aggregated = {}
        for sid in self._scope_collections(session_id):
            try:
                collection = self._chroma.get_collection(self._collection_name(sid))
                rows = collection.get(include=["metadatas"]).get("metadatas") or []
            except Exception:
                continue
            for meta in rows:
                if not meta:
                    continue
                fid = meta.get("file_id", "unknown")
                entry = aggregated.setdefault(
                    fid,
                    {
                        "file_id": fid,
                        "filename": meta.get("source", ""),
                        "chunk_count": 0,
                        "scope": meta.get("scope", "session"),
                    },
                )
                entry["chunk_count"] += 1

        return sorted(aggregated.values(), key=lambda d: d["filename"])

    def get_stats(self, session_id):
        """Summary of the knowledge base (session + global)."""
        if self._chroma is None:
            return {"chunk_count": 0, "document_count": 0, "documents": []}
        total = 0
        for sid in self._scope_collections(session_id):
            try:
                collection = self._chroma.get_collection(self._collection_name(sid))
                total += collection.count()
            except Exception:
                continue
        documents = self.list_documents(session_id)
        return {
            "chunk_count": total,
            "document_count": len(documents),
            "documents": documents,
        }

    # ------------------------------------------------------------------
    # retrieval
    # ------------------------------------------------------------------
    def _search(self, store, query, k, fetch_k, where):
        """MMR candidates with cosine scores, optionally filtered by metadata."""
        try:
            documents = store.max_marginal_relevance_search(
                query, k=k, fetch_k=fetch_k, lambda_mult=LAMBDA_MULT, filter=where
            )
        except Exception as exc:
            print(f"[RAG] MMR search failed: {exc}")
            return []

        if not documents:
            return []

        scores = {}
        try:
            for doc, score in store.similarity_search_with_relevance_scores(
                query, k=fetch_k, filter=where
            ):
                scores[doc.page_content] = score
        except Exception as exc:
            print(f"[RAG] relevance scoring unavailable: {exc}")

        results = []
        for doc in documents:
            results.append(
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata or {},
                    "score": scores.get(doc.page_content),
                }
            )
        return results

    def _retrieve_semantic(self, query, session_id, top_k, score_threshold):
        """Semantic (MMR) candidates above the noise floor, across session+global."""
        candidates = []
        seen = set()

        for sid in self._scope_collections(session_id):
            store = self._get_store(sid)
            file_ids = self._collection_file_ids(sid)
            if len(file_ids) <= 1:
                chunks = self._search(store, query, top_k, FETCH_K, None)
            else:
                per_doc = max(2, top_k // len(file_ids) + 1)
                chunks = []
                for fid in file_ids:
                    chunks.extend(
                        self._search(store, query, per_doc, FETCH_K, {"file_id": fid})
                    )
            for chunk in chunks:
                key = (chunk["metadata"].get("file_id"), chunk["content"])
                if key not in seen:
                    seen.add(key)
                    candidates.append(chunk)

        ranked = [
            c for c in candidates
            if c["score"] is None or c["score"] >= score_threshold
        ]
        ranked.sort(
            key=lambda c: c["score"] if c["score"] is not None else -1.0, reverse=True
        )
        return ranked

    def _bm25_entry(self, session_id):
        """Return (and cache) the BM25 index for a session, or None if empty."""
        name = self._collection_name(session_id)
        entry = self._bm25_cache.get(name)
        if entry is not None:
            return entry
        try:
            collection = self._chroma.get_collection(name)
            rows = collection.get(include=["documents", "metadatas"])
        except Exception:
            return None
        docs = rows.get("documents") or []
        metas = rows.get("metadatas") or []
        if not docs:
            return None
        entry = {"docs": docs, "metas": metas, "bm25": _BM25(docs)}
        self._bm25_cache[name] = entry
        return entry

    def _retrieve_bm25(self, query, session_id, k):
        """Keyword (BM25) candidates across the session + global KB."""
        results = []
        for sid in self._scope_collections(session_id):
            entry = self._bm25_entry(sid)
            if entry is None:
                continue
            metas = entry["metas"]
            for idx, score in entry["bm25"].search(query, k=k):
                results.append(
                    {
                        "content": entry["docs"][idx],
                        "metadata": (metas[idx] or {}) if idx < len(metas) else {},
                        "score": None,
                        "bm25": score,
                    }
                )
        return results

    def _expand_by_section(self, items, session_id):
        """Expand retrieved chunks to their full sections (map-reduce "reduce").

        For each hit, locate its section range via document_sections and pull in
        the whole section, so the LLM sees complete chapters instead of isolated
        fragments. Chunks are appended in document order after the top hits.
        """
        if not items or self._chroma is None:
            return items
        try:
            import db
        except Exception:
            return items

        sections_by_file = {}
        for s in db.get_sections(session_id):
            sections_by_file.setdefault(s["file_id"], []).append(s)

        wanted = {}
        for it in items:
            meta = it.get("metadata") or {}
            fid = meta.get("file_id")
            cidx = meta.get("chunk_index")
            if fid is None or cidx is None:
                continue
            for s in sections_by_file.get(fid, []):
                if s["chunk_start"] <= cidx <= s["chunk_end"]:
                    span = s["chunk_end"] - s["chunk_start"] + 1
                    if span <= MAX_SECTION_CHUNKS:
                        wanted.setdefault(fid, set()).update(range(s["chunk_start"], s["chunk_end"] + 1))
                    else:
                        lo = max(s["chunk_start"], cidx - CONTEXT_WINDOW)
                        hi = min(s["chunk_end"], cidx + CONTEXT_WINDOW)
                        wanted.setdefault(fid, set()).update(range(lo, hi + 1))
                    break

        if not wanted:
            return items

        expanded = {}
        for sid in self._scope_collections(session_id):
            try:
                collection = self._chroma.get_collection(self._collection_name(sid))
            except Exception:
                continue
            for fid, indices in wanted.items():
                try:
                    rows = collection.get(where={"file_id": fid}, include=["documents", "metadatas"])
                except Exception:
                    continue
                docs = rows.get("documents") or []
                metas = rows.get("metadatas") or []
                ids = rows.get("ids") or []
                for cid, doc, meta in zip(ids, docs, metas):
                    if (meta or {}).get("chunk_index") in indices:
                        expanded[cid] = {"content": doc, "metadata": meta, "score": None}

        if not expanded:
            return items

        seen = {it["content"] for it in items}
        extra = [it for it in expanded.values() if it["content"] not in seen]
        extra.sort(key=lambda x: ((x.get("metadata") or {}).get("file_id", ""),
                                  (x.get("metadata") or {}).get("chunk_index", 0)))
        merged = items + extra
        if len(merged) > MAX_TOTAL_CHUNKS:
            merged = merged[:MAX_TOTAL_CHUNKS]
        return merged

    def retrieve(self, query, session_id, top_k=TOP_K, score_threshold=SCORE_THRESHOLD, priority_file_ids=None):
        """Hybrid retrieval: semantic MMR + BM25 keyword, fused via RRF.

        Returns up to ``top_k`` passages; each carries ``score`` (cosine, may be
        None for keyword-only hits) and, when applicable, ``bm25``. An empty
        list means neither source found anything above its floor, which the
        caller treats as "the knowledge base does not cover this".
        """
        if not query or not self.has_index(session_id):
            return []

        # priority_file_ids: None = keep all (kb_browse); a set = filter to these files
        semantic = self._retrieve_semantic(query, session_id, top_k, score_threshold)
        bm25 = self._retrieve_bm25(query, session_id, top_k * 2) if HYBRID_ENABLED else []

        if not semantic and not bm25:
            print("[RAG] retrieve: no passage above the noise floor")
            return []

        # Reciprocal Rank Fusion merges the two incompatible score scales.
        rrf = {}
        by_key = {}
        for rank, item in enumerate(semantic):
            key = item["content"]
            by_key[key] = item
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, item in enumerate(bm25):
            key = item["content"]
            if key not in by_key:
                by_key[key] = item
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

        if priority_file_ids is not None:
            by_key = {k: v for k, v in by_key.items()
                      if (v.get("metadata") or {}).get("file_id") in priority_file_ids}

        ranked = sorted(
            by_key.values(),
            key=lambda it: rrf[it["content"]]
            + (PRIORITY_BONUS if (it.get("metadata") or {}).get("file_id") in (priority_file_ids or set()) else 0.0),
            reverse=True,
        )
        results = ranked[:top_k]
        for item in results:
            item["rrf"] = round(rrf[item["content"]], 4)

        best_cos = max((c["score"] for c in results if c.get("score") is not None), default=None)
        label = f"cos={best_cos:.4f}" if best_cos is not None else "keyword-only"
        results = self._expand_by_section(results, session_id)
        print(f"[RAG] retrieve (hybrid): {len(results)} passages, {label}")
        return results

    def get_document_overview(self, session_id, max_chars=600, priority_file_ids=None):
        """Return one leading chunk per document, across session + global KB.

        Cheap: reads Chroma documents/metadata only, never loads the embedding
        model. Used to tell the model how many files exist and what each one
        is about before it reasons over the retrieved passages.
        """
        if self._chroma is None:
            return []

        docs = []
        metas = []
        for sid in self._scope_collections(session_id):
            try:
                collection = self._chroma.get_collection(self._collection_name(sid))
                rows = collection.get(include=["documents", "metadatas"])
            except Exception:
                continue
            docs.extend(rows.get("documents") or [])
            metas.extend(rows.get("metadatas") or [])

        first = {}
        for text, meta in zip(docs, metas):
            if not meta:
                continue
            fid = meta.get("file_id")
            if fid is None:
                continue
            idx = meta.get("chunk_index", 0)
            cur = first.get(fid)
            if cur is None or idx < cur["chunk_index"]:
                first[fid] = {
                    "filename": meta.get("source", ""),
                    "chunk_index": idx,
                    "text": text,
                }

        overview = []
        if priority_file_ids:
            first = {fid: entry for fid, entry in first.items() if fid in priority_file_ids}
        for fid in sorted(first, key=lambda f: first[f]["filename"]):
            entry = first[fid]
            text = (entry["text"] or "").strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "…"
            overview.append({"filename": entry["filename"], "excerpt": text})
        return overview


# A module-level instance is convenient for the server and the chat backend;
# creating it does not load the embedding model.
_default_service = None


def get_rag_service():
    """Lazily create the shared RagService instance."""
    global _default_service
    if _default_service is None:
        _default_service = RagService()
    return _default_service

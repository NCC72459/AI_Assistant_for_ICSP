import os
import sys
import asyncio
import json
import httpx
import re
import datetime
from typing import Optional, List, Dict, Callable, Tuple
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import MessagesState
from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, Field
from typing import AsyncGenerator

# Language Detections
def detect_language(text: str) -> str:
    """Detect if the input text is primarily Chinese ('zh') or other ('en')."""
    if not text:
        return 'en'
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return 'zh' if chinese_chars >= 3 else 'en'


# ======================================Environment Variables=======================================


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BACKEND_DIR)
_ENV_CANDIDATES = (
    os.path.join(_BACKEND_DIR, "aiapi.env"),              # backend/ (canonical)
    "aiapi.env",                                          # working directory
    os.path.join(_ROOT_DIR, "aiapi.env"),                 # project root
    os.path.join(_ROOT_DIR, "frontend", "aiapi.env"),     # frontend/ (legacy)
)
ENV_FILE = next((p for p in _ENV_CANDIDATES if os.path.exists(p)), _ENV_CANDIDATES[0])
if os.path.exists(ENV_FILE):
    print(f"[ENV] Loading from {ENV_FILE}...")
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
                print(f"  - {key} loaded")
else:
    print(f"[WARN] {ENV_FILE} not found, using defaults")


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY")
BOCHA_API_URL = os.getenv("BOCHA_API_URL", "https://api.bocha.cn/v1/web-search")


def get_api_config() -> dict:
    """Return the current API configuration (for the settings UI)."""
    return {
        "deepseek_api_key": DEEPSEEK_API_KEY or "",
        "deepseek_base_url": DEEPSEEK_BASE_URL or "",
        "deepseek_model": DEEPSEEK_MODEL or "",
        "bocha_api_key": BOCHA_API_KEY or "",
    }


def update_api_config(config: dict) -> dict:
    """Update API keys / model at runtime and persist them to the env file.

    Only non-empty values are applied, so a settings form can send empty
    fields to mean "leave unchanged". The LangGraph fallback path keeps the
    values captured at import time; the primary stream path and image upload
    read these globals live, so the change takes effect on the next request.
    """
    global DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, BOCHA_API_KEY
    if config.get("deepseek_api_key"):
        DEEPSEEK_API_KEY = config["deepseek_api_key"]
        os.environ["DEEPSEEK_API_KEY"] = config["deepseek_api_key"]
    if config.get("deepseek_base_url"):
        DEEPSEEK_BASE_URL = config["deepseek_base_url"]
        os.environ["DEEPSEEK_BASE_URL"] = config["deepseek_base_url"]
    if config.get("deepseek_model"):
        DEEPSEEK_MODEL = config["deepseek_model"]
        os.environ["DEEPSEEK_MODEL"] = config["deepseek_model"]
    if config.get("bocha_api_key"):
        BOCHA_API_KEY = config["bocha_api_key"]
        os.environ["BOCHA_API_KEY"] = config["bocha_api_key"]
    _persist_env()
    return get_api_config()


def _persist_env():
    """Write the current API config back to the canonical env file."""
    try:
        updates = {
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY or "",
            "DEEPSEEK_BASE_URL": DEEPSEEK_BASE_URL or "",
            "DEEPSEEK_MODEL": DEEPSEEK_MODEL or "",
            "BOCHA_API_KEY": BOCHA_API_KEY or "",
        }
        lines = []
        if os.path.isfile(ENV_FILE):
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        seen = set()
        out = []
        for line in lines:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                out.append(line)
        for key, val in updates.items():
            if key not in seen:
                out.append(f"{key}={val}")
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        print("[API] env file updated")
    except Exception as exc:
        print(f"[API] persist env failed: {exc}")


# ======================================RAG Service (personal knowledge base)======================================


_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    _HERE,
    os.path.join(_HERE, "frontend"),
    os.path.join(os.path.dirname(_HERE), "frontend"),
):
    if os.path.isfile(os.path.join(_candidate, "rag_service.py")):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

try:
    from rag_service import RagService # type: ignore

    rag_service = RagService()
    RAG_AVAILABLE = True
    print(f"[RAG] knowledge base available (store: {rag_service.persist_dir})")
except Exception as _rag_error:
    rag_service = None
    RAG_AVAILABLE = False
    print(f"[WARN] RAG unavailable: {_rag_error}")


def _truncate(text: str, limit: int) -> str:
    """Shorten a string for display, marking that it was cut."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n...(truncated)"


def _format_retrieved_context(chunks: list) -> str:
    """Render retrieved passages as a numbered, source-labelled block."""
    parts = []
    for index, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata") or {}
        section = " > ".join(
            meta[key] for key in ("h1", "h2", "h3", "h4") if meta.get(key)
        )
        label = " / ".join(part for part in (meta.get("source", ""), section) if part)
        score = chunk.get("score")
        if score is not None:
            score_label = f"score {score:.2f}"
            label = f"{score_label} | {label}" if label else score_label
        header = f"[Passage {index}]" + (f" ({label})" if label else "")
        parts.append(f"{header}\n{chunk['content']}")
    return "\n\n".join(parts)


# Multi-source orchestrations
_REALTIME_KEYWORDS = (
    "today", "now", "latest", "news", "weather", "current", "recent", "breaking",
)


def _has_realtime_keyword(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in _REALTIME_KEYWORDS)


def _format_web_results(results: list, lang: str) -> str:
    header = "[Web Search Results]"
    lines = [header]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', 'No title')}")
        lines.append(f"   {r.get('body', '')}")
        src = r.get("site", "")
        date = r.get("date", "")
        if src or date:
            suffix = f"{src}  |  {date[:10]}" if date else src
            lines.append(f"   Source: {suffix}")
        if r.get("href"):
            lines.append(f"   URL: {r.get('href')}")
    return "\n".join(lines)


def _load_kb_memory_context() -> str:
    """Load model-written KB memories (file list + per-file summaries)."""
    try:
        import db # type: ignore
        mems = db.get_all_memories()
    except Exception:
        return ""
    if not mems:
        return ""
    lines = []
    for m in mems:
        if m.get("kind") == "file_list":
            lines.append(f"[KB Files]\n{m['content']}")
        else:
            lines.append(f"[File Summary] {m['content']}")
    return "\n".join(lines)


def _is_summary_task(message: str) -> bool:
    """Detect summarization/enumeration tasks that need the full document."""
    m = (message or "").lower()
    keywords = (
        "summary", "summarize", "summarise", "overview", "synopsis",
        "sum up", "main points", "key points", "list all", "what are the",
        "what are all", "give me an overview", "what is this document",
        "what does this document",
    )
    return any(k in m for k in keywords)


def _build_sections_context(session_id: str) -> str:
    """Build a full-document overview from the chapter skeleton (map stage)."""
    try:
        import db # type: ignore
    except Exception:
        return ""
    sections = db.get_sections(session_id)
    if not sections:
        return ""
    lines = []
    for s in sections:
        title = s.get("title") or "(Untitled)"
        summary = (s.get("summary") or "").strip()
        lines.append(f"## {title}\n{summary}")
    return "\n\n".join(lines)


def _build_local_context(retrieved: list, overview: list) -> str:
    parts = []
    if len(overview) > 1:
        lines = ["[Document Overview]"]
        for o in overview:
            lines.append(f"- {o['filename']}\n{o['excerpt']}")
        parts.append("\n\n".join(lines))
    parts.append(_format_retrieved_context(retrieved))
    return "\n\n".join(parts)


def _plan_desc(use_local: bool, use_web: bool, lang: str) -> str:
    if use_local and use_web:
        return "Local KB + Web Search"
    if use_local:
        return "Local KB"
    if use_web:
        return "Web Search"
    return "General Chat"


def _build_synthesis_prompt(lang: str, current_date: str, local_text: str, web_text: str) -> str:
    blocks = []
    if local_text:
        blocks.append(f"[Local Document Passages]\n{local_text}")
    if web_text:
        blocks.append(f"[Web Search Results]\n{web_text}")
    context = "\n\n".join(blocks)

    if lang == "zh":
        sys = f"Current date: {current_date}.\n"
        if context:
            sys += f"The following material is available:\n\n{context}\n\n"
        sys += (
            "你是 DeepSeek（深度求索）开发的大语言模型；若被问及身份，请如实说明。\n"
            "Answer the user's question. You may combine: (1) the [Local document] passages, (2) the "
            "[Web search] results, and (3) your own knowledge. Cite [Local] for document content and [Web] "
            "for web content; for your own reasoning, state the basis. If a source does not cover something, say so honestly; do not fabricate."
        )
    else:
        sys = f"Current date: {current_date}.\n"
        if context:
            sys += f"The following material is available:\n\n{context}\n\n"
        sys += (
            "You are DeepSeek, a large language model developed by DeepSeek (深度求索). "
            "If asked about your identity, answer accordingly.\n"
            "Answer the user's question. You may combine: (1) the [Local document] passages, "
            "(2) the [Web search] results, and (3) your own knowledge. Cite [Local] for document "
            "content and [Web] for web content; for your own reasoning, state the basis. "
            "If a source does not cover something, say so honestly; do not fabricate."
        )
    return sys


def _estimate_text_tokens(text: str) -> int:
    """Rough token estimate: CJK ~1 token/char, latin ~0.25 token/char."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cjk
    return int(cjk + other * 0.25 + 1)


def _estimate_context_tokens(system_message: str, images: list) -> dict:
    """Estimate the current turn's context usage (text + images)."""
    text_tokens = _estimate_text_tokens(system_message or "")
    image_count = len(images or [])
    image_tokens = image_count * 1024  # conservative per-image upper bound
    return {
        "total_tokens": text_tokens + image_tokens,
        "text_tokens": text_tokens,
        "image_tokens": image_tokens,
        "image_count": image_count,
    }


if sys.platform == "win32":
    import locale
    try:
        locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')
    except:
        pass

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("[WARN] Install: pip install beautifulsoup4 lxml")

class StreamPrinter(BaseCallbackHandler):
    """Real-time LLM token output handler."""
    def __init__(self):
        self.text = ""
        self.in_prefix = True
    
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.text += token
        if self.in_prefix and ("【" in self.text or "DeepSeek" in self.text):
            if "\n" in self.text:
                self.in_prefix = False
                after_newline = self.text.split("\n", 1)[1]
                if after_newline:
                    print(after_newline, end="", flush=True)
            return
        if not self.in_prefix:
            print(token, end="", flush=True)



# ======================================Tool 1: Web Search (Bocha API)======================================

class WebSearchInput(BaseModel):
    query: str = Field(description="Search keyword, e.g. 'weather Beijing'")


def search_bocha(query: str, max_results: int = 10) -> List[Dict]:
    headers = {
        "Authorization": f"Bearer {BOCHA_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "query": query,
        "count": max_results,
        "summary": True,
        "freshness": "noLimit"
    }
    
    try:
        print(f"\n[DEBUG] Bocha API: {BOCHA_API_URL}")
        print(f"[DEBUG] Query: '{query}', count={max_results}")
        
        resp = httpx.post(BOCHA_API_URL, json=payload, headers=headers, timeout=30)
        
        print(f"[DEBUG] Status: {resp.status_code}")
        resp.raise_for_status()
        
        data = resp.json()
        response_data = data.get("data", data)
        
        if "webPages" in response_data and "value" in response_data["webPages"]:
            raw_results = response_data["webPages"]["value"]
            print(f"[DEBUG] Got {len(raw_results)} results from data.webPages.value")
        else:
            print(f"[DEBUG] Response keys: {list(data.keys())}")
            return []
        
        results = []
        for item in raw_results[:max_results]:
            results.append({
                'title': item.get('name', 'No title'),
                'body': item.get('summary', item.get('snippet', 'No summary')),
                'href': item.get('url', ''),
                'site': item.get('siteName', ''),
                'date': item.get('datePublished', '')
            })
        
        print(f"[DEBUG] Parsed {len(results)} results")
        return results
        
    except Exception as e:
        print(f"[ERROR] Bocha search: {e}")
        import traceback
        traceback.print_exc()
        return []


@tool("web_search", args_schema=WebSearchInput)
def web_search(query: str) -> str:
    """
    Search the internet for real-time information.
    Use for weather, news, encyclopedia, current events.
    """
    if not BOCHA_API_KEY or BOCHA_API_KEY == "your-bocha-api-key":
        return ("Error: Bocha API Key not configured.\n"
                "Get one at: https://open.bocha.cn")
    
    results = search_bocha(query, 10)
    
    if not results:
        return (f"No results found for '{query}'.\n"
                f"Tips:\n"
                f"1. Check your API key\n"
                f"2. Try a more specific query")
    
    lang = detect_language(query)
    if lang == 'zh':
        output = f"【Web Search Results】\nQuery: {query}\n\n"
    else:
        output = f"[Web Search Results]\nQuery: {query}\n\n"
    
    for i, r in enumerate(results, 1):
        title = r.get('title', 'No title')
        body = r.get('body', 'No summary')
        href = r.get('href', '')
        site = r.get('site', '')
        date = r.get('date', '')
        
        output += f"{i}. {title}\n"
        if lang == 'zh':
            output += f"   Summary: {body}\n"
        else:
            output += f"   Snippet: {body}\n"
        if site or date:
            if lang == 'zh':
                output += "   Source: "
            else:
                output += "   Source: "
            if site:
                output += f"{site}"
            if date:
                output += f"  |  {date[:10]}"
            output += "\n"
        output += f"   URL: {href}\n\n"
    
    return output.strip()



# ======================================Tool 2: Read Webpage======================================


class ReadWebpageInput(BaseModel):
    url: str = Field(description="Full URL of the webpage to read")


@tool("read_webpage", args_schema=ReadWebpageInput)
def read_webpage(url: str) -> str:
    """Read and extract the main text content of a webpage."""
    if not HAS_BS4:
        return "Error: Install beautifulsoup4 first: pip install beautifulsoup4 lxml"
    
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'lxml')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        
        text = soup.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        clean_text = '\n'.join(lines[:200])
        
        if len(lines) > 200:
            clean_text += '\n\n...(content truncated)'
        
        title = soup.title.string if soup.title else "No title"
        return f"[Webpage Content]\nTitle: {title}\nSource: {url}\n\n{clean_text}"
        
    except Exception as e:
        return f"Error reading webpage: {str(e)}"


# ======================================Tool 3: KB memory write (model-writable file list + summaries)======================================


class WriteMemoryInput(BaseModel):
    kind: str = Field(description="Memory type: 'file_list' (the file list, fixed at id 0) or 'file_summary' (a single file's summary)")
    content: str = Field(description="Memory content")
    memory_id: Optional[int] = Field(default=None, description="Memory id to overwrite; omit to append")
    file_id: str = Field(default="", description="Associated file id (fill when writing a file summary; findable in the file list at memory id 0)")


@tool("write_kb_memory", args_schema=WriteMemoryInput)
def write_kb_memory(kind: str, content: str, memory_id: Optional[int] = None, file_id: str = "") -> str:
    """Write an entry to the knowledge-base memory. Memory id 0 is the file list; the rest are per-file summaries."""
    try:
        import db # type: ignore
        mid = db.write_memory(kind, content, memory_id, file_id)
        if mid < 0:
            return "Memory write failed (the 1024-entry limit was reached or an error occurred)."
        return f"Memory written at id={mid}."
    except Exception as e:
        return f"Memory write failed: {e}"


# ======================================Tool 4: KB memory read======================================


class ReadMemoryInput(BaseModel):
    memory_id: int = Field(description="Memory id to read")


@tool("read_kb_memory", args_schema=ReadMemoryInput)
def read_kb_memory(memory_id: int) -> str:
    """Read a knowledge-base memory entry (file list or file summary)."""
    try:
        import db # type: ignore
        m = db.get_memory(memory_id)
        if not m:
            return "Memory entry not found."
        return f"[Memory id={m['id']} kind={m['kind']}]\n{m['content']}"
    except Exception as e:
        return f"Read memory failed: {e}"



# DeepSeek LLM Configuration


llm = ChatOpenAI(
    model=DEEPSEEK_MODEL,
    openai_api_key=DEEPSEEK_API_KEY,
    openai_api_base=DEEPSEEK_BASE_URL,
    temperature=0.7,
    max_tokens=16384
)

stream_handler = StreamPrinter()
llm_streaming = ChatOpenAI(
    model=DEEPSEEK_MODEL,
    openai_api_key=DEEPSEEK_API_KEY,
    openai_api_base=DEEPSEEK_BASE_URL,
    temperature=0.7,
    max_tokens=4096,
    streaming=True,
    callbacks=[stream_handler]
)

tools = [web_search, read_webpage, write_kb_memory, read_kb_memory]
llm_with_tools = llm.bind_tools(tools)
llm_with_tools_streaming = llm_streaming.bind_tools(tools)


TOOL_REGISTRY: Dict[str, Tuple[Callable, str, str]] = {
    "web_search": (web_search, "[Web Search]", "llm_summarize"),
    "read_webpage": (read_webpage, "[Page Reader]", "llm_summarize"),
    "write_kb_memory": (write_kb_memory, "[KB Memory]", "llm_summarize"),
    "read_kb_memory": (read_kb_memory, "[KB Memory]", "llm_summarize"),
}



# ======================================Intent Classification======================================



class IntentRouter:
    """Keyword-based intent router (fallback for LLM classifier)."""
    
    # Keywords for matching user input
    SEARCH_KEYWORDS = [
        'weather', 'news', 'latest', 'today', 'tomorrow', 'real-time', 'search',
        'find', 'lookup', 'stock', 'exchange rate', 'price', 'temperature',



    ]
    
    FILE_KEYWORDS = [
        'file', 'document', 'PDF', 'upload', 'attachment',
        'read it', 'take a look', 'content',
        'this file', 'this document', 'material',
        'report', 'article', 'chapter', 'section',
        'page', 'paragraph',
    ]
    URL_PATTERN = re.compile(r'https?://[^\s]+')
    
    @classmethod
    def classify(cls, text: str, has_file_context: bool = False) -> str:
        if cls.URL_PATTERN.search(text):
            return 'read_url'
        for kw in cls.SEARCH_KEYWORDS:
            if re.search(kw, text, re.IGNORECASE):
                return 'search'
        if has_file_context:
            for kw in cls.FILE_KEYWORDS:
                if re.search(kw, text, re.IGNORECASE):
                    return 'file_qa'
            return 'file_qa'
        return 'chat'


def classify_intent_with_llm(user_message: str, has_file_context: bool = False) -> str:
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    lang = detect_language(user_message)
    
    context_hint = ""
    if has_file_context:
        context_hint = (
            "\nContext: The user has uploaded documents in this conversation and a "
            "knowledge base is available. Any question that could plausibly be "
            "answered from those documents must be classified as file_qa. Only "
            "greetings or clearly file-independent small talk may be classified as chat."
        )
    
    if lang == 'zh':
        classification_prompt = f"""You are an intent classifier. Current date: {current_date}.
Analyze the user input and determine the most suitable intent type.

Available intent types:
- search: User needs real-time information (weather, news, search query)
- read_url: User provided a URL (http/https) and wants to read the webpage
- file_qa: User uploaded a file and is asking questions about the file content
- kb_browse: User asks what files are in the knowledge base, or does a fuzzy search across it (e.g. "what files do you have", "is there anything about X")
- chat: General conversation, casual chat, questions that don't need tools

Rules:
- If the input contains http:// or https:// URL, classify as read_url
- If the user needs real-time or latest information, classify as search
- If a file has been uploaded in this conversation, classify as file_qa whenever the question could plausibly be answered from that file: facts, data, conclusions, findings, people, organisations, figures, dates, terminology
- Choose chat only for greetings or small talk that clearly has nothing to do with the file
{context_hint}

User input: {user_message}

Return ONLY one word (search / read_url / file_qa / kb_browse / chat):"""
    else:
        classification_prompt = f"""You are an intent classifier. Current date: {current_date}.
Analyze the user input and determine the most suitable intent type.

Available intent types:
- search: User needs real-time information (weather, news, search query)
- read_url: User provided a URL (http/https) and wants to read the webpage
- file_qa: User uploaded a file and is asking questions about the file content
- kb_browse: User asks what files are in the knowledge base, or does a fuzzy search across it (e.g. "what files do you have", "is there anything about X")
- chat: General conversation, casual chat, questions that don't need tools

Rules:
- If the input contains http:// or https:// URL, classify as read_url
- If the user needs real-time or latest information, classify as search
- If a file has been uploaded in this conversation, classify as file_qa whenever the question could plausibly be answered from that file: facts, data, conclusions, findings, people, organisations, figures, dates, terminology
- Choose chat only for greetings or small talk that clearly has nothing to do with the file
- When a file is present and you are unsure, prefer file_qa over chat
{context_hint}

User input: {user_message}

Return ONLY one word (search / read_url / file_qa / kb_browse / chat):"""
    
    try:
        response = llm.invoke([{"role": "user", "content": classification_prompt}])
        intent = response.content.strip().lower().rstrip('.。')
        if intent in ('search', 'read_url', 'file_qa', 'kb_browse', 'chat'):
            return intent
        else:
            return IntentRouter.classify(user_message, has_file_context)
    except Exception:
        return IntentRouter.classify(user_message, has_file_context)


def semantic_router(state: MessagesState):
    messages = state["messages"]
    user_message = messages[-1].content
    lang = detect_language(user_message)
    
    has_file_context = False
    for msg in messages:
        if (hasattr(msg, 'type') and getattr(msg, 'type', None) == 'file_context') or \
           (isinstance(msg, dict) and msg.get("type") == "file_context"):
            has_file_context = True
            break
    
    intent = classify_intent_with_llm(user_message, has_file_context=has_file_context)
    current_date = datetime.datetime.now().strftime("%B %d, %Y")
    
    intent_prompts = {
        'search': (
            f"[System]User needs real-time info (weather, news, etc.). "
            f"Current date: {current_date}. You MUST call the web_search tool first. "
            f"Do NOT answer directly."
        ) if lang == 'en' else (
            f"[System] User needs real-time info (weather, news, etc.). "
            f"Current date: {current_date}. You MUST call the web_search tool first. Do NOT answer directly."
        ),
        'read_url': (
            "[System]User provided a URL. You MUST call the read_webpage tool first. "
            "Do NOT answer directly."
        ) if lang == 'en' else (
            "[System] User provided a URL. You MUST call the read_webpage tool first. "
            "Do NOT answer directly."
        ),
        'file_qa': (
            "[System]A file has been uploaded. The full document text is in the conversation "
            "history as a system (type=file_context) message. "
            "Answer based on the file content. If the file doesn't contain the relevant "
            "information, tell the user honestly. "
            "Cite the original text when possible. Do NOT use any tools."
        ) if lang == 'en' else (
            "[System] A file has been uploaded. The full document text is in the conversation history. "
            "Answer based on the file content. If the file doesn't contain the relevant information, tell the user honestly. "
            "Cite the original text when possible. Do NOT use any tools."
        ),
        'chat': (
            f"[System]General conversation. Answer with your own knowledge. "
            f"Current date: {current_date}. Do NOT use any tools."
        ) if lang == 'en' else (
            f"[System] General conversation. Answer with your own knowledge. "
            f"Current date: {current_date}. Do NOT use any tools."
        ),
    }
    
    system_msg = SystemMessage(
        content=f"[Intent] {intent}\n\n{intent_prompts[intent]}"
    )
    
    return {"messages": messages + [system_msg]}



# ======================================Tool Calling & Streaming Logic======================================


def call_deepseek_with_tools(state: MessagesState):
    messages = state["messages"]
    
    stream_handler.text = ""
    stream_handler.in_prefix = True
    
    response = llm_with_tools_streaming.invoke(messages)

    if response.tool_calls:
        tool_messages = []
        last_tool_name = ""
        last_tool_result = ""
        last_prefix = ""
        
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            
            if tool_name in TOOL_REGISTRY:
                func, prefix, strategy = TOOL_REGISTRY[tool_name]
                tool_result = func.invoke(
                    input=tool_call["args"], config={"callbacks": None}
                )
            else:
                tool_result = f"Unknown tool: {tool_name}"
                prefix = "[Unknown]"
                strategy = "raw"
            
            last_tool_name = tool_name
            last_tool_result = tool_result
            last_prefix = prefix
            
            tool_messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tool_call["id"])
            )
        
        if last_tool_name in TOOL_REGISTRY:
            _, _, strategy = TOOL_REGISTRY[last_tool_name]
        else:
            strategy = "raw"
        
        if strategy == "llm_summarize":
            print(f"{last_prefix}", end="", flush=True)
            
            summary_instruction = SystemMessage(
                content="You have received tool results. "
                        "Summarize the information in a concise, natural way. "
                        "Do NOT just repeat the raw results. "
                        "Extract key information and present it in a readable format."
            )
            
            messages_with_results = messages + [response] + tool_messages + [summary_instruction]
            stream_handler.in_prefix = False
            
            full_content = ""
            for chunk in llm_with_tools_streaming.stream(messages_with_results):
                if hasattr(chunk, 'content') and chunk.content:
                    full_content += chunk.content
            
            print()
            return {"messages": [response] + tool_messages + [AIMessage(content=f"{last_prefix}\n{full_content}")]}
        else:
            print(f"{last_prefix}", end="", flush=True)
            print(f"\n{last_tool_result}")
            return {"messages": [response] + tool_messages + [AIMessage(content=f"{last_prefix}\n{last_tool_result}")]}

    print("Assistant: ", end="", flush=True)
    stream_handler.in_prefix = False
    
    full_content = ""
    for chunk in llm_with_tools_streaming.stream(messages):
        if hasattr(chunk, 'content') and chunk.content:
            full_content += chunk.content
    
    print()
    response.content = full_content
    response.content = f"Assistant: {response.content}"
    return {"messages": [response]}



# ======================================LangGraph Definition======================================


builder = StateGraph(MessagesState)
builder.add_node("router", semantic_router)
builder.add_node("deepseek_node", call_deepseek_with_tools)
builder.add_edge(START, "router")
builder.add_edge("router", "deepseek_node")
builder.add_edge("deepseek_node", END)
graph = builder.compile()



# ======================================DeepSeek Files API (vision images)======================================


_IMAGE_EXPIRES_SECONDS = 604800  # 7 days


def upload_image_to_deepseek(data: bytes, filename: str, mime_type: str) -> str:
    """Upload image bytes to DeepSeek ``/files`` (purpose=user_data).

    Files expire after 7 days; the model references them by id, so the bytes
    are not re-sent on every turn.
    """
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    fields = {
        "purpose": "user_data",
        "expires_after[anchor]": "created_at",
        "expires_after[seconds]": str(_IMAGE_EXPIRES_SECONDS),
    }
    files = {"file": (filename, data, mime_type)}
    resp = httpx.post(
        f"{DEEPSEEK_BASE_URL}/files",
        headers=headers,
        data=fields,
        files=files,
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def delete_image_from_deepseek(file_id: str) -> bool:
    """Delete a file previously uploaded to DeepSeek ``/files``."""
    try:
        resp = httpx.delete(
            f"{DEEPSEEK_BASE_URL}/files/{file_id}",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=30.0,
        )
        return resp.status_code == 200
    except Exception as exc:  # noqa: BLE001
        print(f"[Image] delete from DeepSeek failed: {exc}")
        return False



# ======================================Direct DeepSeek API Call (thinking mode)======================================

CHAT_HISTORY_MAX_MESSAGES = int(os.getenv("CHAT_HISTORY_MAX_MESSAGES", "20"))
CHAT_HISTORY_MAX_CHARS = int(os.getenv("CHAT_HISTORY_MAX_CHARS", "12000"))
CHAT_HISTORY_PER_MSG_CHARS = int(os.getenv("CHAT_HISTORY_PER_MSG_CHARS", "4000"))


def _build_chat_history(messages: list) -> list:
    """Return a bounded list of prior {role, content} turns for the model.

    The current (last) user message is excluded - it is sent separately with
    any image blocks - so the model never sees it twice. When the count or
    character budget is exceeded the oldest turns are dropped first.
    """
    turns = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "file_context":
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        turns.append({"role": role, "content": content})

    if turns and turns[-1]["role"] == "user":
        turns.pop()  # the current user message is sent separately

    selected = []
    total = 0
    for turn in reversed(turns[-CHAT_HISTORY_MAX_MESSAGES:]):
        text = turn["content"]
        if len(text) > CHAT_HISTORY_PER_MSG_CHARS:
            text = text[:CHAT_HISTORY_PER_MSG_CHARS] + " ...(truncated)"
        if selected and total + len(text) > CHAT_HISTORY_MAX_CHARS:
            break
        selected.append({"role": turn["role"], "content": text})
        total += len(text)
    selected.reverse()
    return selected

async def call_deepseek_direct_stream(
    message: str,
    system_message: str = None,
    thinking_enabled: bool = True,
    reasoning_effort: str = "high",
    images: list = None,
    history: list = None,
) -> AsyncGenerator[dict, None]:
    """
    Call DeepSeek API directly (stream=True), bypassing LangChain.
    Supports thinking mode with reasoning_content capture.

    When ``images`` is supplied, the user content becomes a block array
    (text + image/file blocks) so the vision model can see the attachments.
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload_messages = []
    if system_message:
        payload_messages.append({"role": "system", "content": system_message})

    # Prior turns (length-controlled) so follow-ups such as "shorten that
    # reply" or "continue from point two" can actually see the conversation.
    # The current user message is appended below and never duplicated here.
    if history:
        payload_messages.extend(history)

    if images:
        content = [{"type": "text", "text": message}]
        content.extend(images)
        payload_messages.append({"role": "user", "content": content})
    else:
        payload_messages.append({"role": "user", "content": message})

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": payload_messages,
        "stream": True,
        "max_tokens": 8192,
        "temperature": 0.7
    }

    if thinking_enabled:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = reasoning_effort

    reasoning_content = ""
    content = ""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                json=payload,
                headers=headers
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield {
                        "type": "error",
                        "content": f"API Error ({response.status_code}): "
                                   f"{error_text.decode('utf-8', errors='replace')}"
                    }
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if not chunk.get("choices"):
                        continue

                    delta = chunk["choices"][0].get("delta", {})

                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        rc = delta["reasoning_content"]
                        reasoning_content += rc
                        yield {"type": "reasoning_token", "content": rc}

                    if "content" in delta and delta["content"]:
                        c = delta["content"]
                        content += c
                        yield {"type": "token", "content": c}

        yield {
            "type": "done",
            "content": content,
            "reasoning_content": reasoning_content
        }

    except httpx.TimeoutException:
        yield {"type": "error", "content": "API request timeout (120s), please retry"}
    except Exception as e:
        yield {"type": "error", "content": f"Request error: {str(e)}"}



# ======================================Main SSE Generator======================================


async def async_stream_response(messages: list, session_id: str = None, images: list = None, settings: dict = None, priority_file_ids: set = None):
    """
    Async generator yielding SSE events (reasoning_token, token, done, etc.).

    Supports thinking mode, file_qa and multi-source orchestration. When
    ``session_id`` is supplied and a knowledge base exists for that
    conversation, the file_qa path retrieves the most relevant passages (RAG)
    instead of injecting the whole document.

    ``images`` is a list of vision content blocks (e.g.
    ``{"type": "file", "file_id": "file-api-..."}``) attached to the current
    user message.
    """
    try:
        user_message = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                user_message = msg["content"]
                break
        
        lang = detect_language(user_message)

        # If no API key is configured yet, fail gracefully instead of a raw
        # 401: the user can keep exploring the UI and configure it via Settings.
        if user_message and not DEEPSEEK_API_KEY:
            if lang == 'zh':
                tip = "No DeepSeek API Key configured yet. Open Settings (⚙️) and add your API key first."
                yield {"type": "prefix", "content": "Assistant: "}
            else:
                tip = "No DeepSeek API Key configured yet. Open Settings (⚙️) and add your API key first."
                yield {"type": "prefix", "content": "Assistant: "}
            yield {"type": "token", "content": tip}
            yield {"type": "needs_setup", "content": tip}
            yield {"type": "done", "content": tip}
            return

        has_file_context = bool(session_id) and RAG_AVAILABLE and rag_service.has_index(session_id)

        # Legacy fallback: whole document appended as a system message.
        file_context_content = ""
        file_filename = ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get("type") == "file_context":
                has_file_context = True
                file_context_content = msg.get("content", "")
                if "Filename:" in file_context_content:
                    for line in file_context_content.split("\n"):
                        if line.startswith("Filename:"):
                            file_filename = line.split(":", 1)[-1].strip()
                            break
                break

        read_url_mode = bool(user_message) and IntentRouter.URL_PATTERN.search(user_message)
        use_local = False
        web_enabled = (not settings) or str(settings.get("web_search_enabled", "1")) != "0"
        use_web = _has_realtime_keyword(user_message) and web_enabled
        if read_url_mode:
            yield {"type": "intent_info", "content": "Page Reader"}
        elif user_message:
            intent = classify_intent_with_llm(user_message, has_file_context=has_file_context)
            use_local = (intent in ('file_qa', 'kb_browse')) and has_file_context
            use_web = ((intent == 'search') or use_web) and web_enabled
            label = f"Knowledge sources: {_plan_desc(use_local, use_web, 'en')}"
            yield {"type": "intent_info", "content": label}

        if not read_url_mode:
            current_date = datetime.datetime.now().strftime("%B %d, %Y")
            yield {"type": "reasoning_start", "content": ""}

            full_content = ""
            reasoning_content = ""
            api_failed = False

            # Gather local passages.
            retrieved = []
            overview = []
            local_text = ""
            if use_local and RAG_AVAILABLE and rag_service is not None and session_id:
                try:
                    browse_mode = (intent == 'kb_browse')
                    effective_priority = None if browse_mode else priority_file_ids
                    retrieved = rag_service.retrieve(user_message, session_id, priority_file_ids=effective_priority)
                    overview = rag_service.get_document_overview(session_id, priority_file_ids=effective_priority)
                except Exception as exc:  # noqa: BLE001
                    print(f"[RAG] local retrieval failed: {exc}")
                if retrieved:
                    local_text = _build_local_context(retrieved, overview)
                    if _is_summary_task(user_message):
                        sections_text = _build_sections_context(session_id)
                        if sections_text:
                            local_text = sections_text + "\n\n" + local_text
                    mem_ctx = _load_kb_memory_context()
                    if mem_ctx:
                        local_text = mem_ctx + "\n\n" + local_text
                elif file_context_content:
                    local_text = file_context_content

            # Gather web results.
            web_text = ""
            if use_web:
                try:
                    results = await asyncio.to_thread(search_bocha, user_message, 10)
                    if results:
                        web_text = _format_web_results(results, lang)
                except Exception as exc:  # noqa: BLE001
                    print(f"[RAG] web search failed: {exc}")

            if retrieved:
                yield {"type": "tool_info", "content": _truncate(_format_retrieved_context(retrieved), 3000)}
            if web_text:
                yield {"type": "tool_info", "content": _truncate(web_text, 3000)}

            if use_local and has_file_context and not local_text and not web_text:
                if lang == 'zh':
                    refusal = "No content relevant to your question was found in the uploaded document. Try rephrasing, or check whether the document covers this topic."
                    yield {"type": "prefix", "content": "Assistant: "}
                    yield {"type": "token", "content": refusal}
                    yield {"type": "done", "content": refusal}
                else:
                    refusal = "No content relevant to your question was found in the uploaded document. Try rephrasing, or check whether the document covers this topic."
                    yield {"type": "prefix", "content": "Assistant: "}
                    yield {"type": "token", "content": refusal}
                    yield {"type": "done", "content": refusal}
                return

            history = _build_chat_history(messages)
            system_message = _build_synthesis_prompt(lang, current_date, local_text, web_text)

            yield {"type": "usage_info", "content": _estimate_context_tokens(system_message, images)}

            async for event in call_deepseek_direct_stream(
                message=user_message,
                thinking_enabled=True,
                system_message=system_message,
                images=images,
                history=history,
            ):
                if event["type"] == "reasoning_token":
                    reasoning_content += event["content"]
                    yield event
                elif event["type"] == "token":
                    full_content += event["content"]
                    yield event
                elif event["type"] == "done":
                    full_content = event["content"]
                    reasoning_content = event.get("reasoning_content", reasoning_content)
                    break
                elif event["type"] == "error":
                    print(f"[fallback] Thinking mode failed: {event['content']}")
                    api_failed = True
                    break

            if api_failed:
                yield {"type": "token", "content": "(Thinking mode unavailable, using standard mode)\n"}
                result = await asyncio.get_event_loop().run_in_executor(
                    None, graph.invoke, {"messages": messages}
                )
                final_message = result["messages"][-1]
                if isinstance(final_message, AIMessage):
                    content = final_message.content
                    actual = content
                    for p in ["Assistant: ", "DeepSeek："]:
                        if content.startswith(p):
                            actual = content[len(p):]
                            if actual.startswith("\n"):
                                actual = actual[1:]
                            break
                    yield {"type": "prefix",
                           "content": "DeepSeek：" if lang == 'zh' else "Assistant: "}
                    for i in range(0, len(actual), 3):
                        yield {"type": "token", "content": actual[i:i+3]}
                        await asyncio.sleep(0.01)
                    yield {"type": "done", "content": actual}
                else:
                    yield {"type": "error", "content": "Fallback mode also failed"}
            else:
                yield {"type": "reasoning_done", "content": reasoning_content}
                yield {"type": "done", "content": full_content, "reasoning_content": reasoning_content}

        else:
            result = await asyncio.get_event_loop().run_in_executor(
                None, graph.invoke, {"messages": messages}
            )
            final_message = result["messages"][-1]

            tool_result_content = ""
            for msg in result["messages"]:
                if isinstance(msg, ToolMessage):
                    tool_result_content = msg.content
                    break

            if tool_result_content:
                if len(tool_result_content) > 3000:
                    tool_result_content = tool_result_content[:3000] + "\n\n...(truncated)"
                yield {"type": "tool_info", "content": tool_result_content}

            if isinstance(final_message, AIMessage):
                content = final_message.content

                prefix = ""
                actual_content = content
                for p in ["[Web Search]", "[Page Reader]", "Assistant: "]:
                    if content.startswith(p):
                        prefix = p
                        actual_content = content[len(p):]
                        if actual_content.startswith("\n"):
                            actual_content = actual_content[1:]
                        break

                if False:  # web search is now handled by the orchestration path
                    yield {"type": "reasoning_start", "content": ""}
                    
                    thinking_prompt = (
                        f"User question: {user_message}\n\n"
                        f"Tool results:\n{tool_result_content[:3000]}\n\n"
                        f"Based on the above information, provide a complete and accurate answer."
                    )

                    full_content = ""
                    reasoning_content = ""
                    api_failed = False

                    async for event in call_deepseek_direct_stream(
                        message=thinking_prompt,
                        thinking_enabled=True,
                        reasoning_effort="high"
                    ):
                        if event["type"] == "reasoning_token":
                            reasoning_content += event["content"]
                            yield event
                        elif event["type"] == "token":
                            full_content += event["content"]
                            yield event
                        elif event["type"] == "done":
                            full_content = event["content"]
                            reasoning_content = event.get("reasoning_content", reasoning_content)
                            break
                        elif event["type"] == "error":
                            api_failed = True
                            break

                    if api_failed:
                        yield {"type": "prefix", "content": prefix}
                        for i in range(0, len(actual_content), 3):
                            yield {"type": "token", "content": actual_content[i:i+3]}
                            await asyncio.sleep(0.01)
                        yield {"type": "done", "content": actual_content}
                    else:
                        yield {"type": "reasoning_done", "content": reasoning_content}
                        yield {"type": "prefix", "content": prefix}
                        yield {"type": "done", "content": full_content, "reasoning_content": reasoning_content}
                else:
                    yield {"type": "prefix", "content": prefix}
                    for i in range(0, len(actual_content), 3):
                        yield {"type": "token", "content": actual_content[i:i+3]}
                        await asyncio.sleep(0.01)
                    yield {"type": "done", "content": actual_content}
            else:
                yield {"type": "error", "content": "Unexpected model response"}

    except Exception as e:
        yield {"type": "error", "content": str(e)}



if __name__ == "__main__":
    print("=" * 50)
    print("AI Assistant - Dev Console")
    print("Type 'quit' or 'exit' to exit")
    print("=" * 50)

    messages = []
    
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ('quit', 'exit', 'q'):
            print("Goodbye!")
            break

        messages.append({"role": "user", "content": user_input})
        
        try:
            result = graph.invoke({"messages": messages})
            assistant_reply = result["messages"][-1].content
            
            print("-" * 40)
            
            messages.append({"role": "assistant", "content": assistant_reply})
            
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            break

import os
import tempfile
import concurrent.futures

# Documents with at least this many pages are extracted in parallel.
_PARALLEL_MIN_PAGES = 12
_PARALLEL_WORKERS = 4

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("[WARN] PyMuPDF not installed. Run: pip install PyMuPDF")

try:
    import pymupdf4llm
    HAS_PYMUPDF4LLM = True
except ImportError:
    HAS_PYMUPDF4LLM = False
    print("[WARN] PyMuPDF4LLM not installed. Run: pip install pymupdf4llm")


# ======================================================================
# Markdown extraction (primary path)
# ======================================================================

def extract_markdown_from_pdf(file_path: str, max_chars: int = None) -> str:
    """Extract a PDF on disk as Markdown.

    Args:
        file_path: path to the PDF file.
        max_chars: optional cap on the returned length; ``None`` means no cap.

    Returns:
        Markdown text, or a string beginning with ``Error`` on failure.
    """
    if not HAS_PYMUPDF:
        return "Error: PyMuPDF is not installed. Run: pip install PyMuPDF"

    try:
        document = fitz.open(file_path)
    except Exception as exc:
        return f"Error: could not open PDF - {exc}"

    try:
        return _markdown_from_document(document, max_chars)
    finally:
        document.close()


def extract_markdown_from_upload(file_content: bytes,
                                 filename: str = "document.pdf",
                                 max_chars: int = None) -> str:
    """Extract uploaded PDF bytes as Markdown without writing to disk.

    Args:
        file_content: raw PDF bytes.
        filename: used for logging only.
        max_chars: optional cap on the returned length; ``None`` means no cap.

    Returns:
        Markdown text, or a string beginning with ``Error`` on failure.
    """
    if not HAS_PYMUPDF:
        return "Error: PyMuPDF is not installed. Run: pip install PyMuPDF"

    try:
        document = fitz.open(stream=file_content, filetype="pdf")
    except Exception:
        # Some PDFs only open cleanly from a real file path.
        return _markdown_via_tempfile(file_content, filename, max_chars)

    try:
        return _markdown_from_document(document, max_chars)
    finally:
        document.close()


def _markdown_from_document(document, max_chars):
    """Convert an open PyMuPDF document to Markdown.

    ``max_chars`` is an optional cap; ``None`` means no limit. The plain-text
    fallbacks honour the same contract so a long document is never silently
    truncated (which used to hide tail content from the index and look like
    poor retrieval).
    """
    if not HAS_PYMUPDF4LLM:
        return _plain_text_from_document(document, max_chars)

    try:
        if len(document) >= _PARALLEL_MIN_PAGES:
            markdown = _markdown_parallel(document)
        else:
            markdown = pymupdf4llm.to_markdown(document)
    except Exception as exc:
        print(f"[WARN] PyMuPDF4LLM failed ({exc}); falling back to plain text")
        return _plain_text_from_document(document, max_chars)

    if max_chars and len(markdown) > max_chars:
        markdown = markdown[:max_chars] + (
            f"\n\n...(document too long, truncated to about {max_chars} characters)"
        )
    return markdown


def _markdown_parallel(document, workers=None):
    """Extract Markdown across multiple threads (each worker owns a sub-doc)."""
    workers = workers or _PARALLEL_WORKERS
    page_count = len(document)
    chunk = (page_count + workers - 1) // workers

    subs = []
    for start in range(0, page_count, chunk):
        end = min(start + chunk, page_count) - 1
        sub = fitz.open()
        sub.insert_pdf(document, from_page=start, to_page=end)
        subs.append(sub)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(pymupdf4llm.to_markdown, subs))
        return "\n\n".join(parts)
    finally:
        for sub in subs:
            sub.close()


def _markdown_via_tempfile(file_content, filename, max_chars):
    """Fallback for PDFs that PyMuPDF cannot open from a byte stream."""
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        handle.write(file_content)
        handle.close()
        return extract_markdown_from_pdf(handle.name, max_chars)
    except Exception as exc:
        return f"Error: PDF parsing failed - {exc}"
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


# ======================================================================
# Plain-text extraction (legacy / fallback path)
# ======================================================================

def extract_text_from_pdf(file_path: str, max_chars: int = 50000) -> str:
    """Extract a PDF on disk as plain text, capped at ``max_chars``."""
    if not HAS_PYMUPDF:
        return "Error: PyMuPDF is not installed. Run: pip install PyMuPDF"

    try:
        document = fitz.open(file_path)
    except Exception as exc:
        return f"Error: PDF parsing failed - {exc}"

    try:
        return _plain_text_from_document(document, max_chars)
    finally:
        document.close()


def extract_text_from_upload(file_content: bytes,
                             filename: str = "document.pdf",
                             max_chars: int = 50000) -> str:
    """Extract uploaded PDF bytes as plain text without writing to disk."""
    if not HAS_PYMUPDF:
        return "Error: PyMuPDF is not installed. Run: pip install PyMuPDF"

    try:
        document = fitz.open(stream=file_content, filetype="pdf")
    except Exception:
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            handle.write(file_content)
            handle.close()
            return extract_text_from_pdf(handle.name, max_chars)
        except Exception as exc:
            return f"Error: PDF parsing failed - {exc}"
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass

    try:
        return _plain_text_from_document(document, max_chars)
    finally:
        document.close()


def _plain_text_from_document(document, max_chars):
    """Concatenate page text, stopping once ``max_chars`` is reached.

    ``max_chars`` may be ``None`` for no limit; when a limit is hit the
    returned text ends with a truncation marker the caller can detect.
    """
    parts = []
    total = 0

    for page_number in range(len(document)):
        text = document[page_number].get_text()

        if max_chars is not None and total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                parts.append(text[:remaining])
            parts.append(
                f"\n\n...(document too long, truncated to about {max_chars} characters)"
            )
            break

        parts.append(text)
        total += len(text)

    return "\n".join(parts)

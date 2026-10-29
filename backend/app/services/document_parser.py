"""Bounded, in-memory parsing. No document is executed or retained as a raw file."""

import io
import unicodedata
import zipfile
from pathlib import PurePath

from docx import Document
from pypdf import PdfReader

from app.analysis_schemas import Source

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 100000


class DocumentError(ValueError):
    pass


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise DocumentError("Document contains unsupported control characters")
    text = text.strip()
    if not text or len(text) > MAX_TEXT_CHARS:
        raise DocumentError("Extracted text must contain 1–100000 characters")
    return text


def text_sources(text: str, location: str = "text") -> list[dict]:
    return [
        Source(id=f"S{i}", location=f"{location}, line {i}", text=line.strip()).model_dump()
        for i, line in enumerate(text.splitlines(), 1)
        if line.strip()
    ]


def parse_document(filename: str, content_type: str, content: bytes) -> tuple[str, list[dict]]:
    extension = PurePath(filename).suffix.lower()
    allowed = {
        ".txt": {"text/plain", "application/octet-stream"},
        ".pdf": {"application/pdf"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    }
    if extension not in allowed or content_type.split(";")[0] not in allowed[extension]:
        raise DocumentError("Only matching PDF, DOCX and UTF-8 TXT uploads are supported")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise DocumentError("Upload must contain 1 byte–5 MiB")
    try:
        if extension == ".txt":
            text = normalize(content.decode("utf-8-sig"))
            return text, text_sources(text, "TXT")
        if extension == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise DocumentError("Invalid PDF signature")
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or len(reader.pages) > 200:
                raise DocumentError("Encrypted PDFs or PDFs over 200 pages are unsupported")
            chunks, sources = [], []
            for page_number, page in enumerate(reader.pages, 1):
                # Reject very large decoded streams before invoking text extraction.
                stream = page.get_contents()
                if stream and len(stream.get_data()) > 10 * 1024 * 1024:
                    raise DocumentError("PDF page content exceeds parser limit")
                chunk = page.extract_text() or ""
                chunks.append(chunk)
                if sum(map(len, chunks)) > MAX_TEXT_CHARS:
                    raise DocumentError("PDF text exceeds 100000 characters")
                for line_number, line in enumerate(chunk.splitlines(), 1):
                    if line.strip():
                        sources.append(
                            Source(
                                id=f"S{len(sources) + 1}",
                                location=f"PDF page {page_number}, line {line_number}",
                                text=line.strip(),
                            ).model_dump()
                        )
            return normalize("\n".join(chunks)), sources
        if not content.startswith(b"PK"):
            raise DocumentError("Invalid DOCX signature")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 1000
                or sum(e.file_size for e in entries) > 20 * 1024 * 1024
                or "word/document.xml" not in archive.namelist()
            ):
                raise DocumentError("DOCX structure or expanded size is unsupported")
            if any(e.filename.endswith("vbaProject.bin") for e in entries):
                raise DocumentError("Macro content is not supported")
        document = Document(io.BytesIO(content))
        lines = []
        # Iterate XML body order so table/paragraph references remain stable.
        for block in document.iter_inner_content():
            if hasattr(block, "rows"):
                lines.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
            else:
                lines.append(block.text)
        text = normalize("\n".join(lines))
        return text, text_sources(text, "DOCX paragraph/table row")
    except DocumentError:
        raise
    except Exception:
        # Parser internals and document payloads must not reach API error responses.
        raise DocumentError("Malformed, unsupported or unreadable document") from None

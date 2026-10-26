"""Read training sources into chunks with a citation each (ADR-0004).

Files: PDF (pypdf), DOCX (stdlib zip/XML), TXT/MD. Links: the page plus same-site pages it links to (robots.txt
respected, 1 request/s, size and page caps). Only text is kept in memory while a job runs; nothing is stored.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from ..intent.knowledge import fold

FILE_TYPES = {".pdf", ".docx", ".txt", ".md"}
MAX_FILE_BYTES = 300 * 1024 * 1024
USER_AGENT = "GuiderTraining/0.1 (+desktop app; reads pages the developer pasted)"
MAX_PAGE_BYTES = 3 * 1024 * 1024

# A passage teaches an Office operation when it both tells the reader to act and names a piece of the UI
# (folded, no diacritics). 26/10/2026: the old single word list kept 99 of 102 chunks of a 226-page book.
ACTIONS = ["click", "select", "choose", "tap", "press", "drag", "type", "go to", "open the", "nhan", "chon", "bam",
           "nhap", "keo", "go ", "mo the", "vao the"]
UI = ["tab", "ribbon", "button", "menu", "dialog", "group", "gallery", "toolbar", "pane", "nut", "the ", "hop thoai",
      "nhom", "thanh cong cu", "bang chon"]


@dataclass
class Chunk:
    text: str
    where: str  # citation inside the source: "trang 12–14", a URL, "đoạn 3"


@dataclass
class Source:
    kind: str  # file | link | research
    name: str
    ref: str  # path or URL (shown to the developer, logged; never the text)
    sha: str
    chunks: list[Chunk] = field(default_factory=list)


def _split(text: str, size: int) -> list[str]:
    """Split on blank lines / headings, packing paragraphs up to `size` characters."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > size:  # a single huge paragraph
            out.append(p[:size])
            p = p[size:]
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def relevant(text: str) -> bool:
    """Cheap filter before the LLM: keep passages that look like Office how-to text."""
    t = f" {fold(text)} "
    acts = sum(t.count(f" {c}") for c in ACTIONS)
    ui = sum(t.count(f" {c}") for c in UI)
    return acts >= 2 and ui >= 1


def read_file(path: str | Path, chunk_chars: int) -> Source:
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in FILE_TYPES or not p.is_file():
        raise ValueError("Chỉ đọc được file PDF, DOCX, TXT hoặc MD có trên máy.")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File quá lớn (tối đa 300 MB).")
    raw = p.read_bytes()
    src = Source("file", p.name, str(p), hashlib.sha256(raw).hexdigest())
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        buf, first = "", 1
        for i, page in enumerate(reader.pages, start=1):
            try:
                t = page.extract_text() or ""
            except Exception:  # damaged page: skip, keep the rest of the book
                t = ""
            buf += "\n\n" + t
            if len(buf) >= chunk_chars or i == len(reader.pages):
                for part in _split(buf, chunk_chars):
                    src.chunks.append(Chunk(part, f"trang {first}–{i}" if first != i else f"trang {i}"))
                buf, first = "", i + 1
    else:
        if ext == ".docx":
            with zipfile.ZipFile(p) as z:
                root = ElementTree.fromstring(z.read("word/document.xml"))
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            text = "\n\n".join("".join(t.text or "" for t in para.iter(f"{ns}t")) for para in root.iter(f"{ns}p"))
        else:
            text = raw.decode("utf-8", errors="replace")
        for n, part in enumerate(_split(text, chunk_chars), start=1):
            src.chunks.append(Chunk(part, f"đoạn {n}"))
    return src


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "tr", "br", "div", "section"):
            self.parts.append("\n\n" if tag.startswith("h") or tag in ("p", "section") else "\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        t = "".join(self.parts)
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()


def _get(url: str, timeout: float = 20) -> tuple[str, str]:
    """Returns (final_url, html). Only http(s) and text/html."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if "html" not in (r.headers.get("Content-Type") or ""):
            raise ValueError("không phải trang HTML")
        data = r.read(MAX_PAGE_BYTES + 1)[:MAX_PAGE_BYTES]
        charset = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), data.decode(charset, errors="replace")


def fetch_url(url: str, chunk_chars: int, max_pages: int = 20, crawl: bool = True, cancel=None,
              on_page=None) -> Source:
    """The page and, when crawl, same-site pages under the same folder that it links to."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("Link phải bắt đầu bằng http:// hoặc https://")
    robots = urllib.robotparser.RobotFileParser(f"{u.scheme}://{u.netloc}/robots.txt")
    try:
        robots.read()
    except Exception:
        robots = None
    prefix = u.path.rsplit("/", 1)[0] + "/"
    queue, seen, pages = [url], set(), 0
    src = Source("link", u.netloc + u.path, url, "")
    digest = hashlib.sha256()
    while queue and pages < max_pages:
        if cancel is not None and cancel.is_set():
            break
        cur = urllib.parse.urldefrag(queue.pop(0))[0]
        if cur in seen:
            continue
        seen.add(cur)
        if robots is not None and not robots.can_fetch(USER_AGENT, cur):
            continue
        try:
            final, html = _get(cur)
        except Exception:
            continue
        pages += 1
        if on_page:
            on_page(pages, final)
        p = _Text()
        p.feed(html)
        text = p.text()
        digest.update(text.encode("utf-8", errors="ignore"))
        if pages == 1 and p.title.strip():
            src.name = p.title.strip()[:120]
        for part in _split(text, chunk_chars):
            src.chunks.append(Chunk(part, final))
        if crawl:
            for href in p.links:
                nxt = urllib.parse.urljoin(final, href)
                n = urllib.parse.urlparse(nxt)
                if n.netloc == u.netloc and n.path.startswith(prefix) and nxt not in seen:
                    queue.append(nxt)
        time.sleep(1.0)  # be gentle with the site
    if pages == 0:
        raise ValueError("Không đọc được trang nào từ link này (bị chặn, cần đăng nhập, hoặc không phải trang web).")
    src.sha = digest.hexdigest()
    return src

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
    all_relevant: bool = False  # spreadsheets and the formula catalogue: every chunk teaches something


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
    formulas = len(_FUNC.findall(text.upper()))  # formula-led books ("type =VLOOKUP(...)") teach too
    return (acts >= 2 and ui >= 1) or (formulas >= 2 and acts >= 1)


def read_file(path: str | Path, chunk_chars: int, data: bytes | None = None, name: str | None = None) -> Source:
    """`data`/`name`: an item read out of a .zip (never written to disk)."""
    p = Path(name or path)
    ext = p.suffix.lower()
    if ext in SHEET_TYPES:
        return read_workbook(path, chunk_chars, data=data, label=p.name)
    if ext not in FILE_TYPES or (data is None and not Path(path).is_file()):
        raise ValueError("Chỉ đọc được file PDF, DOCX, TXT, MD, XLSX hoặc thư mục/zip chứa chúng.")
    if data is None and Path(path).stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File quá lớn (tối đa 300 MB).")
    raw = data if data is not None else Path(path).read_bytes()
    src = Source("file", p.name, p.name, hashlib.sha256(raw).hexdigest())
    if ext == ".pdf":
        import io

        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
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
            import io
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
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


# ---- spreadsheets and archives (27/10/2026: a course's 1,770 practice workbooks) --------------------------
SHEET_TYPES = {".xlsx", ".xlsm"}
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_FUNC = re.compile(r"\b([A-Z][A-Z0-9\.]{1,20})\(")
MAX_CELLS_PER_SHEET = 4000


def _xlsx_cells(data: bytes):
    """Yield (sheet_name, ref, formula or None, shown text) from an .xlsx/.xlsm in memory — stdlib only."""
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{_NS}t")) for si in root.iter(f"{_NS}si")]
        wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
        names = [sh.get("name") for sh in wb.iter(f"{_NS}sheet")]
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        sheets.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        for k, path in enumerate(sheets):
            sname = names[k] if k < len(names) else path
            root = ElementTree.fromstring(z.read(path))
            for n, c in enumerate(root.iter(f"{_NS}c")):
                if n > MAX_CELLS_PER_SHEET:
                    break
                f = c.find(f"{_NS}f")
                v = c.find(f"{_NS}v")
                text = v.text if v is not None else ""
                if c.get("t") == "s" and text:
                    try:
                        text = shared[int(text)]
                    except (ValueError, IndexError):
                        pass
                yield sname, c.get("r"), (f.text if f is not None and f.text else None), text or ""


def read_workbook(path: str | Path, chunk_chars: int, data: bytes | None = None, label: str | None = None) -> Source:
    """A workbook as teaching text: per sheet, its labels and the formulas it uses (with the cell they sit in)."""
    p = Path(path)
    raw = data if data is not None else p.read_bytes()
    src = Source("file", label or p.name, label or p.name, hashlib.sha256(raw).hexdigest())
    lines: list[str] = []
    cur = None
    for sheet, ref, formula, text in _xlsx_cells(raw):
        if sheet != cur:
            lines.append(f"\n## Sheet {sheet}")
            cur = sheet
        if formula:
            lines.append(f"{ref}: ={formula}")
        elif text and not re.fullmatch(r"[-0-9.,E+ ]+", text) and len(text) < 80:
            lines.append(f"{ref}: {text}")
    src.all_relevant = True
    text = f"Workbook {src.name}\n" + "\n".join(lines)
    for n, part in enumerate(_split(text, chunk_chars), start=1):
        src.chunks.append(Chunk(part, f"{src.name}, phần {n}"))
    return src


def formula_catalog(workbooks: list[tuple[str, bytes]], chunk_chars: int, per_function: int = 6) -> Source:
    """Many workbooks → one compact catalogue: each Excel function, how often it is used, real examples with the
    labels around them. The model reads the catalogue (tens of calls), not every file (thousands)."""
    from collections import Counter, defaultdict
    counts: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    digest = hashlib.sha256()
    for name, data in workbooks:
        digest.update(hashlib.sha256(data).digest())
        labels: dict[tuple[str, str], list[str]] = defaultdict(list)  # (sheet, row) → labels on that row
        try:
            cells = list(_xlsx_cells(data))
        except Exception:
            continue
        for sheet, ref, formula, text in cells:
            if not formula and text and len(text) < 40 and not re.fullmatch(r"[-0-9.,E+ ]+", text):
                labels[(sheet, re.sub(r"[A-Z]+", "", ref))].append(text)
        per_file: Counter = Counter()
        for sheet, ref, formula, text in cells:
            if not formula:
                continue
            for fn in set(_FUNC.findall(formula.upper())):
                counts[fn] += 1
                if len(examples[fn]) < per_function and len(formula) < 160 and per_file[fn] < 2:
                    per_file[fn] += 1  # at most two examples per file: variety across the course
                    near = labels.get((sheet, re.sub(r"[A-Z]+", "", ref)), [])[:3]
                    examples[fn].append(f"={formula}   ({name}, {sheet}!{ref}{'; nhãn cùng dòng: ' + ', '.join(near) if near else ''})")
    src = Source("file", f"Danh mục hàm từ {len(workbooks)} file Excel", "formula-catalog", digest.hexdigest())
    blocks = [f"### {fn}: dùng {n} lần\n" + "\n".join(examples[fn]) for fn, n in counts.most_common()]
    text = "Danh mục hàm Excel lấy từ các file bài tập thật. Mỗi mục: tên hàm, số lần dùng, ví dụ công thức.\n\n" + \
           "\n\n".join(blocks)
    for n, part in enumerate(_split(text, chunk_chars), start=1):
        src.chunks.append(Chunk(part, f"danh mục hàm, phần {n}"))
    src.all_relevant = True  # every block teaches a function
    return src


def expand_inputs(path: str | Path) -> list[tuple[str, Path | None, bytes | None]]:
    """A file, a folder or a .zip → [(display name, path or None, bytes or None)] of readable items."""
    p = Path(path)
    out: list[tuple[str, Path | None, bytes | None]] = []
    ok = FILE_TYPES | SHEET_TYPES
    if p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.is_file() and f.suffix.lower() in ok | {".zip"}:
                out += expand_inputs(f) if f.suffix.lower() == ".zip" else [(f.name, f, None)]
    elif p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                name = info.filename
                suffix = Path(name).suffix.lower()
                if info.is_dir() or "/." in name or name.startswith(".") or suffix not in ok:
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    continue
                out.append((Path(name).name, None, z.read(info)))
    elif p.is_file():
        out.append((p.name, p, None))
    return out

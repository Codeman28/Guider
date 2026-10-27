"""One training run (ADR-0004): read source → think chunk by chunk → check names → demonstrate → remember.

Demonstrations need Office: each one takes the server's Office lock, so a tutorial the user asks for waits at
most for the card being demonstrated, then training waits for the tutorial.
"""
from __future__ import annotations

import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import structlog
from pydantic import BaseModel, Field

from ..llm.providers.base import LLMError
from .extract import SYSTEM, XOut, build_card
from .llm import TrainingLLM, search_web
from .memory import Memory
from .sources import SHEET_TYPES, Source, expand_inputs, fetch_url, formula_catalog, read_file, relevant

log = structlog.get_logger()


META = re.compile(r"(tôi sẽ|rút ra các|theo yêu cầu|đoạn văn tài liệu hướng dẫn)", re.IGNORECASE)


RESEARCH_SOURCES = 4  # pages read per research topic (free tier: 500 requests per model per day)
NOT_TRIED = "chưa chạy thử"  # read but not demonstrated yet (training phase 1)


class Cancelled(Exception):
    pass


class Topics(BaseModel):
    topics: list[str] = Field(description="5 chủ đề, mỗi chủ đề là một việc cụ thể trong Excel/Word/PowerPoint")


class Answer(BaseModel):
    answer: str = Field(description="Trả lời tiếng Việt, dẫn nguồn bằng [số]")
    used: list[int]


class TrainingJob:
    def __init__(self, kind: str, ref: str, out_root: Path, progress: Callable[[dict], None],
                 office_lock, cancel, memory: Memory | None = None, llm: TrainingLLM | None = None,
                 demonstrate: bool = True):
        self.kind, self.ref = kind, ref  # file | link | research
        self.out_root = out_root
        self.progress = progress
        self.office_lock = office_lock
        self.cancel = cancel
        self.stop_reason = ""  # what the InputGuard saw (di chuột, bấm chuột, gõ phím), shown to the developer
        self.memory = memory or Memory()
        self.llm = llm or TrainingLLM()
        self.demonstrate = demonstrate

    def _p(self, phase: str, message: str, done: int = 0, total: int = 0):
        self.progress({"phase": phase, "message": message, "done": done, "total": total})

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    # ---- sources ----------------------------------------------------------------------------
    def _sources(self) -> list[Source]:
        size, cap = self.llm.chunk_chars, self.llm.conf.max_pages
        if self.kind == "file":  # a file, a folder or a .zip (27/10/2026)
            self._p("read", "Đang mở file…")
            items = expand_inputs(self.ref)
            if not items:
                raise ValueError("Không có file PDF, DOCX, TXT, MD hay XLSX nào đọc được ở đây.")
            books = [(n, p, d) for n, p, d in items if Path(n).suffix.lower() not in SHEET_TYPES]
            sheets = [(n, p, d) for n, p, d in items if Path(n).suffix.lower() in SHEET_TYPES]
            out = []
            for k, (n, p, d) in enumerate(books, start=1):
                self._check()
                self._p("read", f"Đang đọc {n} ({k}/{len(books)})", k, len(books))
                try:
                    out.append(read_file(p or n, size, data=d, name=n))
                except Exception as e:
                    log.warning("training.read_failed", name=n, error=str(e)[:160])
            if len(sheets) > 20:  # a course's practice files: one catalogue of the functions they use
                self._p("read", f"Đang gom công thức từ {len(sheets)} file Excel…")
                out.append(formula_catalog([(n, d if d is not None else p.read_bytes()) for n, p, d in sheets], size))
            else:
                for n, p, d in sheets:
                    try:
                        out.append(read_file(p or n, size, data=d, name=n))
                    except Exception as e:
                        log.warning("training.read_failed", name=n, error=str(e)[:160])
            return out
        if self.kind == "link":
            return [fetch_url(self.ref, size, max_pages=cap, cancel=self.cancel,
                              on_page=lambda n, u: self._p("read", f"Đang đọc trang {n}: {u}", n, cap))]
        # research: a topic, or none → the AI picks common tasks the memory does not cover yet
        if not self.llm.gemini_key:
            raise ValueError("Tự research cần API key Gemini (tab Cài đặt).")
        topics = [self.ref] if self.ref.strip() else self._suggest_topics()
        out = []
        for ti, topic in enumerate(topics, start=1):
            self._check()
            self._p("research", f"Đang tìm nguồn cho: {topic}", ti, len(topics))
            for hit in self._search(topic):
                self._check()
                try:
                    s = fetch_url(hit["url"], size, max_pages=1, crawl=False, cancel=self.cancel)
                    s.kind, s.name = "research", f"{topic}: {hit['title']}"[:160]
                    out.append(s)
                except Exception as e:
                    log.info("training.research_skip", url=hit["url"], error=str(e))
        if not out:
            raise ValueError("Không tìm được nguồn đọc được cho chủ đề này.")
        return out

    def _search(self, topic: str) -> list[dict]:
        """Google Search through Gemini, rotating models when one's daily quota is spent; a failed topic is skipped."""
        import urllib.error
        for _, model in self.llm.providers:
            if model in self.llm.exhausted:
                continue
            try:
                return search_web(topic, self.llm.gemini_key, model, max_results=RESEARCH_SOURCES)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore") if e.code == 429 else ""
                if e.code == 429 and "PerDay" in body:
                    self.llm.exhausted.add(model)
                    continue
                log.warning("training.search_failed", topic=topic, model=model, error=f"HTTP {e.code}")
                return []
            except Exception as e:
                log.warning("training.search_failed", topic=topic, model=model, error=str(e)[:160])
                return []
        return []

    def _suggest_topics(self) -> list[str]:
        from ..intent.knowledge import KnowledgePack
        known = []
        for app in ("excel", "word", "powerpoint"):
            try:
                known += [f"{app}: {c.title}" for c in KnowledgePack(app).cards]
            except FileNotFoundError:
                pass
        self._p("research", "AI đang chọn chủ đề còn thiếu…")
        out = self.llm.complete("Bạn chọn việc Microsoft 365 mà học sinh, sinh viên Việt Nam hay cần nhưng trợ lý "
                                "chưa biết. Chỉ trả JSON.",
                                "Trợ lý đã biết các việc sau:\n" + "\n".join(known)
                                + "\n\nĐề xuất 5 việc phổ biến khác, làm được bằng ribbon, mỗi việc một câu ngắn.",
                                Topics, max_tokens=800)
        return [t for t in out.topics if t.strip()][:5]

    # ---- run --------------------------------------------------------------------------------
    def run(self) -> dict:
        t0 = time.monotonic()
        stats = {"kind": self.kind, "ref": self.ref, "model": self.llm.label, "sources": [], "chunks": 0,
                 "relevant": 0, "tasks_found": 0, "added": 0, "merged": 0, "pending": 0, "rejected": 0,
                 "notes_added": 0, "notes_merged": 0, "cancelled": False}
        try:
            if self.kind == "verify":  # phase 2: demonstrate the cards read earlier ("chưa chạy thử")
                stats["sources"].append(self._verify_pending(stats))
            else:
                for src in self._sources():
                    self._check()
                    stats["sources"].append(self._learn(src, stats))
        except Cancelled:
            stats["cancelled"] = True
            stats["stop_reason"] = self.stop_reason
        for app in ("excel", "word", "powerpoint"):  # tidy the waiting list: one card per distinct task
            try:
                stats.setdefault("compacted", {})[app] = self.memory.compact_pending(app)
            except Exception as e:
                log.warning("training.compact_failed", app=app, error=str(e)[:160])
        stats["seconds"] = round(time.monotonic() - t0)
        stats["llm_calls"] = self.llm.calls
        return stats

    def _learn(self, src: Source, stats: dict) -> dict:
        prev = self.memory.seen(src.sha)
        # files: name only (a full path would leak the developer's folders into the repo); links: the URL
        entry = {"kind": src.kind, "name": src.name, "ref": src.name if src.kind == "file" else src.ref, "sha": src.sha,
                 "date": time.strftime("%Y-%m-%d %H:%M"), "summary": "", "added": 0, "merged": 0,
                 "pending": 0, "notes": 0}
        if prev and prev.get("complete"):
            self._p("skip", f"Đã học nguồn này rồi ({prev['date']}), bỏ qua.")
            return {**prev, "skipped": True}
        chunks = list(src.chunks) if src.all_relevant else [c for c in src.chunks if relevant(c.text)]
        stats["chunks"] += len(src.chunks)
        stats["relevant"] += len(chunks)
        summaries, cards = [], []

        def think(ch):
            """One chunk → model outputs. Runs in worker threads; memory is written by the caller only."""
            self._check()
            if self.llm.cloud_down:
                return ch, []
            try:
                return ch, [self.llm.complete(SYSTEM, f"Nguồn: {src.name} — {ch.where}\n\n{ch.text}", XOut)]
            except LLMError as e:
                log.warning("training.chunk_failed", where=ch.where, error=str(e)[:200])
                return ch, []

        workers = self.llm.workers
        self._p("think", f"AI đang đọc {len(chunks)} đoạn ({workers} đoạn cùng lúc, model {self.llm.label})…",
                0, len(chunks))
        ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="think")
        futures = [ex.submit(think, ch) for ch in chunks]
        results, read = [], 0
        try:
            for done, fut in enumerate(as_completed(futures), start=1):
                ch, outs = fut.result()
                read += bool(outs)
                self._p("think", f"AI đã đọc {done}/{len(chunks)} đoạn ({ch.where})", done, len(chunks))
                results += [(ch, out) for out in outs]
                if self.llm.cloud_down:
                    break  # keep what was learned; say why below
        except Cancelled:
            ex.shutdown(wait=False, cancel_futures=True)
            raise
        ex.shutdown(wait=True, cancel_futures=True)
        if self.llm.cloud_down:
            stats["warning"] = (f"{self.llm.label} lỗi liên tục ({self.llm.cloud_down}). Đã dừng sau {read}/{len(chunks)} "
                                "đoạn. Phần đã học được giữ lại; đưa lại file này sau ít phút để học tiếp.")
        order = {id(c): k for k, c in enumerate(chunks)}
        for ch, out in sorted(results, key=lambda r: order[id(r[0])]):  # book order for summaries/citations
            if not META.search(out.summary):  # small models sometimes describe the task instead of the text
                summaries.append(out.summary)
            cite = f"{src.name}, {ch.where}"
            for n in out.notes:
                r = self.memory.add_note(n.app, n.topic, n.fact, cite)
                stats["notes_added" if r == "added" else "notes_merged"] += 1
                entry["notes"] += r == "added"
            for t in out.tasks:
                stats["tasks_found"] += 1
                card, reason = build_card(t, src.name, ch.where)
                if card is None:
                    stats["rejected"] += 1
                    log.info("training.rejected", title=t.title, reason=reason)
                    continue
                same = self.memory.find_same(card, t.app)
                if same:
                    self.memory.merge_keywords(t.app, same[0], same[1], card["keywords"] + [card["title"]])
                    stats["merged"] += 1
                    entry["merged"] += 1
                elif all(c[1]["id"] != card["id"] for c in cards):
                    cards.append((t.app, card))
        for i, (app, card) in enumerate(cards, start=1):
            self._check()
            self._p("demo", f"Guider đang làm mẫu thử: {card['title']}. Đừng chạm vào máy.", i, len(cards))
            ok, reason = self._demonstrate(app, card) if self.demonstrate else (False, NOT_TRIED)
            self._check()  # stopped mid-demonstration: neither keep nor blame the card
            if ok:
                self.memory.add_card(app, card)
                stats["added"] += 1
                entry["added"] += 1
            else:
                self.memory.add_pending(app, card, reason)
                stats["pending"] += 1
                entry["pending"] += 1
        if summaries:
            entry["summary"] = self._summarize(src.name, summaries)
        # complete only when every chunk was read: a source with failed chunks is read again next time
        entry["complete"] = not self.llm.cloud_down and read == len(chunks)
        self.memory.add_log(entry)
        return entry

    def _verify_pending(self, stats: dict) -> dict:
        """Demonstrate every pending card whose reason is 'chưa chạy thử' (read now, demonstrate when idle)."""
        todo = [(app, x["card"]) for app in ("excel", "word", "powerpoint")
                for x in self.memory.pending(app) if x["reason"] == NOT_TRIED]
        # typed formulas and shortcuts first: ~11 s each against ~25 s for ribbon cards, most value per minute
        todo.sort(key=lambda ac: not all(s.get("intent") in ("type_formula", "key_combo") for s in ac[1]["steps"]))
        entry = {"kind": "verify", "name": f"Làm mẫu thử {len(todo)} việc đang chờ", "ref": "pending", "sha": "",
                 "date": time.strftime("%Y-%m-%d %H:%M"), "summary": "", "added": 0, "merged": 0, "pending": 0,
                 "notes": 0}
        for i, (app, card) in enumerate(todo, start=1):
            self._check()
            self._p("demo", f"Guider đang làm mẫu thử: {card['title']}. Đừng chạm vào máy.", i, len(todo))
            ok, reason = self._demonstrate(app, card)
            self._check()
            if ok:
                self.memory.add_card(app, card)
                stats["added"] += 1
                entry["added"] += 1
            else:
                self.memory.add_pending(app, card, reason)
                stats["pending"] += 1
                entry["pending"] += 1
        return entry

    def _summarize(self, name: str, parts: list[str]) -> str:
        if len(parts) == 1:
            return parts[0]

        class S(BaseModel):
            summary: str

        try:
            return self.llm.complete("Tóm tắt 2–3 câu tiếng Việt. Chỉ trả JSON.",
                                     f"Các tóm tắt từng phần của '{name}':\n" + "\n".join(f"- {p}" for p in parts[:60]),
                                     S, max_tokens=600).summary
        except LLMError:
            return " ".join(parts[:3])

    def _demonstrate(self, app: str, card: dict) -> tuple[bool, str]:
        """Run the card in a sandbox, exactly as a tutorial would. Waits for a running tutorial to finish."""
        from ..intent.knowledge import Card
        from ..orchestrator.session import Session
        from ..sandbox.office import SandboxRefused
        while not self.office_lock.acquire(timeout=1.0):
            self._check()
        try:
            run_root = self.out_root / "_training_runs"
            run_root.mkdir(parents=True, exist_ok=True)
            plan = Card(card["id"], card["title"], card["keywords"], card, app).to_plan()
            from ..env.input_guard import InputGuard
            with InputGuard(self.cancel) as guard:  # the developer touching the machine stops training
                res = Session(plan, run_root, cancel_event=self.cancel).run()
            self.stop_reason = guard.reason or self.stop_reason
            if res.tutorial.status == "ok":
                return True, ""
            bad = next((s for s in res.trace.steps if not s.verified), None)
            why = f"bước '{bad.element_name}': {bad.error or 'không xác minh được'}" if bad else res.tutorial.status
            return False, why
        except SandboxRefused as e:
            return False, str(e)
        except Exception as e:
            return False, f"lỗi khi làm mẫu: {e}"[:300]
        finally:
            self.office_lock.release()
            shutil.rmtree(self.out_root / "_training_runs", ignore_errors=True)


def ask(question: str, memory: Memory | None = None, llm: TrainingLLM | None = None) -> dict:
    """'Hỏi kho kiến thức': answer from notes + learned cards, with numbered citations."""
    from rapidfuzz import fuzz

    from ..intent.knowledge import KnowledgePack, fold
    memory, llm = memory or Memory(), llm or TrainingLLM()
    q = fold(question)
    notes = sorted(memory.notes(), key=lambda n: -fuzz.token_set_ratio(q, fold(n["topic"] + " " + n["fact"])))[:20]
    cards = []
    for app in ("excel", "word", "powerpoint"):
        try:
            cards += [(app, c) for c in KnowledgePack(app).cards]
        except FileNotFoundError:
            pass
    cards = sorted(cards, key=lambda ac: -fuzz.token_set_ratio(q, fold(ac[1].title + " " + " ".join(ac[1].keywords))))[:8]
    items = [f"[{i}] ({n['app']}) {n['topic']}: {n['fact']} — nguồn: {n['sources'][0]}" for i, n in enumerate(notes, 1)]
    base = len(items)
    items += [f"[{base + i}] ({a}) Guider làm mẫu được: {c.summary()}" for i, (a, c) in enumerate(cards, 1)]
    out = llm.complete("Trả lời câu hỏi CHỈ dựa trên kho kiến thức được cho, dẫn nguồn bằng [số]. Không có trong kho "
                       "thì nói rõ là chưa học. Chỉ trả JSON.",
                       "Kho kiến thức:\n" + "\n".join(items) + f"\n\nCâu hỏi: {question}", Answer, max_tokens=1200)
    cites = []
    for k in out.used:
        if 1 <= k <= base:
            cites.append({"n": k, "text": notes[k - 1]["fact"], "source": notes[k - 1]["sources"][0]})
        elif base < k <= len(items):
            a, c = cards[k - base - 1]
            cites.append({"n": k, "text": c.title, "source": "thẻ " + c.id})
    return {"answer": out.answer, "citations": cites, "model": llm.label}

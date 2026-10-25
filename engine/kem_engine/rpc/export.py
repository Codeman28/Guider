"""tutorial.export (SPEC §9): Markdown + images, or one self-contained HTML file (images base64)."""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

from ..models import Tutorial


def load(dir_: Path) -> Tutorial:
    return Tutorial.model_validate_json((dir_ / "tutorial.json").read_text(encoding="utf-8"))


def to_markdown(t: Tutorial) -> str:
    out = [f"# {t.title}", "", f"_{t.env_label}_", "", t.intro, ""]
    for s in t.steps:
        out += [f"## {s.heading}", ""]
        if s.image:
            out += [f"![{s.heading}]({s.image})", ""]
        out += [s.body, ""]
        if s.result_image:
            out += [f"![Kết quả]({s.result_image})", ""]
        if s.tip:
            out += [f"> {s.tip}", ""]
    if t.example:
        out += ["## Ví dụ", "", t.example.text, ""]
        if t.example.image:
            out += [f"![Ví dụ]({t.example.image})", ""]
    out += [t.outro, ""]
    return "\n".join(out)


def _md_inline(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


def _img(dir_: Path, name: str | None, alt: str) -> str:
    if not name or not (dir_ / name).is_file():
        return ""
    data = base64.b64encode((dir_ / name).read_bytes()).decode()
    return f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{data}">'


def to_html(t: Tutorial, dir_: Path, accent: str = "#E5484D") -> str:
    parts = [f"<h1>{html.escape(t.title)}</h1>", f'<p class="env">{html.escape(t.env_label)}</p>',
             f"<p>{_md_inline(t.intro)}</p>"]
    for s in t.steps:
        parts.append(f"<section><h2>{_md_inline(s.heading)}</h2>{_img(dir_, s.image, s.heading)}"
                     f"<p>{_md_inline(s.body)}</p>{_img(dir_, s.result_image, 'Kết quả')}"
                     + (f'<p class="tip">{_md_inline(s.tip)}</p>' if s.tip else "") + "</section>")
    if t.example:
        parts.append(f'<section class="example"><h2>Ví dụ</h2><p>{_md_inline(t.example.text)}</p>'
                     f"{_img(dir_, t.example.image, 'Ví dụ')}</section>")
    parts.append(f"<p>{_md_inline(t.outro)}</p>")
    css = (f":root{{--accent:{accent}}}body{{font:16px/1.6 system-ui,sans-serif;max-width:860px;margin:2rem auto;"
           "padding:0 16px;color:#1f1d1a;background:#fbfaf7}}h2{{margin-top:2rem}}img{{max-width:100%;"
           "border-radius:6px}}.env{{color:#6b665e;font-size:14px}}.tip{{border-left:3px solid var(--accent);"
           "padding-left:12px}}strong{{color:var(--accent)}}")
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(t.title)}</title>'
            f"<style>{css}</style></head><body>{''.join(parts)}</body></html>")


def export(dir_: Path, fmt: str) -> Path:
    t = load(dir_)
    if fmt == "md":
        p = dir_ / "tutorial.md"
        p.write_text(to_markdown(t), encoding="utf-8")
    elif fmt == "html":
        p = dir_ / "tutorial.html"
        p.write_text(to_html(t, dir_), encoding="utf-8")
    else:
        raise ValueError("định dạng chưa hỗ trợ: dùng md hoặc html (PDF: Phase 3, in từ app)")
    manifest = dir_ / "manifest.json"
    if manifest.exists():  # exports are files of this session — keep the manifest complete (SPEC §8)
        m = json.loads(manifest.read_text(encoding="utf-8"))
        if p.name not in m.get("files", []):
            m.setdefault("files", []).append(p.name)
            manifest.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return p

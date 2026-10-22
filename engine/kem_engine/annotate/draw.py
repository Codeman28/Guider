"""Annotator (SPEC §6.7): rounded highlight box, short curved arrow, step badge. Drawn at 2× then
downsampled. All sizes are logical px from design/tokens.json, scaled by the window DPI."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..models import Rect

TOKENS_PATH = Path(__file__).resolve().parents[3] / "design" / "tokens.json"
SS = 2  # supersampling factor


@dataclass
class Style:
    accent: tuple[int, int, int]
    on_accent: tuple[int, int, int]
    radius: float
    stroke: float
    badge_r: float
    arrow_len: float
    shadow_alpha: float
    spotlight_dim: float

    @classmethod
    def load(cls, scale: float = 1.0, path: Path = TOKENS_PATH) -> "Style":
        t = json.loads(path.read_text(encoding="utf-8"))
        a = t["annotation"]
        return cls(_hex(t["color"]["accent"]), _hex(t["color"]["on_accent"]), a["radius_px"] * scale,
                   a["stroke_px"] * scale, a["badge_radius_px"] * scale, a["arrow_length_px"] * scale,
                   a["shadow_alpha"], t["color"]["spotlight_dim"])


def _hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _arrow_start(img_w: int, img_h: int, box: Rect, length: float) -> tuple[float, float, float, float]:
    """Pick the first direction whose tail lands inside the image; return (sx, sy, ex, ey)."""
    cx, cy = (box.left + box.right) / 2, (box.top + box.bottom) / 2
    for deg in (135, 45, 180, 0, 90, 225, 315, 270):  # screen coords: y grows downward
        rad = math.radians(deg)
        dx, dy = math.cos(rad), math.sin(rad)
        # end point on the box edge in that direction (+ small gap)
        hw, hh = box.width / 2 + 6, box.height / 2 + 6
        t = min(hw / abs(dx) if abs(dx) > 1e-6 else 1e9, hh / abs(dy) if abs(dy) > 1e-6 else 1e9)
        ex, ey = cx + dx * t, cy + dy * t
        sx, sy = ex + dx * length, ey + dy * length
        if 4 <= sx <= img_w - 4 and 4 <= sy <= img_h - 4:
            return sx, sy, ex, ey
    return cx, min(img_h - 4, box.bottom + length), cx, box.bottom + 6


def _curve(sx, sy, ex, ey, bend=0.25, n=24):
    mx, my = (sx + ex) / 2, (sy + ey) / 2
    nx, ny = -(ey - sy), ex - sx  # perpendicular
    cx, cy = mx + nx * bend, my + ny * bend
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append(((1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t * t * ex,
                    (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t * t * ey))
    return pts


def annotate(img: Image.Image, box: Rect, step_no: int, style: Style, spotlight: bool = False) -> Image.Image:
    """box is in image pixel coordinates."""
    W, H = img.size
    big = img.convert("RGB").resize((W * SS, H * SS), Image.LANCZOS)
    b = Rect(left=box.left * SS, top=box.top * SS, right=box.right * SS, bottom=box.bottom * SS)
    pad = style.stroke * SS
    frame = (b.left - pad, b.top - pad, b.right + pad, b.bottom + pad)

    if spotlight:
        mask = Image.new("L", big.size, int(255 * style.spotlight_dim))
        ImageDraw.Draw(mask).rounded_rectangle(frame, radius=style.radius * SS, fill=0)
        big = Image.composite(Image.new("RGB", big.size, (0, 0, 0)), big, mask)

    # soft shadow under the frame
    shadow = Image.new("L", big.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle(frame, radius=style.radius * SS,
                                             outline=int(255 * style.shadow_alpha), width=int(pad * 2))
    shadow = shadow.filter(ImageFilter.GaussianBlur(4 * SS))
    big = Image.composite(Image.new("RGB", big.size, (0, 0, 0)), big, shadow)

    d = ImageDraw.Draw(big)
    d.rounded_rectangle(frame, radius=style.radius * SS, outline=style.accent, width=int(style.stroke * SS))

    sx, sy, ex, ey = _arrow_start(W * SS, H * SS, Rect(left=int(frame[0]), top=int(frame[1]),
                                                       right=int(frame[2]), bottom=int(frame[3])),
                                  style.arrow_len * SS)
    pts = _curve(sx, sy, ex, ey)
    d.line(pts, fill=style.accent, width=int(style.stroke * SS), joint="curve")
    (px, py), (qx, qy) = pts[-3], pts[-1]
    ang = math.atan2(qy - py, qx - px)
    head = style.stroke * SS * 3.2
    left = (qx - head * math.cos(ang - 0.5), qy - head * math.sin(ang - 0.5))
    right = (qx - head * math.cos(ang + 0.5), qy - head * math.sin(ang + 0.5))
    d.polygon([(qx, qy), left, right], fill=style.accent)

    r = style.badge_r * SS
    bx, by = frame[0], frame[1]
    bx, by = max(r + 2, bx), max(r + 2, by)
    d.ellipse((bx - r, by - r, bx + r, by + r), fill=style.accent)
    font = ImageFont.load_default(size=int(r * 1.15))
    d.text((bx, by), str(step_no), fill=style.on_accent, font=font, anchor="mm")

    return big.resize((W, H), Image.LANCZOS)


def smart_crop(img: Image.Image, box: Rect, keep_top: int, min_w: int, margin: int):
    """Crop around a small target but keep the ribbon (rows 0..keep_top). Returns (image, (dx, dy))."""
    W, H = img.size
    if box.width * box.height > W * H / 8:
        return img, (0, 0)
    cw = min(W, max(min_w, box.width + 2 * margin))
    x0 = int(min(max(0, (box.left + box.right) / 2 - cw / 2), W - cw))
    y1 = int(min(H, max(keep_top, box.bottom + margin)))
    return img.crop((x0, 0, x0 + cw, y1)), (x0, 0)

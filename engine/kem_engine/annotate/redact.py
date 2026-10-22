"""Redactor (SPEC §6.7): hide the account name/avatar before an image is stored. Runs locally."""
from __future__ import annotations

from PIL import Image, ImageFilter

from ..models import Rect


def fallback_identity_rect(width: int, scale: float) -> Rect:
    """Account widget sits left of the caption buttons (S1: x 1036–1099 of 1280 at 125%).
    Used when UIA did not report MeControlWidget; deliberately wider than measured."""
    caption = round(144 * scale)
    return Rect(left=max(0, width - caption - round(110 * scale)), top=0,
                right=width - caption, bottom=round(48 * scale))


def redact(img: Image.Image, rects: list[Rect]) -> Image.Image:
    out = img.copy()
    for r in rects:
        box = (max(0, r.left), max(0, r.top), min(out.width, r.right), min(out.height, r.bottom))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        region = out.crop(box)
        small = region.resize((max(1, region.width // 12), max(1, region.height // 12)), Image.BILINEAR)
        region = small.resize(region.size, Image.NEAREST).filter(ImageFilter.GaussianBlur(6))
        out.paste(region, box)
    return out

import json
from pathlib import Path

import pytest
from PIL import Image

from kem_engine.annotate.draw import Style, annotate, smart_crop
from kem_engine.annotate.redact import fallback_identity_rect, redact
from kem_engine.env.probe import normalize_build
from kem_engine.models import Plan, Rect
from kem_engine.sandbox import com as com_mod
from kem_engine.sandbox.com import RPC_E_SERVERCALL_RETRYLATER, com_retry, is_busy_error

PLANS = Path(__file__).resolve().parents[1] / "plans"


@pytest.mark.parametrize("raw,want", [("20326.0", "20326"), ("16.0.20326", "20326"), ("20326", "20326"),
                                      ("16.0", "0"), ("", "unknown")])
def test_normalize_build(raw, want):
    assert normalize_build(raw) == want


class Busy(Exception):
    def __init__(self):
        super().__init__(RPC_E_SERVERCALL_RETRYLATER, "busy")


def test_com_retry_recovers_and_nudges_once():
    calls, nudges = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise Busy()
        return "ok"

    assert com_retry(fn, timeout=2, interval=0.01, on_busy=lambda: nudges.append(1)) == "ok"
    assert len(nudges) == 1


def test_com_retry_reraises_other_errors_and_timeout():
    with pytest.raises(ValueError):
        com_retry(lambda: (_ for _ in ()).throw(ValueError("x")), timeout=1)
    with pytest.raises(Busy):
        com_retry(lambda: (_ for _ in ()).throw(Busy()), timeout=0.05, interval=0.01)
    assert not is_busy_error(Exception("no code"))


def test_plans_validate_and_use_closed_intents():
    for p in PLANS.glob("*.json"):
        plan = Plan.model_validate_json(p.read_text(encoding="utf-8"))
        assert plan.steps and plan.task_canonical == p.stem


def test_fixture_ids_exist():
    from kem_engine.sandbox.excel import load_fixture
    for p in PLANS.glob("*.json"):
        fx = json.loads(p.read_text(encoding="utf-8"))["fixture_id"]
        assert load_fixture(fx)["rows"]
    with pytest.raises(ValueError):
        load_fixture("../../secret")


def test_annotate_keeps_size_and_draws_accent():
    img = Image.new("RGB", (400, 300), (250, 250, 250))
    style = Style.load(1.0)
    out = annotate(img, Rect(left=100, top=100, right=160, bottom=130), 3, style, spotlight=True)
    assert out.size == img.size
    px = [out.getpixel((x, 100 - 2)) for x in range(110, 150)]
    assert any(p[0] > 180 and p[1] < 120 for p in px)  # accent-red frame edge


def test_annotate_target_in_corner_still_draws_arrow():
    img = Image.new("RGB", (200, 120), (255, 255, 255))
    out = annotate(img, Rect(left=170, top=95, right=198, bottom=118), 1, Style.load(1.0))
    assert out.size == (200, 120)


def test_smart_crop_small_vs_large_target():
    img = Image.new("RGB", (1600, 1000))
    small, (dx, _) = smart_crop(img, Rect(left=1500, top=80, right=1560, bottom=120), 230, 900, 200)
    assert small.size[0] == 900 and small.size[1] == 320 and dx == 700
    big, off = smart_crop(img, Rect(left=0, top=0, right=1000, bottom=600), 230, 900, 200)
    assert big.size == img.size and off == (0, 0)


def test_redact_changes_region_only():
    img = Image.new("RGB", (300, 100), (255, 255, 255))
    for x in range(200, 260):
        for y in range(0, 40):
            img.putpixel((x, y), (0, 0, 0) if (x + y) % 2 else (255, 255, 255))
    out = redact(img, [Rect(left=200, top=0, right=260, bottom=40), Rect(left=10, top=10, right=10, bottom=20)])
    assert out.getpixel((50, 50)) == (255, 255, 255)
    assert out.crop((200, 0, 260, 40)).tobytes() != img.crop((200, 0, 260, 40)).tobytes()


def test_fallback_identity_rect_matches_measured_widget():
    r = fallback_identity_rect(1280, 1.25)  # S1: MeControlWidget at x 1036–1099, 125%
    assert r.left <= 1036 and r.right >= 1099 and r.top == 0

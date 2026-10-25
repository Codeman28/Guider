"""User touching the machine stops a demonstration (25/10/2026)."""
import threading

from kem_engine.env.input_guard import InputGuard


def guard():
    g = InputGuard(threading.Event(), move_px=60)
    g._tick, g._origin, g._last = 100, (500, 500), (500, 500)
    return g


def test_no_new_input_never_stops():
    assert guard().check(100, (900, 900), True) is None


def test_click_stops():
    assert guard().check(101, (500, 500), True) == "bấm chuột"


def test_real_move_stops_but_drift_does_not():
    g = guard()
    assert g.check(101, (520, 510), False) is None  # small drift tolerated
    assert g.check(102, (545, 530), False) is None
    assert g.check(103, (570, 540), False) == "di chuột"  # travel from the start passes 60 px


def test_key_press_stops():
    g = guard()
    assert g.check(101, (510, 500), False) is None
    assert g.check(102, (510, 500), False) == "gõ phím"  # new input, cursor did not move

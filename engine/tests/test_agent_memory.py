"""What the agent keeps between runs (ADR-0008): lessons and the practice queue."""
from __future__ import annotations

import pytest

from kem_engine.agent import memory


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_lessons_for_a_similar_goal_come_first_and_are_not_repeated():
    memory.add_lessons("word", "Đổi màu tiêu đề thành đỏ", ["Màu chữ: bấm Font Color rồi chọn Red"], ok=False)
    memory.add_lessons("word", "Thêm số trang", ["Số trang ở Insert > Page Number"], ok=True)
    memory.add_lessons("word", "Đổi màu tiêu đề thành đỏ", ["Màu chữ: bấm Font Color rồi chọn Red"], ok=False)
    got = memory.lessons_for("word", "đổi màu tiêu đề sang xanh")
    assert got[0] == "Màu chữ: bấm Font Color rồi chọn Red" and len(got) == 2
    assert memory.lessons_for("excel", "bất kỳ") == []


def test_reflect_falls_back_to_what_failed(monkeypatch):
    import kem_engine.vision.exercise as ex
    monkeypatch.setattr(ex, "_gemini", lambda *a, **k: None)
    got = memory.reflect("goal", [{"what": "bấm Font Color", "result": "không có control này trên màn hình"},
                                  {"what": "chọn p1", "result": "đã làm"}], "chưa đạt", False)
    assert got == ["'bấm Font Color' không dùng được (không có control này trên màn hình)"]


def test_practice_queue_counts_tries_and_drops_solved_goals():
    memory.queue_goal("excel", "Vẽ biểu đồ tròn", "chưa đạt")
    memory.queue_goal("word", "Chèn mục lục", "chưa đạt")
    memory.mark("excel", "Vẽ biểu đồ tròn", False)
    assert [g["goal"] for g in memory.pending()] == ["Chèn mục lục", "Vẽ biểu đồ tròn"]  # least tried first
    memory.mark("word", "Chèn mục lục", True)
    assert [g["goal"] for g in memory.pending()] == ["Vẽ biểu đồ tròn"]
    for _ in range(memory.MAX_TRIES):
        memory.mark("excel", "Vẽ biểu đồ tròn", False)
    assert memory.pending() == []  # stops retrying on its own; still listed for the user
    assert len(memory.queue()) == 2

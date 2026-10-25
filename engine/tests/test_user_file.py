"""ADR-0003 user-file mode: the original is only ever copied; refs adapt to the real document."""
import os
import stat

import pytest

from kem_engine.sandbox import office, word


def test_copy_is_private_and_writable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    src = tmp_path / "Báo cáo.docx"
    src.write_bytes(b"original")
    os.chmod(src, stat.S_IREAD)  # read-only original
    work, copy = office.copy_user_file(src)
    assert copy.parent == work and work.parent == office.work_root()
    copy.write_bytes(b"changed")  # the copy is writable
    assert src.read_bytes() == b"original"
    os.chmod(src, stat.S_IWRITE)


@pytest.mark.parametrize("name", ["a.exe", "a.txt", "a.pdf"])
def test_rejects_other_file_types(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        office.copy_user_file(f)


def test_app_for_file():
    assert office.app_for_file(r"C:\x\Sổ tay.XLSX") == "excel"
    assert office.app_for_file("deck.pptx") == "powerpoint"
    assert office.app_for_file("notes.txt") is None


class _Doc:
    class Paragraphs:
        Count = 3


def test_word_refs_clamp_to_document():
    assert word._map_ref(_Doc, "p2") == "p2"
    assert word._map_ref(_Doc, "p6") == "p3"
    assert word._map_ref(_Doc, "p3-p5") == "p3-p3"
    assert word._map_ref(_Doc, "all") == "all"

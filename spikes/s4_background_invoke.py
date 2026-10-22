"""S4: Do UIA patterns work on the Excel ribbon while the sandbox window is NOT foreground?

An occluder window we own holds the foreground. Each action is verified via UIA/COM, and we
record whether Excel stole the foreground. Keyboard intents (type_text, key_combo) go to the
focused window by definition (SendInput) — not exercised here so nothing is typed elsewhere.
"""
import time

from _common import (close_occluder, close_sandbox, force_foreground, foreground, launch_occluder,
                     open_sandbox, save_json, set_dpi_awareness, window_rect)

set_dpi_awareness()
from pywinauto import Desktop  # noqa: E402


def find(win, names, control_type):
    for e in win.descendants(control_type=control_type):
        if e.element_info.name in names:
            return e
    return None


def main():
    out = {}
    sb = open_sandbox("excel")
    proc = occ = None
    try:
        ws = sb.app.ActiveSheet
        ws.Range("A1").Value = "Kèm"
        ws.Range("A1").Select()
        win = Desktop(backend="uia").window(handle=sb.hwnd).wrapper_object()
        l, t, r, b = window_rect(sb.hwnd)
        proc, occ = launch_occluder((l + 200, t + 300, l + 700, t + 600))
        time.sleep(0.8)
        out["occluder_is_foreground"] = foreground() == occ

        def com_retry(fn, tries=20):
            # RPC_E_SERVERCALL_RETRYLATER while Excel is busy / in cell-edit mode
            for i in range(tries):
                try:
                    return fn()
                except Exception as e:
                    if "busy" not in str(e) or i == tries - 1:
                        raise
                    time.sleep(0.25)

        def record(label, fn, check):
            force_foreground(occ)  # measure each action independently
            res = {"foreground_before": "occluder" if foreground() == occ else
                   "sandbox" if foreground() == sb.hwnd else foreground()}
            try:
                fn()
                time.sleep(0.8)
                res["ok"] = bool(com_retry(check))
            except Exception as e:
                res["ok"] = False
                res["error"] = repr(e)[:200]
            res["foreground_after"] = ("sandbox" if foreground() == sb.hwnd else
                                       "occluder" if foreground() == occ else foreground())
            out[label] = res

        # select_ribbon_tab via SelectionItem
        data_tab = find(win, ("Data", "Dữ liệu"), "TabItem")
        record("select_ribbon_tab(SelectionItem)", lambda: data_tab.select(),
               lambda: data_tab.is_selected())

        home_tab = find(win, ("Home", "Trang đầu"), "TabItem")
        home_tab.select()
        time.sleep(0.6)

        # toggle via TogglePattern (Bold)
        bold = find(win, ("Bold", "Đậm"), "Button") or find(win, ("Bold", "Đậm"), "CheckBox")
        record("toggle(TogglePattern Bold)", lambda: bold.toggle(),
               lambda: ws.Range("A1").Font.Bold is True or ws.Range("A1").Font.Bold == -1)

        # invoke via InvokePattern (Increase Font Size)
        size0 = float(com_retry(lambda: ws.Range("A1").Font.Size))
        inc = find(win, ("Increase Font Size", "Tăng Cỡ Phông"), "Button")
        record("invoke(InvokePattern Increase Font Size)", lambda: inc.invoke(),
               lambda: float(ws.Range("A1").Font.Size) > size0)

        # expand via ExpandCollapse (Insert > collapsed Tables group)
        ins = find(win, ("Insert", "Chèn"), "TabItem")
        ins.select()
        time.sleep(0.6)
        tables = find(win, ("Tables", "Bảng"), "MenuItem")
        record("expand(ExpandCollapse Tables)", lambda: tables.expand(),
               lambda: tables.get_expand_state() == 1)
        try:
            tables.collapse()
        except Exception:
            pass

        # set_value via ValuePattern on the Name Box (no Enter)
        namebox = find(win, ("Name Box", "Hộp Tên"), "Edit") or find(win, ("Name Box",), "ComboBox")
        record("set_value(ValuePattern Name Box)",
               lambda: namebox.iface_value.SetValue("C5"),
               lambda: "C5" in (namebox.iface_value.CurrentValue or ""))
        out["name_box_moved_selection"] = com_retry(lambda: str(sb.app.Selection.Address)) == "$C$5"
        out["a1_value_after"] = com_retry(lambda: ws.Range("A1").Value)
        return out
    finally:
        if proc:
            close_occluder(proc, occ)
        close_sandbox(sb)


if __name__ == "__main__":
    r = main()
    save_json("s4_background_invoke", r)
    for k, v in r.items():
        print(k, v)

"""S3: Does PrintWindow + PW_RENDERFULLCONTENT capture Excel correctly while partly covered?
What about popups/menus (separate HWNDs) — can we composite them at the right place?

Also S5 (current DPI only): do UIA rects line up with the captured pixels within ±2 px?
"""
import time

from _common import (OUT, close_occluder, close_sandbox, class_name, dpi_for_window,
                     force_foreground, img_stats, launch_occluder, mean_abs_diff,
                     open_sandbox, owner_of, print_window, save_json, screen_grab,
                     set_dpi_awareness, top_level_windows, window_rect)

dpi_mode = set_dpi_awareness()
from pywinauto import Desktop  # noqa: E402


def find(win, names, control_type):
    for e in win.descendants(control_type=control_type):
        if e.element_info.name in names:
            return e
    return None


def best_shift(cap, origin, rect, search=4):
    """Compare UIA rect region in PrintWindow image vs the same rect on screen; find best offset."""
    l, t, r, b = rect
    ref = screen_grab((l, t, r, b))
    best = None
    for dx in range(-search, search + 1):
        for dy in range(-search, search + 1):
            box = (l - origin[0] + dx, t - origin[1] + dy, r - origin[0] + dx, b - origin[1] + dy)
            d = mean_abs_diff(cap.crop(box), ref)
            if best is None or d < best[0]:
                best = (d, dx, dy)
    return {"diff": best[0], "dx": best[1], "dy": best[2]}


def main():
    out = {"dpi_awareness": dpi_mode}
    sb = open_sandbox("excel")
    proc = occ = None
    try:
        sb.app.ActiveSheet.Range("A1:D3").Value = (("Tháng", "Doanh số", "Chi phí", "Lãi"),
                                                   (1, 100, 60, 40), (2, 120, 70, 50))
        force_foreground(sb.hwnd)
        time.sleep(0.5)
        out["window_dpi"] = dpi_for_window(sb.hwnd)
        out["scale_pct"] = round(out["window_dpi"] / 96 * 100)

        # 1) Plain capture, unobscured
        clean, ok, wr = print_window(sb.hwnd)
        clean.save(OUT / "s3_clean.png")
        screen_ref = screen_grab(wr)
        out["clean"] = {"ok": ok, "size": clean.size, **img_stats(clean),
                        "diff_vs_screen": mean_abs_diff(clean, screen_ref)}
        noflag, ok0, _ = print_window(sb.hwnd, flags=0)
        noflag.save(OUT / "s3_noflag.png")
        out["no_flag"] = {"ok": ok0, **img_stats(noflag), "diff_vs_clean": mean_abs_diff(noflag, clean)}

        # 2) Partly covered by another window
        l, t, r, b = wr
        proc, occ = launch_occluder((l + (r - l) // 3, t + (b - t) // 4, r - 100, b - 100))
        time.sleep(0.8)
        covered, ok2, _ = print_window(sb.hwnd)
        covered.save(OUT / "s3_covered.png")
        out["covered"] = {"ok": ok2, **img_stats(covered),
                          "diff_vs_clean": mean_abs_diff(covered, clean),
                          "occluder_found": bool(occ)}
        close_occluder(proc, occ)
        proc = occ = None
        force_foreground(sb.hwnd)
        time.sleep(0.5)

        # 3) Popup: open collapsed "Tables" group menu in Insert tab
        win = Desktop(backend="uia").window(handle=sb.hwnd).wrapper_object()
        find(win, ("Insert", "Chèn"), "TabItem").select()
        time.sleep(0.6)
        cap_tab, _, _ = print_window(sb.hwnd)
        btn = find(win, ("Recommended Charts",), "Button")
        tab = find(win, ("Insert", "Chèn"), "TabItem")
        s5 = {}
        for label, el in (("insert_tab", tab), ("recommended_charts", btn)):
            rr = el.element_info.rectangle
            s5[label] = {"rect": [rr.left, rr.top, rr.right, rr.bottom],
                         **best_shift(cap_tab, wr, (rr.left, rr.top, rr.right, rr.bottom))}
        out["s5_alignment"] = s5

        before = set(top_level_windows(sb.pid))
        tables = find(win, ("Tables", "Bảng"), "MenuItem")
        tables.expand()
        time.sleep(1.0)
        popups = [h for h in top_level_windows(sb.pid) if h not in before]
        out["popups"] = [{"hwnd": h, "class": class_name(h), "rect": window_rect(h),
                          "owner": owner_of(h)} for h in popups]
        base, _, _ = print_window(sb.hwnd)
        composite = base.copy()
        for h in popups:
            if class_name(h).startswith("MSO_BORDEREFFECT"):
                continue
            img, okp, pr = print_window(h)
            img.save(OUT / f"s3_popup_{h}.png")
            composite.paste(img, (pr[0] - wr[0], pr[1] - wr[1]))
        composite.save(OUT / "s3_composite.png")
        screen_now = screen_grab(wr)
        screen_now.save(OUT / "s3_screen_with_popup.png")
        out["composite_diff_vs_screen"] = mean_abs_diff(composite, screen_now)
        out["base_without_popup_diff_vs_screen"] = mean_abs_diff(base, screen_now)
        try:
            tables.collapse()
        except Exception:
            win.type_keys("{ESC}")
        return out
    finally:
        if proc:
            close_occluder(proc, occ)
        close_sandbox(sb)


if __name__ == "__main__":
    r = main()
    save_json("s3_capture", r)
    print(r)

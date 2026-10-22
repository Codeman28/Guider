"""S6: Can we read the Office UI language over COM?

MsoAppLanguageID: msoLanguageIDInstall = 1, msoLanguageIDUI = 2, msoLanguageIDHelp = 3,
msoLanguageIDExeMode = 4. TODO(verify): https://learn.microsoft.com/office/vba/api/office.msoapplanguageid
"""
from _common import close_sandbox, open_sandbox, save_json, set_dpi_awareness

set_dpi_awareness()

LCID = {1033: "en-US", 1066: "vi-VN"}
out = {}
for name in ("excel", "word", "powerpoint"):
    sb = open_sandbox(name)
    try:
        ls = sb.app.LanguageSettings
        r = {}
        for label, const in (("install", 1), ("ui", 2), ("help", 3), ("exe_mode", 4)):
            try:
                v = int(ls.LanguageID(const))
                r[label] = {"lcid": v, "tag": LCID.get(v, "?")}
            except Exception as e:
                r[label] = repr(e)
        r["version"] = str(sb.app.Version)
        try:
            r["build"] = str(sb.app.Build)
        except Exception as e:
            r["build"] = f"n/a ({type(e).__name__})"
        out[name] = r
        print(name, r)
    finally:
        close_sandbox(sb)

save_json("s6_ui_language", out)

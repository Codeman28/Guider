"""Package the engine as the app's sidecar (SPEC §5: PyInstaller onefile).

    .venv/Scripts/python build_sidecar.py
→ ../app/src-tauri/binaries/guider-engine-x86_64-pc-windows-msvc.exe (Tauri externalBin naming).
Data files keep the repo-relative layout the code expects (fixtures/, knowledge/, config/, plans/,
design/tokens.json, safety/blocklist.yaml inside the package).
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "app" / "src-tauri" / "binaries"
NAME = "guider-engine"
TRIPLE = "x86_64-pc-windows-msvc"

entry = HERE / "build" / "sidecar_entry.py"
entry.parent.mkdir(exist_ok=True)
entry.write_text("import sys\nfrom kem_engine.rpc.server import main\n\nif __name__ == '__main__':\n"
                 "    sys.argv = sys.argv[:1]\n    main()\n", encoding="utf-8")

sep = ";"
datas = [
    (HERE / "fixtures", "fixtures"),
    (HERE / "knowledge", "knowledge"),
    (HERE / "config", "config"),
    (HERE / "plans", "plans"),
    (ROOT / "design" / "tokens.json", "design"),
    (HERE / "kem_engine" / "safety" / "blocklist.yaml", "kem_engine/safety"),
    (HERE / "kem_engine" / "vision" / "ocr.ps1", "kem_engine/vision"),
]
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--name", NAME,
       "--distpath", str(HERE / "build" / "dist"), "--workpath", str(HERE / "build" / "work"),
       "--specpath", str(HERE / "build"), "--paths", str(HERE),
       "--collect-submodules", "kem_engine", "--collect-submodules", "pywinauto", "--collect-submodules", "comtypes",
       "--hidden-import", "win32timezone"]
for src, dst in datas:
    cmd += ["--add-data", f"{src}{sep}{dst}"]
cmd.append(str(entry))
subprocess.run(cmd, check=True)
OUT.mkdir(parents=True, exist_ok=True)
target = OUT / f"{NAME}-{TRIPLE}.exe"
shutil.copy2(HERE / "build" / "dist" / f"{NAME}.exe", target)
print(target, round(target.stat().st_size / 1e6, 1), "MB")

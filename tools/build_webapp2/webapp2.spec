# -*- mode: python ; coding: utf-8 -*-
"""Self-contained Windows build; keep local modules at their original paths."""

import ast
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parents[1]
folders = ["src/program/webapp2", "src/program/webapp", "src/program/commands",
           "src/program/data_acquisition", "src/robot", "src/measurement", "src/routines", "tools/robot"]
files = []
for folder in folders:
    for path in (root / folder).rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name.startswith("test_") or path.suffix not in {".py", ".html", ".css", ".js", ".json", ".script", ".svg", ".ico"}:
            continue
        files.append(path)
files.append(root / "src/program/config/config_default.json")
files.append(root / "src/program/config/wall_coordinates.json")
datas = [(str(path), str(path.parent.relative_to(root))) for path in files]

# Local modules use __file__ to find adjacent assets and are imported dynamically.
# Keeping their source layout in the bundle avoids changing the original webapp.
local_roots = {"src", "webapp", "data_acquisition"}
local_roots.update(path.stem for path in files if path.suffix == ".py")
imports = set()
for path in files:
    if path.suffix != ".py":
        continue
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
libraries = {"fastapi", "pydantic", "uvicorn", "rtde_control", "rtde_receive", "rtde_io"}
hiddenimports = sorted({name for name in imports if name.split(".")[0] in sys.stdlib_module_names | libraries}
                       | {"fastapi", "pydantic", "rtde_control", "rtde_receive"})
hiddenimports += collect_submodules("uvicorn")

a = Analysis([str(root / "tools/webapp2.py")], pathex=[str(root)], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=sorted(local_roots), noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="RTM Cobot Studio", debug=False,
          icon=str(root / "src/program/webapp2/static/svti-logo.ico"),
          version=str(Path(SPECPATH) / "version_info.txt"),
          bootloader_ignore_signals=False, strip=False, upx=False, console=True,
          disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
          codesign_identity=None, entitlements_file=None)

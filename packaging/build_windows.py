"""Build a single Windows EXE using a local Python/Tk runtime and Windows csc.exe.

No downloads, third-party packaging modules, installer or registry changes are needed.
Run with Python on 64-bit Windows:
  python packaging/build_windows.py --runtime C:/path/to/python --build C:/path/to/build
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import struct
import sys
import zipfile
from pathlib import Path


def build(runtime: Path, destination: Path):
    if sys.platform != "win32":
        raise SystemExit("Build on Windows using a 64-bit Python/Tk installation.")
    app = Path(__file__).resolve().parents[1]
    packaging = app / "packaging"
    destination.mkdir(parents=True, exist_ok=True)
    runtime = runtime.resolve()
    required = ["python.exe", "pythonw.exe", "python312.dll", "LICENSE.txt"]
    for name in required:
        if not (runtime / name).is_file():
            raise SystemExit(f"Required Python 3.12 runtime file is missing: {name}")
    if not (runtime / "DLLs" / "_tkinter.pyd").is_file():
        raise SystemExit("This Python installation does not include Tcl/Tk.")
    pe = (runtime / "python312.dll").read_bytes()
    pe_offset = struct.unpack_from("<I", pe, 60)[0]
    if struct.unpack_from("<H", pe, pe_offset + 4)[0] != 0x8664:
        raise SystemExit("The runtime must be 64-bit Python 3.12.")

    stdlib_zip = destination / "python312.zip"
    excluded = {"site-packages", "__pycache__", "ensurepip", "idlelib", "turtledemo", "venv"}
    with zipfile.ZipFile(stdlib_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        library = runtime / "Lib"
        for folder, directories, filenames in os.walk(library):
            directories[:] = sorted(name for name in directories if name not in excluded)
            for filename in sorted(filenames):
                path = Path(folder) / filename
                if path.suffix != ".pyc":
                    archive.write(path, path.relative_to(library).as_posix())

    payload = destination / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(runtime.iterdir()):
            if path.is_file() and (path.suffix.lower() in {".exe", ".dll"} or path.name == "LICENSE.txt"):
                archive.write(path, "python/" + path.name)
        archive.write(stdlib_zip, "python/python312.zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("python/python312._pth", "python312.zip\n.\nDLLs\n../app\n")
        for directory in ("DLLs", "tcl"):
            for path in sorted((runtime / directory).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.name.startswith(("_test", "_ctypes_test")) or path.suffix.lower() in {".lib", ".pdb"}:
                    continue
                archive.write(path, "python/" + path.relative_to(runtime).as_posix())
        if not (runtime / "tcl" / "tcl8.6" / "license.terms").is_file():
            archive.write(packaging / "Tcl-license.terms", "python/tcl/tcl8.6/license.terms")
        for path in sorted(app.rglob("*")):
            relative = path.relative_to(app)
            if (path.is_file() and "__pycache__" not in relative.parts
                    and "packaging" not in relative.parts and path.suffix != ".pyc"):
                archive.write(path, "app/" + relative.as_posix())
        archive.write(packaging / "_launch.py", "app/_launch.py")
    with zipfile.ZipFile(payload) as archive:
        assert archive.testzip() is None
        count = len(archive.namelist())

    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not compiler.is_file():
        raise SystemExit("The Windows .NET Framework C# compiler could not be found.")
    executable = destination / "TranslationTools.exe"
    icon = app / "translation_tools" / "assets" / "Darknyte_Nightglass.ico"
    if not icon.is_file():
        raise SystemExit(f"The Darknyte Nightglass app icon is missing: {icon}")
    # Relative paths work with Windows file-system redirection as well as ordinary drives.
    relative = lambda path: os.path.relpath(path, Path.cwd())
    command = [str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001",
               "/reference:System.Windows.Forms.dll", "/reference:System.IO.Compression.dll",
               "/reference:System.IO.Compression.FileSystem.dll",
               "/out:" + relative(executable),
               "/win32icon:" + relative(icon),
               "/resource:" + relative(payload) + ",TranslationTools.Payload.zip",
               "/win32manifest:" + relative(packaging / "app.manifest"), relative(packaging / "Launcher.cs")]
    subprocess.run(command, check=True)
    manifest = {"file": executable.name, "bytes": executable.stat().st_size,
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "payload_files": count, "python": "3.12", "architecture": "Windows x64"}
    (destination / "build-info.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return executable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path(sys.executable).parent)
    parser.add_argument("--build", required=True, type=Path)
    args = parser.parse_args()
    build(args.runtime, args.build.resolve())

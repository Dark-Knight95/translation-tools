"""Entry point inside the bundled runtime, including an optional packaging self-check."""
from __future__ import annotations

import io
import json
import os
import sys
import traceback
from pathlib import Path


def self_test(report: Path):
    import contextlib
    import tkinter
    import unittest
    from importlib.util import module_from_spec, spec_from_file_location

    app_dir = Path(__file__).resolve().parent
    runtime_dir = app_dir.parent / "python"
    data = {"status": "failed", "python": sys.version, "isolated": bool(sys.flags.isolated),
            "executable": sys.executable, "prefix": sys.prefix}
    try:
        assert Path(sys.executable).resolve().parent == runtime_dir.resolve()
        assert Path(sys.prefix).resolve() == runtime_dir.resolve()
        assert sys.flags.isolated and sys.flags.no_site
        import translation_tools.core
        assert str(Path(translation_tools.core.__file__).resolve()).startswith(str(app_dir))
        root = tkinter.Tk()
        root.withdraw()
        data["tk"] = str(root.tk.call("info", "patchlevel"))
        root.destroy()

        log = io.StringIO()
        suite = unittest.defaultTestLoader.discover(str(app_dir / "tests"), pattern="test_core.py")
        result = unittest.TextTestRunner(stream=log, verbosity=1).run(suite)
        data.update(core_tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    core_log=log.getvalue())
        assert result.wasSuccessful(), log.getvalue()

        spec = spec_from_file_location("bundled_gui_smoke", app_dir / "tests" / "gui_smoke.py")
        smoke = module_from_spec(spec)
        spec.loader.exec_module(smoke)
        gui_log = io.StringIO()
        with contextlib.redirect_stdout(gui_log):
            smoke.main()
        data["gui_log"] = gui_log.getvalue()
        assert gui_log.getvalue().count("PASS:") == 4
        data["status"] = "passed"
    except BaseException:
        data["error"] = traceback.format_exc()
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if data["status"] == "passed" else 1


def main():
    # pythonw has no console streams. Keep accidental diagnostic prints harmless.
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        return self_test(Path(sys.argv[2]))
    from translation_tools.gui import main as gui_main
    tab = "timestamps" if sys.argv[1:] == ["--tab", "timestamps"] else "renamer"
    gui_main(tab)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        location = Path(__file__).resolve().parent.parent / "startup-error.txt"
        location.write_text(traceback.format_exc(), encoding="utf-8")
        raise SystemExit(1)

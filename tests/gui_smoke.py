"""Optional desktop smoke check. All file operations use a temporary folder."""
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translation_tools.gui import TranslationToolsApp


def wait_for_worker(app):
    deadline = time.monotonic() + 15
    while app.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)
    assert not app.busy, "Worker did not finish within 15 seconds"


def main():
    app = TranslationToolsApp()
    app.withdraw()
    try:
        app.update()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            subtitle = root / "source.srt"
            subtitle.write_bytes("1\r\n00:00:01,000 --> 00:00:02,000\r\nمرحبا\r\n".encode("utf-8"))
            reference = root / "Episode 1.mkv"
            reference.write_bytes(b"video")
            tab = app.renamer
            tab.names.add_paths([reference])
            tab.sources.add_paths([subtitle])
            tab.folder.set(str(output))
            tab.preview()
            assert len(tab.plan) == 1
            assert str(tab.run_button.cget("state")) == "normal"
            tab.run()
            assert tab.sources.locked and app.timestamps.sources.locked
            wait_for_worker(app)
            assert tab.last_result is not None and not tab.last_result.errors
            assert (output / "Episode 1.srt").read_bytes() == subtitle.read_bytes()
            assert str(tab.run_button.cget("state")) == "disabled"
            assert not tab.sources.locked
            print("PASS: GUI copy workflow")
            tab = app.timestamps
            app.select_tab("timestamps")
            tab.sources.add_paths([subtitle])
            tab.folder.set(str(output))
            tab.offset.set("1.5")
            tab.preview()
            tab.run()
            wait_for_worker(app)
            assert tab.last_result is not None and not tab.last_result.errors
            assert b"00:00:02,500" in (output / "source_shifted.srt").read_bytes()
            print("PASS: GUI subtitle workflow")
            tab.preview()
            assert tab.plan[0].destination.name == "source_shifted (2).srt"
            tab.offset.set("2")
            assert not tab.plan
            assert str(tab.run_button.cget("state")) == "disabled"
            print("PASS: fresh preview and stale-plan protection")
            with patch.object(tab, "show_times") as show_times:
                tab.preview_times()
                wait_for_worker(app)
                show_times.assert_called_once()
                assert show_times.call_args.args[1].cues == 1
            print("PASS: asynchronous timing preview")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()

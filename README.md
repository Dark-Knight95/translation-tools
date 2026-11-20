# Translation Tools

## Windows download

[Download TranslationTools_Windows.zip](downloads/TranslationTools_Windows.zip?raw=1)

Extract the ZIP and run **TranslationTools.exe**. Version 2.0.2 includes the Darknyte Nightglass icon. No Python installation is required for the Windows app. The ready-to-run package, build information and SHA-256 checksum are in `downloads/`.

The repository contains the editable Python source, Windows packaging scripts, tests, sample subtitles and bundled runtime licenses. See `VALIDATION.md` for the completed release checks and `CODE_REVIEW.md` for the review of the original scripts.

A desktop app for copying filenames and shifting subtitle timestamps. Both tools live in one window, with separate launchers if you prefer to open a particular tab.

## Start

If you downloaded **TranslationTools_Windows.zip**, extract it and double-click **TranslationTools.exe**. The Windows executable includes its own Python/Tk runtime. It needs no separate Python installation and runs on 64-bit Windows 10/11.

To run from the source files instead:

1. Extract the entire ZIP into a folder.
2. Install Python 3.10 or newer **with Tcl/Tk** from [python.org](https://www.python.org/downloads/), if it is not already installed. The normal Windows installer includes Tcl/Tk. No pip packages are required.
3. On Windows, double-click **Start Translation Tools.cmd**. You can also run `python TranslationTools.py` from this folder.

The `.py` launchers work when Python file associations are configured:

| Launcher | Opens |
| --- | --- |
| `TranslationTools.py` | Combined app, renamer selected |
| `File Renamer.py` | File Copier & Renamer tab |
| `Timestamp Mover.py` | Timestamp Mover tab |

Keep the `translation_tools` folder next to the Python launchers. On macOS and Linux, launch the source with `python3 TranslationTools.py`; your Python installation needs Tk support. The `.exe` is for Windows only.

## File Copier & Renamer

1. Add reference files under **Names to use**. Their filenames supply the names for the outputs.
2. Add files under **Files to copy**. Use one source to make a copy for every reference name, or provide an equal number of files in both lists.
3. Set the order using the arrows or **Sort 1–10**. Files pair from top to bottom, exactly as shown. Natural sort puts Episode 2 before Episode 10.
4. Choose an output folder and whether to keep the source extension.
5. Select **Preview outputs**, review the mappings, then **Copy & rename**.

Example: use `Episode 1.mkv` and `Episode 2.mkv` as reference names, with two `.srt` source files. Keeping source extensions creates `Episode 1.srt` and `Episode 2.srt`.

The reference files are used only for their names. Source files are copied, leaving the originals in place. Contents are copied byte for byte and file metadata is preserved where supported.

## Subtitle Timestamp Mover

1. Add `.srt` and/or `.ass` files.
2. Enter an offset in seconds. `1.5` moves subtitles later by 1.5 seconds; `-90` moves them earlier by 90 seconds.
3. Optionally change the output suffix, text encoding, or whether ASS comments should shift too.
4. Use **Preview cue times** to inspect the selected file (or the first file if none is selected).
5. Choose an output folder, select **Preview outputs**, then **Shift subtitles**.

The default suffix is `_shifted`. Negative resulting timestamps clamp to zero, and the run details report how many cues were affected. Cues are kept even when clamping makes their start and end both zero. SRT uses milliseconds and ASS uses centiseconds; results round to the nearest supported unit with ties rounded up.

**Auto (Unicode)** preserves UTF-8 with or without a BOM, and UTF-16 with a BOM, including its byte order. For older Arabic files, choose **Windows-1256 (Arabic)**. There is no silent fallback to a guessed encoding. Dialogue text, Arabic characters, ASS styling, line endings and SRT positioning settings are preserved. ASS timing fields follow the `[Events]` Format definition. Timing-like text inside SRT dialogue is left unchanged.

The mover shifts event start/end times only. It does not retime ASS karaoke tags, animated effects inside dialogue text, or embedded media.

## Output conflicts and cancellation

- **Add a number**: choose a free name such as `Episode 1 (2).srt`.
- **Skip**: skip any output whose name is already in use.
- **Stop and review**: require you to resolve a conflict before running.

Existing files are never overwritten, including files that appear after preview. An input changed since preview is rejected and needs a new preview. Each run needs a fresh preview before it can be repeated.

The interface stays responsive during file operations. **Cancel** stops at the next safe checkpoint. Completed outputs remain, and any incomplete current output is removed. Closing the app during a job requests cancellation and waits for cleanup. Reading and decoding a single subtitle file is done as one step, so a very large file can take time before cancellation is observed.

Failures are reported per file and the rest of the batch continues. **View run details** lists saved files, skipped files, errors and warnings. A malformed subtitle file produces no output. The operation is not a transaction across the entire batch; already completed outputs are kept if a later file fails.

The app operates locally and does not make network requests or store your file lists or content. Scroll the tab if your display or Windows text size puts controls below the visible area.

## Verify and develop

From this folder:

```text
python -m unittest discover -s tests -v
python tests/gui_smoke.py
```

The first command exercises parsing, rounding, encoding, collision handling, cancellation and partial failures using disposable test files. The GUI smoke check needs a desktop with Tk; it exercises both tabs through their worker queues. Neither check operates on your own files.

See `CODE_REVIEW.md` for the changes made to the original scripts. The processing code is in `translation_tools/core.py`, and the GUI is in `translation_tools/gui.py`.

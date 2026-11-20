TRANSLATION TOOLS 2.0.2 - DARKNYTE NIGHTGLASS EDITION

START
Extract this ZIP and double-click TranslationTools.exe.
Both tools are available as tabs in the same window.
The executable, app window and taskbar use the Darknyte Nightglass icon.
No Python installation, pip packages or administrator access is needed.
This executable is for 64-bit Windows 10/11. It uses the .NET Framework
already included with Windows.

FILE COPIER & RENAMER
Add the files whose names you want to use, then the files to copy.
Use one source for all names, or match the number of files in both lists.
Set the order, choose an output folder, preview the filenames, then run.

TIMESTAMP MOVER
Add SRT/ASS subtitles and enter an offset in seconds.
Positive values move subtitles later; negative values move them earlier.
Choose an output folder, inspect the previews, then run.
For legacy Arabic text, Windows-1256 is available in the encoding selector.

OUTPUTS
Original files remain in place. Existing outputs are never overwritten.
Use numbering, skipping or conflict rejection to handle duplicate names.
Progress, cancellation and per-file run details are available in both tabs.

HOW THE EXECUTABLE RUNS
The EXE contains the app and its own Python/Tk runtime. On startup it
extracts its support files to a unique temporary folder, then launches
the app without a console window. The folder is removed after the app
closes normally. Allow a few seconds for startup. It makes no network
requests and does not install anything or change registry settings.

SOURCE AND LICENSES
The Source folder includes the editable app, tests and build scripts.
Python's LICENSE.txt and the Tcl/Tk license.terms files are included in
the embedded runtime and copied into the Licenses folder of this ZIP.
See Source/README.md for the full usage guide and Source/CODE_REVIEW.md
for the review of the original scripts.

You can choose an initial tab from a shortcut or command line:
    TranslationTools.exe --tab renamer
    TranslationTools.exe --tab timestamps

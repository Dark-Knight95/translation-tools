# Validation — Windows executable release

Version 2.0.2 adds the Darknyte Nightglass icon to the executable and app window,
sets a Windows app identity for taskbar grouping, and bundles the icon assets
with the editable source. All ten icon sizes (16 through 256 pixels) were
checked against the actual executable resources. The existing packaged
self-check passed 48 core tests and all four GUI checks on this release.

Validated on 20 November 2026 with Windows, bundled Python 3.12.14 and Tcl/Tk 8.6.12.

- **48 core regression tests passed.** Coverage includes time rollover, fractional offsets, zero clamping, malformed cues, custom ASS columns, comment handling, SRT dialogue preservation, Arabic text, Unicode BOMs, UTF-16 byte order, legacy Arabic encoding, copy pairing, natural sorting, output conflicts, changed inputs, cancellation and partial-write cleanup.
- **Both GUI workflows passed.** A desktop smoke check loaded temporary files into each tab, previewed outputs, ran the background workers, verified output bytes/timestamps and checked that controls were restored afterward.
- **Stale-plan checks passed.** Changing the offset invalidated the previous output plan. Repeated processing selected a numbered output rather than replacing the prior result.
- **Asynchronous timing preview passed.** A subtitle was parsed on its worker thread and delivered back through the GUI event queue.

- **Executable isolation check passed.** The compiled EXE extracted its own runtime and executed the tests with system PATH limited to Windows System32 and deliberately invalid external Python/Tk settings. Its child interpreter reported isolated mode and loaded the app from the bundled files.
- **Temporary-file cleanup passed.** After the self-check, the launcher removed its uniquely named extraction directory.

The included checks use temporary files and do not modify the user's original files. The Windows download includes a standalone `TranslationTools.exe` and the editable source. The executable bundles its runtime; Python does not need to be installed separately. The executable is built for 64-bit Windows 10/11 and uses Windows' built-in .NET Framework.

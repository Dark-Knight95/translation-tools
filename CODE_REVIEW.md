# Code review and changes

Reviewed the supplied `File Renamer.py` (284 lines) and `Timestamp Mover.py` (92 lines). The renamer already had a Tkinter GUI; the timestamp mover ran a fixed -90 second shift over the working folder at import time.

| Finding in the original code | Updated behavior |
| --- | --- |
| `shutil.copy2` could silently replace an existing file, including when two generated filenames collided. | Plan output names before running; select numbering, skipping or conflict rejection. Exclusive output creation also protects against files created after preview. |
| Lists could not be reordered, so the source/reference mapping was hard to inspect or correct. | Explicit ordering, up/down controls, natural sort, file removal and a full mapping preview. |
| Copying ran inside the GUI callback and froze the window during large jobs. | A worker thread performs processing; a queue delivers results on the GUI thread. Progress and cancellation remain available. |
| The whole copy batch stopped at the first error, with no clear record of earlier successes. | Per-file errors, continued processing of other files, and a run summary listing outputs and failures. |
| Floating-point rounding could emit invalid ASS `.100` or SRT `,1000` fractions without carrying to the next second. | Decimal arithmetic and integer time units normalize seconds, minutes and hours. |
| A hardcoded offset and working-folder glob determined what was processed. Importing the module could write files. | Choose files and offsets in the GUI. Launchers are guarded by `if __name__ == '__main__'`; importing the timestamp module performs no work. |
| ASS events assumed Start and End were always columns 1 and 2, regardless of the Events Format definition. | Parse `[Events]` Format and use the declared Start/End positions; leave unrelated sections alone. |
| SRT processing stripped timing-line whitespace/settings and assumed a literal space-delimited arrow. | Preserve line layout and positioning settings, accept variable horizontal spacing around the arrow, and leave dialogue text alone. |
| Output was always rewritten as UTF-8 with a BOM and platform-default newlines. | Preserve detected Unicode encoding, BOM and newline style; expose explicit Windows-1256 and Windows-1252 choices for legacy files. |
| A parse/write error could leave a partial output. | Parse each subtitle completely before creating its output. Clean up incomplete files after a cancellation or write failure. |
| There was no protection from an input changing after the user reviewed a mapping. | Retain file identity, size and modification time in the plan and recheck before processing. |
| Processing logic was coupled to the UI and had no regression tests. | Separate reusable processing functions from the interface; add tests focused on data integrity and edge cases. |

## Scope and limitations

The renamer still copies and renames files; it does not rename or move the originals. SRT and ASS are supported. SSA, VTT and retiming of internal ASS animation/karaoke tags are outside this release.

Subtitles are loaded into memory one file at a time. This keeps parsing and output validation straightforward for typical subtitle sizes. Malformed cue timing fails that file rather than silently producing a partially shifted subtitle. Outputs from earlier successful files are retained if a later file fails or the batch is cancelled.

Collision comparisons are conservatively case-insensitive so the same plan is safe on Windows. Copying attempts to preserve ordinary file metadata, but is not a backup of NTFS permissions, alternate streams or every platform-specific attribute.

## Implementation references

- [Python Tkinter threading model](https://docs.python.org/3/library/tkinter.html#threading-model)
- [Python decimal arithmetic and rounding](https://docs.python.org/3/library/decimal.html)
- [Python file opening modes](https://docs.python.org/3/library/functions.html#open)

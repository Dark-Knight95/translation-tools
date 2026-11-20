"""File operations and subtitle parsing, independent of the graphical interface."""
from __future__ import annotations

import codecs
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable


class ValidationError(ValueError):
    """An input cannot be processed safely."""


class Cancelled(Exception):
    """The current operation was cancelled."""


@dataclass(frozen=True)
class Operation:
    source: Path
    destination: Path
    skip: bool = False
    note: str = "Ready"
    fingerprint: tuple[int, int, int, int] = field(default=(), repr=False)


@dataclass
class ShiftResult:
    text: str
    cues: int
    clamped: int = 0
    preview: list[tuple[str, str, str, str]] = field(default_factory=list)


@dataclass
class BatchResult:
    completed: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cancelled: bool = False


ASS_TIME = re.compile(r"^(\d+):([0-5]\d):([0-5]\d)\.(\d{2})$")
SRT_TIME_TEXT = r"\d{2,}:[0-5]\d:[0-5]\d,\d{3}"
SRT_TIME = re.compile(r"^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$")
SRT_LINE = re.compile(
    rf"^(?P<lead>\ufeff?[ \t]*)(?P<start>{SRT_TIME_TEXT})(?P<arrow>[ \t]*-->[ \t]*)"
    rf"(?P<end>{SRT_TIME_TEXT})(?P<tail>[^\r\n]*)(?P<newline>\r\n|\n|\r)?$"
)


def parse_shift(value: str | int | float | Decimal) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError("Enter a number of seconds, such as 1.5 or -90.") from None
    if not number.is_finite() or abs(number) > Decimal("999999999"):
        raise ValidationError("The offset must be finite and between -999999999 and 999999999 seconds.")
    return number


def _ticks(time_str: str, scale: int) -> int:
    match = (ASS_TIME if scale == 100 else SRT_TIME).fullmatch(time_str.strip())
    if not match:
        raise ValidationError(f"Invalid subtitle timestamp: {time_str!r}")
    h, m, s, fraction = map(int, match.groups())
    return (h * 3600 + m * 60 + s) * scale + fraction


def _format_ticks(total: int, scale: int) -> str:
    whole, fraction = divmod(max(0, total), scale)
    h, remainder = divmod(whole, 3600)
    m, s = divmod(remainder, 60)
    if scale == 100:
        return f"{h}:{m:02}:{s:02}.{fraction:02}"
    return f"{h:02}:{m:02}:{s:02},{fraction:03}"


def _shift(time_str: str, offset: Decimal, scale: int) -> tuple[str, bool]:
    # Round the complete shifted time once. Integer divmod carries into minutes/hours.
    value = Decimal(_ticks(time_str, scale)) + offset * scale
    rounded = int(value.to_integral_value(rounding=ROUND_HALF_UP))
    return _format_ticks(rounded, scale), value < 0


def shift_ass_timestamp(time_str: str, shift_seconds: str | float | Decimal) -> str:
    return _shift(time_str, parse_shift(shift_seconds), 100)[0]


def shift_srt_timestamp(time_str: str, shift_seconds: str | float | Decimal) -> str:
    return _shift(time_str, parse_shift(shift_seconds), 1000)[0]


def shift_subtitles(text: str, extension: str, shift_seconds: str | float | Decimal,
                    *, include_comments: bool = True,
                    cancel: threading.Event | None = None) -> ShiftResult:
    """Shift SRT or ASS events, preserving all other text and line endings.

    ASS Start/End positions follow the [Events] Format line rather than fixed columns.
    A malformed cue aborts the file; the caller never saves a partly parsed result.
    """
    extension = extension.lower()
    if extension not in {".srt", ".ass"}:
        raise ValidationError("Only .srt and .ass subtitles are supported.")
    offset = parse_shift(shift_seconds)
    result = ShiftResult("", 0)
    output: list[str] = []
    section = ""
    srt_state = "start"
    columns = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]

    def shift_pair(start: str, end: str, scale: int, line_number: int):
        if _ticks(end, scale) < _ticks(start, scale):
            raise ValidationError(f"Line {line_number}: the end time precedes the start time.")
        new_start, clamp_start = _shift(start, offset, scale)
        new_end, clamp_end = _shift(end, offset, scale)
        result.cues += 1
        result.clamped += int(clamp_start or clamp_end)
        if len(result.preview) < 100:
            result.preview.append((start, end, new_start, new_end))
        return new_start, new_end

    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            if extension == ".srt":
                stripped = line.strip().lstrip("\ufeff")
                if not stripped:
                    srt_state = "start"
                    output.append(line)
                    continue
                if srt_state == "start" and stripped.isdigit():
                    srt_state = "timing"
                    output.append(line)
                    continue
                match = SRT_LINE.fullmatch(line) if srt_state != "text" else None
                if match:
                    start, end = shift_pair(match["start"], match["end"], 1000, number)
                    line = (match["lead"] + start + match["arrow"] + end
                            + match["tail"] + (match["newline"] or ""))
                    srt_state = "text"
                elif srt_state == "timing" or (srt_state == "start" and re.match(r"^\s*\d[^\r\n]*-->", line)):
                    raise ValidationError("Malformed SRT timing line.")
            else:
                stripped = line.strip().lstrip("\ufeff")
                if stripped.startswith("[") and stripped.endswith("]"):
                    section = stripped.casefold()
                elif section == "[events]":
                    kind, sep, payload = line.partition(":")
                    kind = kind.strip().casefold()
                    if sep and kind == "format":
                        columns = [name.strip().casefold() for name in payload.split(",")]
                        if ("start" not in columns or "end" not in columns or columns[-1] != "text"
                                or len(set(columns)) != len(columns)):
                            raise ValidationError("ASS Events Format must contain Start, End and a final Text column.")
                    elif sep and (kind == "dialogue" or (kind == "comment" and include_comments)):
                        fields = payload.split(",", len(columns) - 1)
                        if len(fields) != len(columns):
                            raise ValidationError("ASS event does not match its Format columns.")
                        si, ei = columns.index("start"), columns.index("end")
                        start, end = shift_pair(fields[si].strip(), fields[ei].strip(), 100, number)
                        for index, value in ((si, start), (ei, end)):
                            old = fields[index]
                            fields[index] = old[:len(old) - len(old.lstrip())] + value + old[len(old.rstrip()):]
                        line = line[:line.index(":") + 1] + ",".join(fields)
        except ValidationError as error:
            raise ValidationError(f"Line {number}: {error}") from error
        output.append(line)
    if not result.cues:
        raise ValidationError("No valid subtitle cues found. Check the file format and encoding.")
    result.text = "".join(output)
    return result


def read_subtitle(path: Path, encoding: str = "auto") -> tuple[str, str]:
    raw = Path(path).read_bytes()
    if encoding == "auto":
        if raw.startswith(codecs.BOM_UTF8):
            codec = "utf-8-sig"
        elif raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
            codec = "utf-16"
        else:
            codec = "utf-8"
    else:
        codec = encoding
    try:
        text = raw.decode(codec)
    except (UnicodeError, LookupError) as error:
        raise ValidationError("Cannot decode this subtitle. Select its encoding (for example Windows-1256 for Arabic).") from error
    # Keep the original UTF-16 byte order and BOM on output as well.
    if codec == "utf-16":
        codec = "utf-16-be" if raw.startswith(codecs.BOM_UTF16_BE) else "utf-16-le"
        text = "\ufeff" + text
    return text, codec


def natural_key(value: str | Path):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r"(\d+)", Path(value).name))


def path_key(path: Path) -> str:
    # Conservative case-insensitive planning also catches collisions on Windows.
    return str(path.resolve()).casefold()


def fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _validate_files(files: Iterable[str | Path]) -> list[Path]:
    paths = [Path(path).expanduser().resolve() for path in files]
    if not paths:
        raise ValidationError("Add at least one file.")
    if len({path_key(path) for path in paths}) != len(paths):
        raise ValidationError("The file list contains duplicates.")
    for path in paths:
        if not path.is_file():
            raise ValidationError(f"File no longer exists: {path}")
    return paths


def _plan(pairs: Iterable[tuple[Path, Path]], output_dir: str | Path,
          collision: str) -> list[Operation]:
    folder = Path(output_dir).expanduser().resolve()
    if not folder.is_dir():
        raise ValidationError("Choose an existing output folder.")
    if collision not in {"number", "skip", "error"}:
        raise ValidationError("Choose a valid conflict policy.")
    occupied = {path_key(path) for path in folder.iterdir()}
    plan = []
    for source, requested in pairs:
        destination = folder / requested.name
        key = path_key(destination)
        skip, note = False, "Ready"
        if key in occupied:
            if collision == "error":
                raise ValidationError(f"Output name already exists or occurs twice: {destination.name}")
            if collision == "skip":
                skip, note = True, "Skipped: name exists"
            else:
                version = 2
                while key in occupied:
                    destination = folder / f"{requested.stem} ({version}){requested.suffix}"
                    key = path_key(destination)
                    version += 1
                note = "Ready: numbered to avoid conflict"
        occupied.add(key)
        plan.append(Operation(source, destination, skip, note, fingerprint(source)))
    return plan


def plan_copies(targets: Iterable[str | Path], sources: Iterable[str | Path],
                output_dir: str | Path, *, keep_extension: bool = True,
                collision: str = "number") -> list[Operation]:
    names, originals = _validate_files(targets), _validate_files(sources)
    if len(originals) != 1 and len(originals) != len(names):
        raise ValidationError(f"You have {len(names)} name files and {len(originals)} source files. "
                              "Use one source for all names, or an equal number of both.")
    pairs = []
    for index, target in enumerate(names):
        source = originals[0] if len(originals) == 1 else originals[index]
        filename = target.stem + source.suffix if keep_extension else target.name
        pairs.append((source, Path(filename)))
    return _plan(pairs, output_dir, collision)


def plan_subtitles(sources: Iterable[str | Path], output_dir: str | Path,
                   *, suffix: str = "_shifted", collision: str = "number") -> list[Operation]:
    paths = _validate_files(sources)
    if not suffix or re.search(r'[<>:"/\\|?*\x00-\x1f]', suffix) or suffix.endswith((".", " ")):
        raise ValidationError("Use a nonempty filename suffix without special path characters or trailing dots/spaces.")
    for path in paths:
        if path.suffix.lower() not in {".srt", ".ass"}:
            raise ValidationError(f"Unsupported subtitle format: {path.name}")
    return _plan(((path, Path(path.stem + suffix + path.suffix)) for path in paths), output_dir, collision)


def _check_cancel(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled()


def _write_exclusive(destination: Path, chunks: Iterable[bytes], cancel: threading.Event):
    # 'xb' is the final protection if a file appears after planning; never truncate it.
    created = False
    try:
        _check_cancel(cancel)
        with destination.open("xb") as output:
            created = True
            for chunk in chunks:
                _check_cancel(cancel)
                output.write(chunk)
            _check_cancel(cancel)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def run_batch(plan: list[Operation], *, shift_seconds: str | Decimal | None = None,
              encoding: str = "auto", include_comments: bool = True,
              cancel: threading.Event | None = None,
              progress: Callable[[int, Operation, str], None] | None = None) -> BatchResult:
    cancel = cancel if cancel is not None else threading.Event()
    offset = parse_shift(shift_seconds) if shift_seconds is not None else None
    result = BatchResult()
    for index, operation in enumerate(plan):
        if cancel.is_set():
            result.cancelled = True
            break
        try:
            if operation.skip:
                result.skipped.append(operation.source)
                if progress:
                    progress(index, operation, "Skipped")
                continue
            if fingerprint(operation.source) != operation.fingerprint:
                raise ValidationError("The source changed since preview. Refresh the preview and retry.")
            if progress:
                progress(index, operation, "Working")
            if offset is None:
                with operation.source.open("rb") as input_file:
                    chunks = iter(lambda: input_file.read(1024 * 1024), b"")
                    _write_exclusive(operation.destination, chunks, cancel)
                try:
                    shutil.copystat(operation.source, operation.destination)
                except OSError as error:
                    result.warnings.append(f"{operation.destination.name}: copied, but metadata could not be preserved ({error}).")
            else:
                text, codec = read_subtitle(operation.source, encoding)
                shifted = shift_subtitles(text, operation.source.suffix, offset,
                                          include_comments=include_comments, cancel=cancel)
                data = shifted.text.encode(codec)
                _write_exclusive(operation.destination,
                                 (data[i:i + 1024 * 1024] for i in range(0, len(data), 1024 * 1024)), cancel)
                if shifted.clamped:
                    result.warnings.append(f"{operation.source.name}: {shifted.clamped} cue(s) reached zero; negative times were clamped.")
            result.completed.append(operation.destination)
            if progress:
                progress(index, operation, "Saved")
        except Cancelled:
            result.cancelled = True
            break
        except (OSError, ValueError, UnicodeError) as error:
            result.errors.append((operation.source, str(error)))
            if progress:
                progress(index, operation, f"Error: {error}")
    return result


def move_subtitles(input_file: str | Path, output_file: str | Path,
                   shift_seconds: str | float | Decimal) -> ShiftResult:
    """Compatibility helper: shift one file, refusing to replace an existing output."""
    source, destination = Path(input_file), Path(output_file)
    text, codec = read_subtitle(source)
    result = shift_subtitles(text, source.suffix, shift_seconds)
    _write_exclusive(destination, [result.text.encode(codec)], threading.Event())
    return result

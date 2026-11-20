import codecs
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from translation_tools.core import (Cancelled, ValidationError, _write_exclusive,
    move_subtitles, natural_key, parse_shift, plan_copies, plan_subtitles,
    read_subtitle, run_batch, shift_ass_timestamp, shift_srt_timestamp, shift_subtitles)


SRT = "1\r\n00:00:01,000 --> 00:00:02,500 X1:0 X2:1\r\nمرحبا بالعالم\r\n\r\n2\r\n00:00:59,999 --> 00:01:01,000\r\nSecond cue\r\n"
ASS = ("[Script Info]\r\nTitle: Test\r\n[Events]\r\n"
       "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
       "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}مرحبا, world{\\i0}\r\n"
       "Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Keep this, comma\r\n")


class TimestampTests(unittest.TestCase):
    def test_srt_fraction_carries_into_next_minute(self):
        self.assertEqual(shift_srt_timestamp("00:00:59,999", "0.0005"), "00:01:00,000")

    def test_ass_fraction_carries_into_next_minute(self):
        self.assertEqual(shift_ass_timestamp("0:00:59.99", "0.005"), "0:01:00.00")

    def test_hour_carry(self):
        self.assertEqual(shift_srt_timestamp("00:59:59,999", "0.001"), "01:00:00,000")

    def test_large_hours(self):
        self.assertEqual(shift_ass_timestamp("12:59:59.99", "0.01"), "13:00:00.00")

    def test_decimal_shift(self):
        self.assertEqual(shift_srt_timestamp("00:00:00,900", "0.1"), "00:00:01,000")

    def test_negative_clamps(self):
        self.assertEqual(shift_srt_timestamp("00:00:01,000", "-90"), "00:00:00,000")

    def test_invalid_offset(self):
        for value in ("", "hello", "NaN", "Infinity", "-Infinity", "1e99"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_shift(value)

    def test_invalid_timestamp(self):
        for timestamp in ("00:61:00,000", "00:00:60,000", "-01:00:00,000", "00:00:00,1000"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValidationError):
                shift_srt_timestamp(timestamp, 1)

    def test_preserves_srt_arabic_crlf_and_settings(self):
        result = shift_subtitles(SRT, ".srt", "1.5")
        self.assertIn("00:00:02,500 --> 00:00:04,000 X1:0 X2:1\r\nمرحبا بالعالم", result.text)
        self.assertNotIn("\n", result.text.replace("\r\n", ""))
        self.assertEqual(result.cues, 2)

    def test_keeps_timing_like_dialogue_text(self):
        text = "1\n00:00:01,000 --> 00:00:02,000\n00:00:10,000 --> 00:00:20,000\n5 --> 6\n"
        result = shift_subtitles(text, ".srt", 1)
        self.assertIn("\n00:00:10,000 --> 00:00:20,000\n5 --> 6\n", result.text)
        self.assertEqual(result.cues, 1)

    def test_no_final_newline(self):
        result = shift_subtitles("1\n00:00:01,000-->00:00:02,000\nText", ".srt", 1)
        self.assertTrue(result.text.endswith("Text"))

    def test_clamp_count(self):
        result = shift_subtitles(SRT, ".srt", -2)
        self.assertEqual(result.clamped, 1)

    def test_ass_preserves_text_and_styles(self):
        result = shift_subtitles(ASS, ".ASS", 1)
        self.assertEqual(result.cues, 2)
        self.assertIn("0:00:02.00,0:00:03.50", result.text)
        self.assertIn("{\\i1}مرحبا, world{\\i0}\r\n", result.text)

    def test_ass_comments_option(self):
        result = shift_subtitles(ASS, ".ass", 1, include_comments=False)
        self.assertEqual(result.cues, 1)
        self.assertIn("Comment: 0,0:00:03.00,0:00:04.00", result.text)

    def test_ass_custom_field_order(self):
        text = "[Events]\nFormat: End, Start, Layer, Text\nDialogue: 0:00:03.00,0:00:01.00,0,Hello, world\n"
        result = shift_subtitles(text, ".ass", 1)
        self.assertIn("Dialogue: 0:00:04.00,0:00:02.00,0,Hello, world\n", result.text)

    def test_ass_non_event_sections_untouched(self):
        text = "[Script Info]\nComment: This is metadata\n" + ASS
        self.assertIn("Comment: This is metadata\n", shift_subtitles(text, ".ass", 1).text)

    def test_ass_bom_before_first_events_section(self):
        text = "\ufeff[Events]\nFormat: Start, End, Text\nDialogue: 0:00:01.00,0:00:02.00,مرحبا\n"
        result = shift_subtitles(text, ".ass", 1)
        self.assertTrue(result.text.startswith("\ufeff[Events]"))
        self.assertIn("0:00:02.00,0:00:03.00,مرحبا", result.text)

    def test_srt_bom_before_unindexed_timing(self):
        text = "\ufeff00:00:01,000 --> 00:00:02,000\nمرحبا"
        result = shift_subtitles(text, ".srt", 1)
        self.assertTrue(result.text.startswith("\ufeff00:00:02,000"))

    def test_ass_bad_format_aborts(self):
        with self.assertRaises(ValidationError):
            shift_subtitles("[Events]\nFormat: Layer, Text\nDialogue: 0,Hello", ".ass", 1)

    def test_ass_malformed_event_aborts(self):
        with self.assertRaisesRegex(ValidationError, "Line"):
            shift_subtitles(ASS + "Dialogue: broken\n", ".ass", 1)

    def test_srt_malformed_timing_aborts(self):
        with self.assertRaisesRegex(ValidationError, "Line 2"):
            shift_subtitles("1\n00:99:00,000 --> 00:00:01,000\nhello\n", ".srt", 1)

    def test_reversed_cue_rejected(self):
        with self.assertRaisesRegex(ValidationError, "end time"):
            shift_subtitles("1\n00:00:03,000 --> 00:00:01,000\ntext", ".srt", 1)

    def test_unsupported_or_empty(self):
        for extension, text in ((".vtt", SRT), (".srt", "not subtitles"), (".ass", "")):
            with self.subTest(extension=extension), self.assertRaises(ValidationError):
                shift_subtitles(text, extension, 1)

    def test_preview_limit(self):
        text = "\n\n".join(f"{n}\n00:00:01,000 --> 00:00:02,000\nText" for n in range(1, 150))
        result = shift_subtitles(text, ".srt", 1)
        self.assertEqual(result.cues, 149)
        self.assertEqual(len(result.preview), 100)

    def test_parsing_cancel(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            shift_subtitles(SRT, ".srt", 1, cancel=event)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.source = self.create("subtitle.srt", SRT.encode("utf-8"))
        self.names = [self.create("Episode 1.mkv", b"video1"), self.create("Episode 2.mkv", b"video2")]

    def create(self, name, content):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_one_source_many_names(self):
        plan = plan_copies(self.names, [self.source], self.output)
        self.assertEqual([p.destination.name for p in plan], ["Episode 1.srt", "Episode 2.srt"])
        result = run_batch(plan)
        self.assertEqual(len(result.completed), 2)
        self.assertEqual(result.errors, [])
        for path in result.completed:
            self.assertEqual(path.read_bytes(), self.source.read_bytes())
        self.assertTrue(self.source.exists())

    def test_equal_count_order_and_exact_extension(self):
        second = self.create("other.txt", b"other")
        plan = plan_copies(list(reversed(self.names)), [self.source, second], self.output, keep_extension=False)
        self.assertEqual(plan[0].destination.name, "Episode 2.mkv")
        self.assertEqual(plan[1].source, second.resolve())

    def test_mismatch_rejected(self):
        third = self.create("third.txt", b"third")
        with self.assertRaises(ValidationError):
            plan_copies(self.names, [self.source, self.names[0], third], self.output)

    def test_collision_policies(self):
        existing = self.output / "Episode 1.srt"
        existing.write_bytes(b"keep me")
        plan = plan_copies(self.names, [self.source], self.output)
        self.assertEqual(plan[0].destination.name, "Episode 1 (2).srt")
        skipped = plan_copies(self.names, [self.source], self.output, collision="skip")
        self.assertTrue(skipped[0].skip)
        with self.assertRaises(ValidationError):
            plan_copies(self.names, [self.source], self.output, collision="error")
        self.assertEqual(existing.read_bytes(), b"keep me")

    def test_duplicate_output_names_in_batch(self):
        other = self.create("Episode 1.mp4", b"video3")
        plan = plan_copies([self.names[0], other], [self.source], self.output)
        self.assertEqual(plan[1].destination.name, "Episode 1 (2).srt")

    def test_skip_batch_reports_skip_and_continues(self):
        existing = self.output / "Episode 1.srt"
        existing.write_bytes(b"existing")
        result = run_batch(plan_copies(self.names, [self.source], self.output, collision="skip"))
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(result.completed), 1)
        self.assertEqual(existing.read_bytes(), b"existing")

    def test_case_insensitive_collision(self):
        (self.output / "EPISODE 1.SRT").write_bytes(b"existing")
        plan = plan_copies([self.names[0]], [self.source], self.output)
        self.assertEqual(plan[0].destination.name, "Episode 1 (2).srt")

    def test_file_appearing_after_preview_is_never_overwritten(self):
        plan = plan_copies(self.names, [self.source], self.output)
        plan[0].destination.write_bytes(b"new file")
        result = run_batch(plan)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.completed), 1)
        self.assertEqual(plan[0].destination.read_bytes(), b"new file")

    def test_input_changed_after_preview(self):
        plan = plan_copies(self.names, [self.source], self.output)
        self.source.write_bytes(b"changed")
        result = run_batch(plan)
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_missing_input(self):
        self.source.unlink()
        with self.assertRaises(ValidationError):
            plan_copies(self.names, [self.source], self.output)

    def test_own_source_is_not_replaced(self):
        plan = plan_copies([self.source], [self.source], self.root)
        self.assertEqual(plan[0].destination.name, "subtitle (2).srt")

    def test_cancel_before_batch(self):
        event = threading.Event()
        event.set()
        result = run_batch(plan_copies(self.names, [self.source], self.output), cancel=event)
        self.assertTrue(result.cancelled)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cancel_removes_incomplete_output(self):
        event = threading.Event()
        destination = self.output / "incomplete.bin"
        def chunks():
            yield b"first"
            event.set()
            yield b"second"
        with self.assertRaises(Cancelled):
            _write_exclusive(destination, chunks(), event)
        self.assertFalse(destination.exists())

    def test_disk_write_failure_removes_incomplete_output(self):
        destination = self.output / "broken.bin"
        def chunks():
            yield b"first"
            raise OSError("Simulated disk failure")
        with self.assertRaises(OSError):
            _write_exclusive(destination, chunks(), threading.Event())
        self.assertFalse(destination.exists())

    def test_batch_subtitles_and_source_unchanged(self):
        original = self.source.read_bytes()
        plan = plan_subtitles([self.source], self.output)
        result = run_batch(plan, shift_seconds="1.5")
        self.assertEqual(result.errors, [])
        self.assertIn(b"00:00:02,500", result.completed[0].read_bytes())
        self.assertEqual(self.source.read_bytes(), original)
        self.assertIn(b"\r\n", result.completed[0].read_bytes())

    def test_malformed_file_leaves_no_output_and_batch_continues(self):
        bad = self.create("bad.ass", b"[Events]\nDialogue: bad\n")
        result = run_batch(plan_subtitles([bad, self.source], self.output), shift_seconds=1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.completed), 1)
        self.assertFalse((self.output / "bad_shifted.ass").exists())

    def test_keep_utf8_bom_and_no_bom(self):
        for bom in (b"", codecs.BOM_UTF8):
            self.source.write_bytes(bom + SRT.encode("utf-8"))
            text, codec = read_subtitle(self.source)
            self.assertEqual(text.encode(codec), self.source.read_bytes())

    def test_utf16_byte_order_and_bom_preserved(self):
        for bom, codec in ((codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
            with self.subTest(codec=codec):
                self.source.write_bytes(bom + SRT.encode(codec))
                text, output_codec = read_subtitle(self.source)
                shifted = shift_subtitles(text, ".srt", 1)
                self.assertEqual(shifted.text.encode(output_codec)[:2], bom)

    def test_arabic_windows_encoding(self):
        self.source.write_bytes(SRT.encode("cp1256"))
        with self.assertRaises(ValidationError):
            read_subtitle(self.source)
        text, codec = read_subtitle(self.source, "cp1256")
        self.assertIn("مرحبا", text)
        self.assertEqual(text.encode(codec), self.source.read_bytes())

    def test_bad_output_suffix(self):
        for suffix in ("", "../oops", "a:b", "trail.", "trail "):
            with self.subTest(suffix=suffix), self.assertRaises(ValidationError):
                plan_subtitles([self.source], self.output, suffix=suffix)

    def test_move_subtitles_compatibility(self):
        destination = self.output / "shifted.srt"
        result = move_subtitles(self.source, destination, 1)
        self.assertEqual(result.cues, 2)
        with self.assertRaises(FileExistsError):
            move_subtitles(self.source, destination, 1)

    def test_natural_sort(self):
        names = ["Episode 10.mkv", "Episode 2.mkv", "Episode 1.mkv"]
        self.assertEqual(sorted(names, key=natural_key), ["Episode 1.mkv", "Episode 2.mkv", "Episode 10.mkv"])

    def test_importing_timestamp_script_has_no_side_effects(self):
        wrapper = Path(__file__).resolve().parents[1] / "Timestamp Mover.py"
        spec = importlib.util.spec_from_file_location("timestamp_mover_wrapper", wrapper)
        with patch("translation_tools.gui.main") as main:
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        main.assert_not_called()


if __name__ == "__main__":
    unittest.main()

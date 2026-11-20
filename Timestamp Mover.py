"""Open Timestamp Mover; importing this file never processes any files."""
from translation_tools.core import move_subtitles, shift_ass_timestamp, shift_srt_timestamp
from translation_tools.gui import main

if __name__ == "__main__":
    main("timestamps")

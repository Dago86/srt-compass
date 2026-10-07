import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.selection import (
    StartTimeError,
    create_chunks,
    format_time_value,
    parse_start_minutes,
    parse_time_range,
    parse_time_value,
)


class StartSelectionTests(unittest.TestCase):
    def test_accepts_integer_decimal_point_and_decimal_comma(self) -> None:
        duration = 60 * 60
        self.assertEqual(parse_start_minutes("40", duration), 40 * 60)
        self.assertEqual(parse_start_minutes("40.5", duration), 40 * 60 + 30)
        self.assertEqual(parse_start_minutes("40,5", duration), 40 * 60 + 30)

    def test_rejects_invalid_or_out_of_range_values(self) -> None:
        duration = 60 * 60
        invalid_values = ("", "hello", "-1", "60", "61", "nan", "inf", "-inf")
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(StartTimeError):
                parse_start_minutes(value, duration)

    def test_chunks_keep_absolute_video_offsets(self) -> None:
        chunks = create_chunks(60 * 60, 40 * 60)
        self.assertEqual([chunk["start"] for chunk in chunks], [2400, 3000])
        self.assertEqual([chunk["duration"] for chunk in chunks], [600, 600])

    def test_start_near_end_creates_one_short_chunk(self) -> None:
        chunks = create_chunks(60 * 60, 60 * 60 - 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["start"], 3599)
        self.assertTrue(math.isclose(chunks[0]["duration"], 1))

    def test_time_fields_accept_clock_and_decimal_minutes(self) -> None:
        self.assertEqual(parse_time_value("00:40:30"), 2430)
        self.assertEqual(parse_time_value("40,5"), 2430)
        self.assertEqual(format_time_value(2430), "00:40:30")

    def test_selected_end_limits_chunks(self) -> None:
        chunks = create_chunks(60 * 60, 40 * 60, end_at_seconds=50 * 60)
        self.assertEqual(
            chunks, [{"start": 2400, "duration": 600, "status": "pending"}]
        )
        self.assertEqual(parse_time_range("40", "50", 3600), (2400, 3000))

    def test_range_rejects_reverse_equal_and_beyond_duration(self) -> None:
        for start, end in (("40", "40"), ("50", "40"), ("0", "61")):
            with self.subTest(start=start, end=end), self.assertRaises(StartTimeError):
                parse_time_range(start, end, 3600)


if __name__ == "__main__":
    unittest.main()

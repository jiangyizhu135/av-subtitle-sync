import unittest

from subsync.inventory import parse_number, subtitle_for


class ParseNumberTests(unittest.TestCase):
    def test_basic_and_prefixes(self):
        self.assertEqual(parse_number("ABC-001.mp4"), "ABC-001")
        self.assertEqual(parse_number("forum.example.com@ABC-002.mp4"), "ABC-002")
        self.assertEqual(parse_number("ABC-003-C.mp4"), "ABC-003")
        self.assertEqual(parse_number("ABC-003-U.mp4"), "ABC-003")

    def test_suffix_and_variants(self):
        self.assertEqual(parse_number("ABC-004.restored.mp4"), "ABC-004")
        self.assertEqual(parse_number("ABC-004.restored_prob2.mp4"), "ABC-004")
        self.assertEqual(parse_number("TEST-123_4K.mp4"), "TEST-123")
        self.assertEqual(parse_number("XYZ-999.part1.mp4"), "XYZ-999")

    def test_zero_padding(self):
        self.assertEqual(parse_number("ABC-038_4K.mp4"), "ABC-038")
        self.assertEqual(parse_number("abc00499_2_8k.mp4"), "ABC-499")

    def test_cjk_tail(self):
        self.assertEqual(parse_number("ABC-005合成名.restored.mp4"), "ABC-005")

    def test_junk_returns_none(self):
        for name in ("无 番 号 视 频.mp4", "aa直播剪辑.mp4", "18+游戏.mp4"):
            self.assertIsNone(parse_number(name), name)



class SubtitleMatchTests(unittest.TestCase):
    VIDEO = "site@ABC-001.mp4"

    def test_matches(self):
        for cand in ("site@ABC-001.srt", "site@ABC-001.mp4.srt", "site@ABC-001.zh-CN.srt",
                     "site@ABC-001.zh-Hans.srt", "site@ABC-001.chs.ass"):
            self.assertTrue(subtitle_for(self.VIDEO, cand), cand)

    def test_no_false_match(self):
        for cand in ("other.srt", "ABC-002.srt", "site@ABC-001-poster.png",
                     "site@ABC-001.nfo", "site@ABC-001.jpg"):
            self.assertFalse(subtitle_for(self.VIDEO, cand), cand)


if __name__ == "__main__":
    unittest.main()

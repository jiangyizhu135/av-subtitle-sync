import unittest
from pathlib import Path

import pysubs2

from subsync import clean as clean_mod
from subsync.srt import validate_srt

FIX = Path(__file__).parent / "fixtures" / "subtitles"


class SrtValidationTests(unittest.TestCase):
    def test_valid(self):
        rep = validate_srt((FIX / "sample.srt").read_bytes())
        self.assertTrue(rep.ok)
        self.assertEqual(rep.cue_count, 2)
        self.assertEqual(rep.encoding, "utf-8")

    def test_gbk(self):
        rep = validate_srt((FIX / "sample.srt").read_text(encoding="utf-8").encode("gbk"))
        self.assertTrue(rep.ok)
        self.assertEqual(rep.encoding, "gbk")

    def test_garbage(self):
        self.assertFalse(validate_srt(b"not a subtitle").ok)


class CleanTests(unittest.TestCase):
    def test_drop_invalid_keep_timeline(self):
        data = (FIX / "invalid_timeline.srt").read_bytes()
        kept, removed = clean_mod.clean_events(
            pysubs2.SSAFile.from_string(data.decode("utf-8-sig"), format_="srt"))
        self.assertEqual(removed, 1)
        self.assertEqual([(e.start, e.end, e.plaintext) for e in kept],
                         [(1000, 3000, "正常字幕。"), (6000, 8000, "正常字幕二。")])
        out = clean_mod.build_final(kept)
        rev = pysubs2.SSAFile.from_string(out.decode("utf-8"), format_="srt")
        self.assertEqual(len(rev.events), 2)
        self.assertEqual(sum(1 for e in rev.events if e.plaintext.strip() == ""), 0)


if __name__ == "__main__":
    unittest.main()

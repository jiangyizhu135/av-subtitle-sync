import unittest
from pathlib import Path

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
        # 经 clean.load_srt（生产归一加载器）解析 fixture；
        # fixture 在仓库固定 LF（.gitattributes），即使 Windows checkout 也保持 LF。
        data = (FIX / "invalid_timeline.srt").read_bytes()
        ssa = clean_mod.load_srt(data)
        kept, removed = clean_mod.clean_events(ssa)
        self.assertEqual(removed, 1)
        self.assertEqual([(e.start, e.end, e.plaintext) for e in kept],
                         [(1000, 3000, "正常字幕。"), (6000, 8000, "正常字幕二。")])
        out = clean_mod.build_final(kept)
        rev = clean_mod.load_srt(out)
        self.assertEqual(len(rev.events), 2)
        self.assertEqual(sum(1 for e in rev.events if e.plaintext.strip() == ""), 0)


LF_SRT = "1\n00:00:01,000 --> 00:00:03,000\n测试字幕。\n\n2\n00:00:04,000 --> 00:00:06,000\n第二条。\n"
MULTILINE_SRT = ("1\n00:00:01,000 --> 00:00:03,000\n第一行\n第二行\n\n"
                 "2\n00:00:04,000 --> 00:00:06,000\n下一句。\n")


class NewlineNormalizationTests(unittest.TestCase):
    """LF / CRLF / legacy-CR 输入必须解析出语义一致的 cue（start/end/text）。"""

    def _cues(self, data: bytes):
        ssa = clean_mod.load_srt(data)
        return [(e.start, e.end, e.plaintext) for e in ssa.events]

    def test_lf(self):
        self.assertEqual(self._cues(LF_SRT.encode("utf-8")),
                         [(1000, 3000, "测试字幕。"), (4000, 6000, "第二条。")])

    def test_crlf(self):
        crlf = LF_SRT.replace("\n", "\r\n").encode("utf-8")
        self.assertEqual(self._cues(crlf),
                         [(1000, 3000, "测试字幕。"), (4000, 6000, "第二条。")])

    def test_cr_only(self):
        cr = LF_SRT.replace("\n", "\r").encode("utf-8")
        self.assertEqual(self._cues(cr),
                         [(1000, 3000, "测试字幕。"), (4000, 6000, "第二条。")])

    def test_mixed_newline_no_cr_leak(self):
        # 混合换行：cue1 用 CRLF，cue2 用 LF，中间夹 legacy CR —— 不得有 \r 泄漏进 text
        mixed = ("1\r\n00:00:01,000 --> 00:00:03,000\r\n测试字幕。\r\n\r\n"
                 "2\n00:00:04,000 --> 00:00:06,000\n第二条。\r\n").encode()
        cues = self._cues(mixed)
        self.assertEqual(cues, [(1000, 3000, "测试字幕。"), (4000, 6000, "第二条。")])
        self.assertTrue(all("\r" not in text for _, _, text in cues))

    def test_multiline_cue_preserved(self):
        # 真实多行字幕：两行信息必须保留，不能被 newline 归一吃掉
        cues = self._cues(MULTILINE_SRT.encode("utf-8"))
        self.assertEqual(cues, [(1000, 3000, "第一行\n第二行"), (4000, 6000, "下一句。")])

    def test_fixture_drop_invalid_cross_platform(self):
        # 复现 Windows CI 失败场景：读 fixture 字节（LF 固定），经 load_srt 归一后无 \r 残留
        data = (FIX / "invalid_timeline.srt").read_bytes()
        cues = [(e.start, e.end, e.plaintext) for e in clean_mod.load_srt(data).events]
        self.assertEqual(cues,
                         [(1000, 3000, "正常字幕。"), (5000, 5000, "坏时间轴。"), (6000, 8000, "正常字幕二。")])
        self.assertTrue(all("\r" not in text for _, _, text in cues))

    def test_build_final_written_lf(self):
        # clean 输出应为统一 LF 文本（无 \r）
        kept, _ = clean_mod.clean_events(clean_mod.load_srt(LF_SRT.encode("utf-8")))
        out = clean_mod.build_final(kept).decode("utf-8")
        self.assertNotIn("\r", out)


if __name__ == "__main__":
    unittest.main()

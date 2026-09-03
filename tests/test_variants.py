import unittest

from subsync.variants import classify_number_videos


def vids(*tuples):
    return [{"name": n, "rel": f"dir/{n}", "size": s} for n, s in tuples]


class MultipartPriorityTests(unittest.TestCase):
    def test_multipart_beats_quality(self):
        g = classify_number_videos("TEST-004", vids(
            ("TEST-004_1_8K.mp4", 7_000_000_000), ("TEST-004_2_8K.mp4", 9_000_000_000)))
        self.assertEqual(g.kind, "MULTIPART")

    def test_part_word(self):
        g = classify_number_videos("TEST-005", vids(
            ("TEST-005.part1.mp4", 1), ("TEST-005.part2.mp4", 2)))
        self.assertEqual(g.kind, "MULTIPART")


class QualityVariantTests(unittest.TestCase):
    def test_base_plus_4k(self):
        g = classify_number_videos("TEST-006", vids(
            ("TEST-006.mp4", 6_000_000_000), ("TEST-006_4K.mp4", 25_000_000_000)))
        self.assertEqual(g.kind, "VIDEO_VARIANT_GROUP")
        self.assertEqual([v["quality"] for v in g.variants], ["", "4K"])
        self.assertEqual([v["subtitle_name"] for v in g.variants],
                         ["TEST-006.srt", "TEST-006_4K.srt"])

    def test_unknown_suffix_ambiguous(self):
        g = classify_number_videos("TEST-007", vids(
            ("TEST-007.mp4", 1), ("TEST-007-special.mp4", 2)))
        self.assertEqual(g.kind, "AMBIGUOUS")


class DuplicateCopyTests(unittest.TestCase):
    def test_cross_dir_duplicate(self):
        g = classify_number_videos("TEST-008", vids(
            ("site@test-008.mp4", 1_000), ("site@test-008.mp4", 1_000)))
        self.assertEqual(g.kind, "DUPLICATE_COPY_GROUP")
        self.assertEqual(g.copy_count, 2)
        self.assertFalse(g.content_hash_verified)
        self.assertTrue(all(v["subtitle_upload_allowed"] for v in g.variants))

    def test_same_name_diff_size_ambiguous(self):
        g = classify_number_videos("TEST-008", vids(
            ("site@test-008.mp4", 100), ("site@test-008.mp4", 200)))
        self.assertEqual(g.kind, "AMBIGUOUS")


class EditionTests(unittest.TestCase):
    def test_standard_plus_edition(self):
        g = classify_number_videos("TEST-009", vids(
            ("TEST-009.mp4", 1_000), ("TEST-009-U.mp4", 2_000)))
        self.assertEqual(g.kind, "EDITION_VARIANT_GROUP")
        self.assertEqual(g.edition_suffix, "U")
        roles = {v["video_name"]: v["role"] for v in g.variants}
        self.assertEqual(roles["TEST-009.mp4"], "STANDARD")
        self.assertEqual(roles["TEST-009-U.mp4"], "EDITION_VARIANT_UNRESOLVED")
        allowed = {v["video_name"]: v["subtitle_upload_allowed"] for v in g.variants}
        self.assertTrue(allowed["TEST-009.mp4"])
        self.assertFalse(allowed["TEST-009-U.mp4"])

    def test_unlisted_suffix_stays_ambiguous(self):
        g = classify_number_videos("TEST-010", vids(
            ("TEST-010-C.mp4", 1), ("TEST-010.mp4", 2)))
        self.assertEqual(g.kind, "AMBIGUOUS")


class SingleTests(unittest.TestCase):
    def test_single_unexplained_suffix_is_single(self):
        g = classify_number_videos("TEST-011", vids(("TEST-011.restored_prob2.mp4", 5)))
        self.assertEqual(g.kind, "SINGLE")


if __name__ == "__main__":
    unittest.main()

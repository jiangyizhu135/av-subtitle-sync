import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from typing import ClassVar

from subsync import cli
from subsync.nfo import build_nfo_bytes, compose_nfo_title, parse_list


class ComposeTitleTests(unittest.TestCase):
    def test_number_plus_title(self):
        self.assertEqual(compose_nfo_title("MIDA-727", "中文标题"), "MIDA-727 中文标题")

    def test_no_double_number(self):
        self.assertEqual(compose_nfo_title("MIDA-727", "MIDA-727 中文标题"), "MIDA-727 中文标题")
        self.assertEqual(compose_nfo_title("MIDA-727", "MIDA727 中文标题"), "MIDA-727 中文标题")
        self.assertEqual(compose_nfo_title("MIDA-727", "MIDA-727：中文"), "MIDA-727 中文")

    def test_empty_base(self):
        self.assertEqual(compose_nfo_title("MIDA-727", ""), "MIDA-727")
        self.assertEqual(compose_nfo_title("MIDA-727", None), "MIDA-727")

    def test_case_insensitive_prefix(self):
        self.assertEqual(compose_nfo_title("MIDA-727", "mida-727 标题"), "MIDA-727 标题")


class ParseListTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(parse_list(None), [])

    def test_list(self):
        self.assertEqual(parse_list(["a", 1]), ["a", "1"])

    def test_str_literal(self):
        self.assertEqual(parse_list("['巨乳', '中出']"), ["巨乳", "中出"])

    def test_plain_str(self):
        self.assertEqual(parse_list(" 单体作品 "), ["单体作品"])


class NfoBuilderTests(unittest.TestCase):
    META: ClassVar[dict] = {
        "number": "MIDA-727",
        "cid": "mida00727",
        "title": "日文原题",
        "release": "2026-07-31",
        "score": "9.00",
        "runtime": "120",
        "producer": "MOODYZ",
        "director": "某导演",
        "actresses": ["女优A", "女优B"],
        "genres": ["巨乳", "HD"],
        "trailer": "https://example/trailer",
    }

    def bytes_root(self, **kw):
        data = build_nfo_bytes("MIDA-727", self.META, kw.pop("plot", None), **kw)
        return ET.fromstring(data)

    def test_title_policy(self):
        root = self.bytes_root(title_info={"display_title": "中文标题"})
        self.assertEqual(root.findtext("title"), "MIDA-727 中文标题")
        self.assertEqual(root.findtext("originaltitle"), "日文原题")
        self.assertEqual(root.findtext("sorttitle"), "MIDA-727")

    def test_no_plot_when_none(self):
        root = self.bytes_root(plot=None)
        self.assertIsNone(root.findtext("plot"))
        self.assertIsNone(root.findtext("outline"))

    def test_plot_written(self):
        root = self.bytes_root(plot="剧情内容超过一点点")
        self.assertEqual(root.findtext("plot"), "剧情内容超过一点点")
        self.assertEqual(root.findtext("outline"), "剧情内容超过一点点")

    def test_actor_and_uniqueid(self):
        root = self.bytes_root()
        actors = root.findall("actor")
        self.assertEqual([a.findtext("name") for a in actors], ["女优A", "女优B"])
        self.assertEqual(actors[0].findtext("order"), "0")
        ids = {u.get("type"): u.text for u in root.findall("uniqueid")}
        self.assertEqual(ids.get("num"), "MIDA-727")
        self.assertEqual(ids.get("cid"), "mida00727")

    def test_actor_thumb(self):
        root = self.bytes_root(thumb_map={"女优A": "https://example/a.jpg"})
        actors = root.findall("actor")
        self.assertEqual(actors[0].findtext("thumb"), "https://example/a.jpg")
        self.assertIsNone(actors[1].findtext("thumb"))

    def test_studio_genre(self):
        root = self.bytes_root()
        self.assertEqual(root.findtext("studio"), "MOODYZ")
        self.assertEqual([g.text for g in root.findall("genre")], ["巨乳", "HD"])
        self.assertEqual([t.text for t in root.findall("tag")], ["巨乳", "HD"])


class NfoCliTests(unittest.TestCase):
    META: ClassVar[dict] = {"number": "ABC-001", "title": "日文原题", "release": "2026-01-01",
                            "actresses": ["女优A"], "genres": [" genre1 "]}

    def _write(self, dirpath, name, obj):
        p = Path(dirpath) / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_stdout_generation(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._write(td, "meta.json", self.META)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.cmd_nfo(type("A", (), {
                    "meta": meta, "number": None, "plot": None, "title_info": None,
                    "thumb_map": None, "out": None, "force": False, "stdout": True})())
            self.assertEqual(rc, 0)
            root = ET.fromstring(buf.getvalue())
            self.assertEqual(root.tag, "movie")
            self.assertEqual(root.findtext("title"), "ABC-001 日文原题")
            self.assertEqual(root.findtext("sorttitle"), "ABC-001")

    def test_write_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._write(td, "meta.json", self.META)
            out = str(Path(td) / "out.nfo")
            args_ok = {"meta": meta, "number": None, "plot": None, "title_info": None,
                       "thumb_map": None, "out": out, "force": False, "stdout": False}
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.cmd_nfo(type("A", (), args_ok)()), 0)
                data = Path(out).read_bytes()
                self.assertEqual(ET.fromstring(data).tag, "movie")
                # 已存在不覆盖（安全默认）
                self.assertEqual(cli.cmd_nfo(type("A", (), args_ok)()), 1)
                self.assertEqual(Path(out).read_bytes(), data)
                # --force 才允许覆盖
                args_force = dict(args_ok, force=True)
                self.assertEqual(cli.cmd_nfo(type("A", (), args_force)()), 0)

    def test_number_from_cli_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._write(td, "meta.json", self.META)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.cmd_nfo(type("A", (), {
                    "meta": meta, "number": "xyz-999", "plot": None, "title_info": None,
                    "thumb_map": None, "out": None, "force": False, "stdout": True})())
            self.assertEqual(rc, 0)
            root = ET.fromstring(buf.getvalue())
            self.assertEqual(root.findtext("sorttitle"), "XYZ-999")

    def test_meta_missing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.cmd_nfo(type("A", (), {
                "meta": "NO_SUCH_FILE.json", "number": None, "plot": None,
                "title_info": None, "thumb_map": None, "out": None,
                "force": False, "stdout": False})())
        self.assertEqual(rc, 1)
        self.assertIn("META_NOT_FOUND", buf.getvalue())

    def test_number_missing(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._write(td, "meta.json", {"title": "无番号"})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.cmd_nfo(type("A", (), {
                    "meta": meta, "number": None, "plot": None, "title_info": None,
                    "thumb_map": None, "out": None, "force": False, "stdout": True})())
        self.assertEqual(rc, 1)
        self.assertIn("NFO_NUMBER_MISSING", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

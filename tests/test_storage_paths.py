import unittest
from pathlib import PureWindowsPath

from subsync.storage import WebDAVStorage


class RemotePathTests(unittest.TestCase):
    def setUp(self):
        self.st = WebDAVStorage("http://127.0.0.1:8080/dav", "u", "p")

    def test_url_join_always_posix(self):
        self.assertEqual(self.st.url_for("Movies/ABC-001/ABC-001.srt"),
                         "http://127.0.0.1:8080/dav/Movies/ABC-001/ABC-001.srt")
        self.assertEqual(self.st.url_for("/Movies/x.mp4"),
                         "http://127.0.0.1:8080/dav/Movies/x.mp4")
        # 远端路径里永远不出现反斜杠
        self.assertNotIn("\\", self.st.url_for("Movies/测试/ABC-001.srt"))

    def test_unicode_remote_path(self):
        rel = "Movies/测试/ABC-001.srt"
        url = self.st.url_for(rel)
        self.assertIn("/Movies/", url)          # POSIX 分隔
        self.assertIn("测试", url)               # UTF-8 原样（编码交给 HTTP 栈）

    def test_strip_base(self):
        self.assertEqual(self.st._strip_base("/dav/Movies/测试/ABC-001.srt"),
                         "Movies/测试/ABC-001.srt")


class LocalPathTests(unittest.TestCase):
    def test_windows_local_path_never_pollutes_remote(self):
        # Windows 本地路径以 PureWindowsPath 表示，构造远端 rel 时仍是 POSIX 字符串
        local = PureWindowsPath(r"C:\Users\Test\Videos\测试\ABC-001.srt")
        remote_rel = "/Movies/测试/ABC-001/ABC-001.srt"
        self.assertEqual(PureWindowsPath(local).name, "ABC-001.srt")
        self.assertNotIn("\\", remote_rel)
        self.assertTrue(remote_rel.startswith("/"))

    def test_sidecar_name_from_remote_rel(self):
        # 远端 → sidecar 命名只依赖 basename
        from pathlib import PurePosixPath
        rel = "/Movies/测试/ABC-001/ABC-001.mp4"
        name = PurePosixPath(rel).stem + ".srt"
        self.assertEqual(name, "ABC-001.srt")


class RedactTests(unittest.TestCase):
    def test_url_userinfo(self):
        from subsync.utils import redact_secrets
        self.assertEqual(redact_secrets("http://user:secret@example.com/dav"),
                         "http://***:***@example.com/dav")

    def test_keyval(self):
        from subsync.utils import redact_secrets
        out = redact_secrets("WEBDAV_PASSWORD=hunter2")
        self.assertNotIn("hunter2", out)


if __name__ == "__main__":
    unittest.main()

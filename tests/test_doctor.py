import io
import unittest
from contextlib import redirect_stdout

from subsync import cli
from subsync.settings import reset_settings


class DoctorTests(unittest.TestCase):
    def test_unconfigured_is_friendly(self):
        reset_settings()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.cmd_doctor(type("A", (), {"debug": False}))
        out = buf.getvalue()
        self.assertIn("CONFIGURATION_REQUIRED", out)
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()

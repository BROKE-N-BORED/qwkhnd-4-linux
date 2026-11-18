"""Debug log layer tests (BNB T21 behaviour, adapted for Qwkhnd).

The fake secrets below are deliberate fixtures — key-shaped values
that prove the scrubber redacts them. They are not real credentials.
"""

import os
import sys
import tempfile
import unittest

from qwkhnd.debug_log import (
    DebugLogger, scrub_dict, scrub_text,
)

FAKE_KEY = "FAKE_KEY_1234567890abcdef"
FAKE_TOKEN = "ghp_FAKE00000000000000000000000000000000"


class ScrubTests(unittest.TestCase):
    def test_scrub_text_redacts_api_key(self):
        text = scrub_text("api_key=%s" % FAKE_KEY)
        self.assertNotIn(FAKE_KEY, text)
        self.assertIn("[REDACTED]", text)

    def test_scrub_text_redacts_bearer(self):
        text = scrub_text("Authorization: Bearer %s" % FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertIn("[REDACTED]", text)

    def test_scrub_text_redacts_github_token(self):
        text = scrub_text("token %s" % FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, text)

    def test_scrub_text_leaves_plain_text(self):
        text = scrub_text("the quick brown fox")
        self.assertEqual(text, "the quick brown fox")

    def test_scrub_dict_redacts_sensitive_keys(self):
        out = scrub_dict({"api_key": FAKE_KEY, "folder": "/tmp/x"})
        self.assertNotIn(FAKE_KEY, str(out))
        self.assertEqual(out["folder"], "/tmp/x")


class DebugLoggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = os.path.join(self.tmp.name, "logs")
        self.log = DebugLogger("qwkhnd", "0.1",
                               log_dir=self.log_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_file_created(self):
        self.log.info("hello")
        self.assertTrue(os.path.exists(
            os.path.join(self.log_dir, "qwkhnd.log")))

    def test_ring_buffer_keeps_last_200(self):
        for i in range(250):
            self.log.action("step %d" % i)
        records = list(self.log._ring.records)
        self.assertEqual(len(records), 200)
        self.assertIn("step 249", records[-1])
        self.assertFalse(any(r.endswith("step 0") for r in records))

    def test_exception_captures_traceback(self):
        try:
            raise ValueError("boom-test-value")
        except ValueError:
            self.log.exception("something broke")
        errors = list(self.log._errors.errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("boom-test-value", errors[0])
        self.assertIn("Traceback", errors[0])

    def test_report_scrubs_secrets(self):
        self.log.info("api_key=%s" % FAKE_KEY)
        self.log.set_setting("token", FAKE_TOKEN)
        path = self.log.generate_report()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertIn("qwkhnd 0.1", text)

    def test_report_includes_context(self):
        self.log.register_dependency("PySide6")
        path = self.log.generate_report()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("PySide6", text)
        self.assertIn("Python:", text)
        self.assertIn("RAM:", text)

    def test_report_omits_empty_services_section(self):
        # T21 (v0.4): no services registered, no Services
        # section — the old "(none registered)" line under it
        # is gone. (Settings still prints one when empty; only
        # Services was always empty in Qwkhnd.)
        path = self.log.generate_report()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("== Services ==", text)

    def test_report_keeps_services_section_when_registered(self):
        self.log.register_service("ollama", lambda: "up")
        path = self.log.generate_report()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("== Services ==", text)
        self.assertIn("ollama", text)

    def test_crash_handler_writes_a_report(self):
        # T26: calling the installed excepthook writes a report
        # file and still calls the previous hook.
        self.log.install_crash_handler()
        chained = []
        # Silence the real previous hook (it prints to stderr).
        self.log._previous_excepthook = lambda *args: chained.append(
            True)
        try:
            try:
                raise ValueError("boom for the crash test")
            except ValueError:
                exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)
        finally:
            self.log.uninstall_crash_handler()
        self.assertEqual(chained, [True])
        reports = [name for name in os.listdir(self.log_dir)
                   if name.startswith("debug-report-")]
        self.assertEqual(len(reports), 1)
        with open(os.path.join(self.log_dir, reports[0]),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("UNHANDLED EXCEPTION", text)
        self.assertIn("boom for the crash test", text)

    def test_two_reports_same_path_do_not_overwrite(self):
        # An explicit path makes the collision deterministic (two
        # timestamped calls could straddle a second boundary).
        path = os.path.join(self.log_dir, "debug-report-same.txt")
        first = self.log.generate_report(path)
        second = self.log.generate_report(path)
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.exists(first))
        self.assertTrue(os.path.exists(second))
        self.assertIn("-2", second)


if __name__ == "__main__":
    unittest.main()

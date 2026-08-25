import logging
import os
import tempfile
import unittest

from autoftbq_v2.infrastructure.app_logging import LOGGER_NAME, configure_logging


class V2AppLoggingTests(unittest.TestCase):
    def test_rotating_utf8_log_records_traceback(self):
        logger = logging.getLogger(LOGGER_NAME)
        old_handlers = list(logger.handlers)
        for handler in old_handlers:
            logger.removeHandler(handler)
        try:
            with tempfile.TemporaryDirectory() as root:
                configured, path = configure_logging(root)
                try:
                    raise ValueError("测试异常")
                except ValueError:
                    configured.exception("Agent failure")
                for handler in configured.handlers:
                    handler.flush()
                with open(path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                self.assertIn("Agent failure", content)
                self.assertIn("ValueError", content)
                self.assertIn("测试异常", content)
                for handler in list(configured.handlers):
                    handler.close()
                    configured.removeHandler(handler)
        finally:
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            for handler in old_handlers:
                logger.addHandler(handler)


if __name__ == "__main__":
    unittest.main()

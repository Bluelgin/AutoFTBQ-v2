#!/usr/bin/env python3
"""Launch AutoFTBQ Studio."""

import os
import sys

if "--smoke-test" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from autoftbq_v2.ux_polish import run_app, smoke_test_app


if __name__ == "__main__":
    raise SystemExit(smoke_test_app() if "--smoke-test" in sys.argv else run_app())

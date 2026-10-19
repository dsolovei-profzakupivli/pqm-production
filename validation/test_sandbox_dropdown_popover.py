import hashlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import sandbox_runtime


ROOT = Path(__file__).resolve().parents[1]
LIVE_INDEX_SHA256 = "f2c0abda242358eb33c133587185b2e27f021081aacdf8c3b3094c160daaa576"


class SandboxDropdownPopoverContractTests(unittest.TestCase):
    def test_protected_index_is_unchanged(self):
        self.assertEqual(
            hashlib.sha256((ROOT / "index.html").read_bytes()).hexdigest(),
            LIVE_INDEX_SHA256,
        )

    def test_script_is_injected_only_by_sandbox_decorator(self):
        raw = (ROOT / "index.html").read_bytes()
        with patch.dict(os.environ, {"PQM_SANDBOX": "1"}):
            sandbox = sandbox_runtime.decorate_html(raw).decode("utf-8")
        with patch.dict(os.environ, {}, clear=True):
            production = sandbox_runtime.decorate_html(raw).decode("utf-8")
        self.assertEqual(sandbox.count('<script src="registry_popovers.js"></script>'), 1)
        self.assertNotIn('<script src="registry_popovers.js"></script>', production)


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import sandbox_runtime


ROOT = Path(__file__).resolve().parents[1]
HALLOWEEN_CONTRACT = ROOT / "test_halloween_motion_contract.json"


def normalized_index_sha256():
    raw = (ROOT / "index.html").read_bytes()
    raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


class SandboxDropdownPopoverContractTests(unittest.TestCase):
    def test_protected_index_is_unchanged(self):
        contract = json.loads(HALLOWEEN_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["normalization"], "CRLF to LF for text only")
        self.assertEqual(
            normalized_index_sha256(),
            contract["files"]["index.html"],
        )

    def test_script_is_injected_only_by_sandbox_decorator(self):
        raw = (ROOT / "index.html").read_bytes()
        with patch.dict(os.environ, {"PQM_SANDBOX": "1"}):
            sandbox = sandbox_runtime.decorate_html(raw).decode("utf-8")
        with patch.dict(os.environ, {}, clear=True):
            production = sandbox_runtime.decorate_html(raw).decode("utf-8")
        self.assertEqual(sandbox.count('<script src="registry_popovers.js"></script>'), 1)
        self.assertNotIn('<script src="registry_popovers.js"></script>', production)
        include = '<script src="operational_task_officers.js?v=1"></script>'
        self.assertEqual(sandbox.count(include), 1)
        self.assertNotIn(include, production)


if __name__ == "__main__":
    unittest.main()

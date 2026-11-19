"""Additive source integrity pin for administrative unknown-run closure."""
import hashlib
import re
from pathlib import Path
import unittest


SELF_SHA256 = "60be85d244570924eb82a3ba996c16bd39d5445d094c412ed39fdb82914ea333"
SOURCE_SHA256 = {
    "auth_access.py": "a344da35bada1544a0b3af58f2cea542a0e7651d69fc80c1dc4939407b9799aa",
    "google_writer_execution.py": "088fa50c58feaf7cfae04ebf3748e6da56260071cb069ec475e3878065a82a7b",
    "google_writer_ui.js": "49864f96fbab0ea7119bd18c6df291b8ed3efa560ce128ac8db0b2ed92b30e7a",
    "server.py": "982a3e763b7547f507aecd8d617b9110ff03fe533b70cc0ccfcb06df1871c7af",
    "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs": "22b67b7234091cc7a611ad79911b15a1e0b98303d8fb204046c6d42091774f32",
    "test_google_writer_admin_close.py": "3edb22b1661c4f33133840daeee306d3a7056ce4a1e5fcf6357c1683c61ea322",
    "scripts/pqm-google-writer/mirror-alignment/admin-close-unknown.test.cjs": "f0f792cc99d5b37b07997e5a6826f9277136fd8d00d72547fc5cb05cecb962f2",
}
PRESERVED_SHA256 = {
    "validation/local_release_20261109/google_writer_all_scope_receipt_recovery_v1.json": "72c63161435081aec44f98a4605338bd9263afc9064614bce931caa3e43a0fa6",
    "validation/local_release_20261109/google_writer_manifest_compatibility_v2.json": "3b2af6306f75f93503332d214a636c87dcfc75ce0ca0497821d84441d701d494",
}


def root_path():
    here = Path(__file__).resolve()
    for root in (here.parent, *here.parents):
        if (root / "google_writer_execution.py").is_file():
            return root
    raise RuntimeError("Cannot locate admin-close integrity root")


def canonical(raw):
    return raw.replace(b"\r\n", b"\n")


def self_digest(raw):
    normalized = re.sub(rb'(?m)^SELF_SHA256 = "(?:<self-sha256>|[0-9a-f]{64})"$',
                        b'SELF_SHA256 = "<self-sha256>"', canonical(raw))
    return hashlib.sha256(normalized).hexdigest()


class GoogleWriterAdminCloseIntegrityTests(unittest.TestCase):
    def test_additive_sources_are_pinned_and_historical_manifests_unchanged(self):
        root = root_path()
        self.assertEqual(self_digest((root / Path(__file__).name).read_bytes()), SELF_SHA256)
        for relative, expected in SOURCE_SHA256.items():
            with self.subTest(source=relative):
                source = (root / relative if relative != "google_writer_ui.js" else
                          root / "validation/legacy_snapshots/google_writer_ui_admin_close_v1.js")
                self.assertEqual(hashlib.sha256(canonical(source.read_bytes())).hexdigest(), expected)
        for relative, expected in PRESERVED_SHA256.items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((root / relative).read_bytes())).hexdigest(), expected)

    def test_route_and_script_close_are_sandbox_bound_and_sheet_write_free(self):
        root = root_path()
        backend = canonical((root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        server = canonical((root / "server.py").read_bytes()).decode("utf-8")
        script = canonical((root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs").read_bytes()).decode("utf-8")
        close = backend[backend.index("def close_unknown_run("):backend.index("\ndef migrate(", backend.index("def close_unknown_run("))]
        script_close = script[script.index("function pqmSandboxCloseUnknownRun20261109_"):script.index("\nfunction ", script.index("function pqmSandboxCloseUnknownRun20261109_") + 10)]
        self.assertIn("if not SANDBOX_MODE", server)
        self.assertIn("permissions.get('admin.manage')", server)
        self.assertIn("permissions.get('google.writer.execute')", server)
        self.assertIn("finalize_admin_close_unknown", close)
        self.assertIn("client.invoke('close_unknown_run'", close)
        self.assertNotIn("SpreadsheetApp", script_close)
        self.assertNotIn("openById", script_close)
        self.assertIn("PQM_EXECUTION_CLOSED_", script_close)
        self.assertIn("PQM_EXECUTION_UNCERTAIN", script_close)


if __name__ == "__main__":
    unittest.main()

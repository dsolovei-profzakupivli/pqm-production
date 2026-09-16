import json
import tempfile
import unittest
from pathlib import Path

import historical_applications as historical


ROOT = Path(__file__).resolve().parent


class HistoricalApplicationManifestTests(unittest.TestCase):
    def tearDown(self):
        historical.manifest.cache_clear()

    def test_explicit_manifest_controls_read_only_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            submission_id = "a" * 32
            path.write_text(json.dumps({
                "version": 1,
                "applications": {
                    submission_id: {"source_system": "MedData", "source_row": 2},
                },
            }), encoding="utf-8")
            previous = historical.MANIFEST_PATH
            try:
                historical.MANIFEST_PATH = path
                historical.manifest.cache_clear()
                self.assertTrue(historical.is_read_only(submission_id))
                self.assertFalse(historical.is_read_only("b" * 32))
                self.assertEqual(historical.provenance(submission_id)["source_row"], 2)
                with self.assertRaises(historical.HistoricalApplicationReadOnlyError):
                    historical.assert_editable(submission_id)
                historical.assert_editable("b" * 32)
            finally:
                historical.MANIFEST_PATH = previous

    def test_current_manifest_is_complete_and_explicit(self):
        payload = json.loads((ROOT / "metadata" / "meddata_historical_applications.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["source"]["row_count"], 53803)
        self.assertEqual(len(payload["applications"]), 53803)
        self.assertEqual(len(set(payload["applications"])), 53803)
        self.assertEqual(
            payload["source"]["sha256"],
            "316f86077660ce53a1fc9c338ee586cc0867779b53b099db0bf4beb41b93499f",
        )


class HistoricalApplicationGuardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (ROOT / "server.py").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_backend_guards_every_application_write_path(self):
        self.assertIn("historical_applications.assert_editable(submission_id)", self.server)
        self.assertGreaterEqual(self.server.count("historical_applications.assert_editable("), 5)
        self.assertIn("any(historical_applications.is_read_only(submission_id) for submission_id in ids)", self.server)
        self.assertIn('"historical_read_only": True}, 409', self.server)
        self.assertIn('item["historical_read_only"] = bool(meddata)', self.server)

    def test_frontend_disables_historical_edits_and_bulk_selection(self):
        self.assertIn("Boolean(row.historicalReadOnly)||role()==='viewer'", self.app)
        self.assertIn("else selected.add(r.id)", self.app)
        self.assertIn("row=>selected.has(row.id)&&row.historicalReadOnly", self.app)
        self.assertIn("можна передавати в Chat, але не змінювати масово", self.app)
        self.assertIn("r.historicalReadOnly?'historical-read-only'", self.app)
        self.assertIn("historicalReadOnly||Boolean(c.nazk_certificate_checked)", self.app)
        self.assertIn("Історичну заявку можна вибрати для перегляду або Chat", self.app)
        self.assertIn("applicationNazkMarker(row)", self.app)
        marker = self.app.split("function applicationNazkMarker(row){", 1)[1].split("\nfunction cell(", 1)[0]
        self.assertNotIn("НАЗК · Не актуально", marker)
        self.assertIn("row.historicalReadOnly||rejected", marker)


if __name__ == "__main__":
    unittest.main()

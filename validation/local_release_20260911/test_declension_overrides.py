import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from declension import OverrideStore, decline_name
from declension_overrides import (OverrideConflictError, delete_override,
                                  ensure_pending_overrides, list_overrides, save_override)
import server
import declension
import declension_overrides


class DeclensionOverrideRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "declension_overrides.csv"

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **changes):
        value = dict(entity_type="legal_entity", original="ДЕРЖАВНА УСТАНОВА «ТЕСТ»",
                     genitive="ДЕРЖАВНОЇ УСТАНОВИ «ТЕСТ»", dative="", accusative="",
                     comment="перевірено")
        value.update(changes)
        return value

    def test_sandbox_seed_once_survives_deploy_and_reopens_for_generation(self):
        data = Path(self.temp.name)
        bootstrap = data / "bootstrap.csv"
        persistent = data / "declension_overrides.csv"
        bootstrap.write_text("entity_type;original;genitive;dative;accusative;comment\n", encoding="utf-8")
        with patch.object(declension, "SANDBOX_OVERRIDES", True), \
                patch.object(declension, "BOOTSTRAP_OVERRIDES_PATH", bootstrap), \
                patch.object(declension, "DEFAULT_OVERRIDES_PATH", persistent), \
                patch.object(declension_overrides, "DEFAULT_OVERRIDES_PATH", persistent), \
                patch("sandbox_runtime.validate_environment", return_value=(data, data / "pqm_sandbox.sqlite3", "fixture")):
            self.assertEqual(list_overrides(persistent), [])
            saved = save_override(self.payload(accusative="ДЕРЖАВНУ УСТАНОВУ «ТЕСТ»"), path=persistent)
            bootstrap.write_text("entity_type;original;genitive;dative;accusative;comment\n"
                                 "person;ДРУГА ОСОБА;інше;;інше;новий deploy\n", encoding="utf-8")
            declension.ensure_default_overrides()
            reopened = list_overrides(persistent)
            self.assertEqual(len(reopened), 1)
            self.assertEqual(reopened[0]["id"], saved["id"])
            self.assertEqual(reopened[0]["accusative"], "ДЕРЖАВНУ УСТАНОВУ «ТЕСТ»")
            self.assertEqual(OverrideStore(persistent).form(self.payload()["original"],
                                                       "legal_entity", "genitive"),
                             "ДЕРЖАВНОЇ УСТАНОВИ «ТЕСТ»")
            generated = decline_name(self.payload()["original"], "legal_entity",
                                     "accusative", OverrideStore(persistent))
            self.assertEqual(generated.value, "ДЕРЖАВНУ УСТАНОВУ «ТЕСТ»")
            self.assertEqual(save_override(self.payload(comment="редаговано"), saved["id"], persistent)["comment"], "редаговано")

    def test_sandbox_storage_attestation_failure_does_not_seed_or_write(self):
        persistent = Path(self.temp.name) / "declension_overrides.csv"
        with patch.object(declension, "SANDBOX_OVERRIDES", True), \
                patch.object(declension, "DEFAULT_OVERRIDES_PATH", persistent), \
                patch.object(declension_overrides, "DEFAULT_OVERRIDES_PATH", persistent), \
                patch("sandbox_runtime.validate_environment", side_effect=RuntimeError("wrong target")):
            with self.assertRaisesRegex(RuntimeError, "wrong target"):
                save_override(self.payload(), path=persistent)
        self.assertFalse(persistent.exists())

    def test_prod_legacy_csv_migrates_once_and_survives_release_seed(self):
        data = Path(self.temp.name)
        legacy = data / "legacy.csv"
        persistent = data / "declension_overrides.csv"
        legacy_bytes = ("entity_type;original;genitive;dative;accusative;comment\n"
                        "person;ТЕСТОВА ОСОБА;ТЕСТОВОЇ ОСОБИ;;ТЕСТОВУ ОСОБУ;чинний PROD запис\n").encode("utf-8")
        legacy.write_bytes(legacy_bytes)
        with patch.object(declension, "PROD_OVERRIDES", True), \
                patch.object(declension, "SANDBOX_OVERRIDES", False), \
                patch.object(declension, "BOOTSTRAP_OVERRIDES_PATH", legacy), \
                patch.object(declension, "DEFAULT_OVERRIDES_PATH", persistent), \
                patch.object(declension_overrides, "DEFAULT_OVERRIDES_PATH", persistent), \
                patch.dict("os.environ", {"PQM_DATA_DIR": str(data)}):
            declension.ensure_default_overrides()
            self.assertEqual(persistent.read_bytes(), legacy_bytes)
            row = list_overrides(persistent)[0]
            self.assertEqual(row["genitive"], "ТЕСТОВОЇ ОСОБИ")
            saved = save_override({**row, "dative": "ТЕСТОВІЙ ОСОБІ"}, row["id"], persistent)
            before_restart = persistent.read_bytes()
            legacy.write_text("entity_type;original;genitive;dative;accusative;comment\n",
                              encoding="utf-8")
            declension.ensure_default_overrides()
            self.assertEqual(persistent.read_bytes(), before_restart)
            self.assertEqual(list_overrides(persistent)[0]["dative"], saved["dative"])
            store = OverrideStore(persistent)
            self.assertEqual(decline_name("ТЕСТОВА ОСОБА", "person", "dative", store).value,
                             "ТЕСТОВІЙ ОСОБІ")

    def test_create_list_edit_delete_and_bom(self):
        created = save_override(self.payload(), path=self.path)
        self.assertEqual(self.path.read_bytes()[:3], b"\xef\xbb\xbf")
        self.assertIn(b";", self.path.read_bytes())
        self.assertEqual(list_overrides(self.path)[0]["genitive"], "ДЕРЖАВНОЇ УСТАНОВИ «ТЕСТ»")
        edited = save_override(self.payload(comment="оновлено"), created["id"], self.path)
        self.assertEqual(edited["comment"], "оновлено")
        delete_override(edited["id"], self.path)
        self.assertEqual(list_overrides(self.path), [])

    def test_duplicate_uses_same_normalization_as_lookup(self):
        save_override(self.payload(), path=self.path)
        with self.assertRaises(OverrideConflictError):
            save_override(self.payload(original='  ДЕРЖАВНА   УСТАНОВА "ТЕСТ"  '), path=self.path)

    def test_failed_atomic_replace_preserves_existing_csv(self):
        save_override(self.payload(), path=self.path)
        before = self.path.read_bytes()
        with patch("declension_overrides.os.replace", side_effect=OSError("fault")):
            with self.assertRaises(OSError):
                save_override(self.payload(original="ІНШИЙ ЗАПИС"), path=self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_atomic_replace_retries_transient_windows_permission_error(self):
        save_override(self.payload(), path=self.path)
        real_replace = __import__("os").replace
        attempts = []
        def flaky(source, destination):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError(5, "temporarily locked")
            return real_replace(source, destination)
        with patch("declension_overrides.os.replace", side_effect=flaky), \
                patch("declension_overrides.time.sleep"):
            save_override(self.payload(comment="після retry"),
                          list_overrides(self.path)[0]["id"], self.path)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(list_overrides(self.path)[0]["comment"], "після retry")

    def test_locked_target_fallback_updates_complete_csv_after_replace_denied(self):
        save_override(self.payload(), path=self.path)
        with patch("declension_overrides.os.replace", side_effect=PermissionError(5, "locked")), \
                patch("declension_overrides.time.sleep"):
            save_override(self.payload(comment="fallback complete"),
                          list_overrides(self.path)[0]["id"], self.path)
        self.assertEqual(list_overrides(self.path)[0]["comment"], "fallback complete")
        self.assertEqual(self.path.read_bytes()[:3], b"\xef\xbb\xbf")
        self.assertIn(b";", self.path.read_bytes())

    def test_unresolved_entries_are_auto_added_merged_and_become_ready(self):
        items = [
            {"entity_type": "legal_entity", "original": "Військова частина А0528",
             "grammatical_case": "genitive"},
            {"entity_type": "legal_entity", "original": '  Військова   частина А0528 ',
             "grammatical_case": "accusative"},
        ]
        rows = ensure_pending_overrides(items, self.path)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["needs_completion"])
        self.assertEqual(rows[0]["required_cases"], ["accusative", "genitive"])
        self.assertEqual(self.path.read_bytes()[:3], b"\xef\xbb\xbf")
        self.assertIn(b";", self.path.read_bytes())
        ensure_pending_overrides(items, self.path)
        self.assertEqual(len(list_overrides(self.path)), 1)
        ready = save_override({**rows[0], "genitive": "Військової частини А0528",
                               "accusative": "Військову частину А0528"}, rows[0]["id"], self.path)
        self.assertFalse(ready["needs_completion"])
        self.assertEqual(ready["comment"], "")

    def test_pending_does_not_overwrite_existing_verified_override(self):
        created = save_override(self.payload(), path=self.path)
        before = self.path.read_bytes()
        ensure_pending_overrides([{"entity_type": "legal_entity",
                                   "original": self.payload()["original"],
                                   "grammatical_case": "accusative"}], self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list_overrides(self.path)[0]["id"], created["id"])

    def test_override_store_reloads_after_ui_style_save(self):
        store = OverrideStore(self.path)
        self.assertEqual(decline_name("НАЗВА", "other", "dative", store).status, "unresolved")
        save_override(self.payload(entity_type="other", original="НАЗВА", genitive="",
                                   dative="НАЗВІ", comment=""), path=self.path)
        result = decline_name("НАЗВА", "other", "dative", store)
        self.assertEqual((result.status, result.source, result.value), ("resolved", "override", "НАЗВІ"))


class DeclensionValidationContractTests(unittest.TestCase):
    def test_multiple_unresolved_forms_are_structured_once(self):
        names = {
            "customer_name_genitive": decline_name("ДЕРЖАВНА УСТАНОВА «ТЕСТ»", "legal_entity", "genitive",
                                                     OverrideStore(Path(self.temp_path()))),
            "customer_name_accusative": decline_name("ДЕРЖАВНА УСТАНОВА «ТЕСТ»", "legal_entity", "accusative",
                                                       OverrideStore(Path(self.temp_path()))),
        }
        items = server.unresolved_declension_items(names.keys(), names, {
            "id": "internal-report-id", "report_id": "UA-D-TEST",
            "author_code": "CUSTOMER-1", "defendant_code": "SUPPLIER-1",
        })
        error = server.DeclensionValidationError(items)
        payload = error.payload()
        self.assertEqual(payload["code"], "declension_unresolved")
        self.assertEqual(payload["status"], 422)
        self.assertEqual({item["grammatical_case"] for item in payload["unresolved"]},
                         {"genitive", "accusative"})
        self.assertEqual({item["subject_type"] for item in payload["unresolved"]}, {"customer"})
        self.assertEqual({item["subject_label"] for item in payload["unresolved"]}, {"Замовник"})
        self.assertEqual({item["entity_identifier"] for item in payload["unresolved"]}, {"CUSTOMER-1"})
        self.assertEqual({item["report_id"] for item in payload["unresolved"]}, {"UA-D-TEST"})

    def test_supplier_unresolved_payload_carries_case_return_context(self):
        unresolved = decline_name("ПОСТАЧАЛЬНИК", "other", "dative",
                                  OverrideStore(Path(self.temp_path())))
        items = server.unresolved_declension_items(["supplier_name_dative"],
            {"supplier_name_dative": unresolved}, {
                "report_id": "UA-D-SUPPLIER", "author_code": "CUSTOMER-1",
                "defendant_code": "SUPPLIER-1",
            })
        self.assertEqual(items[0]["subject_type"], "supplier")
        self.assertEqual(items[0]["subject_label"], "Постачальник")
        self.assertEqual(items[0]["entity_identifier"], "SUPPLIER-1")
        self.assertEqual(items[0]["report_id"], "UA-D-SUPPLIER")

    @staticmethod
    def temp_path():
        return str(Path(tempfile.gettempdir()) / "pqm-no-declension-overrides.csv")

    def test_unused_unresolved_form_does_not_enter_validation(self):
        unresolved = decline_name("ПОСТАЧАЛЬНИК", "other", "dative",
                                  OverrideStore(Path(self.temp_path())))
        items = server.unresolved_declension_items([], {"supplier_name_dative": unresolved})
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()

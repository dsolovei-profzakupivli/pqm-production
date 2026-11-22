import io
import json
import urllib.parse
import unittest
from unittest.mock import patch

import server


class ProductionEdrGoogleNazkReconcileTests(unittest.TestCase):
    def test_grid_reader_uses_display_timestamp_and_keeps_empty_cells(self):
        body = {"properties": {"timeZone": "Europe/Kiev"}, "sheets": [{
            "properties": {"title": "ЮО"}, "data": [{"startRow": 0, "startColumn": 0,
                "rowData": [
                    {"values": [{"formattedValue": "h"} for _ in range(15)]},
                    {"values": [
                        {"formattedValue": ""}, {"formattedValue": "0038261938"},
                        {"formattedValue": ""}, {"formattedValue": "Manager"},
                        {"formattedValue": ""}, {"formattedValue": ""},
                        {"formattedValue": ""}, {"formattedValue": ""},
                        {"formattedValue": "29.10.2026 14:27:49"},
                        {"formattedValue": ""}, {"formattedValue": ""},
                        {"formattedValue": ""}, {"formattedValue": ""},
                        {"formattedValue": ""}, {"formattedValue": ""},
                    ]},
                    {"values": [{"formattedValue": ""} for _ in range(15)]},
                ]}]}]}
        with patch.object(server, "google_edr_effective_enabled", return_value=True), \
             patch.object(server, "_google_access_token", return_value="synthetic"), \
             patch.object(server.urllib.request, "urlopen",
                          return_value=io.BytesIO(json.dumps(body).encode("utf-8"))) as opened:
            rows = server._google_edr_sheet_values("ЮО")
        request = opened.call_args.args[0]
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)["ranges"],
                         ["'ЮО'!A:O"])
        self.assertEqual(rows[1][1], "0038261938")
        self.assertEqual(rows[1][8], "29.10.2026 14:27:49")
        self.assertEqual(rows[1][6], "")
        self.assertEqual(rows[2][6], "")

    def test_manager_reconcile_is_supplier_scoped_and_uses_persisted_data_only(self):
        con = object()
        calls = []
        active = {"38261938": ["application-1"]}
        with patch.object(server.operational_tasks, "reconcile_irrelevant_nazk_managers",
                          return_value={"cancelled": 1}) as old_manager, \
             patch.object(server.operational_tasks, "_active_application_map", return_value=active), \
             patch.object(server.operational_tasks, "reconcile_stale_nazk_tasks",
                          return_value={"cancelled": 0}) as stale, \
             patch.object(server, "reconcile_active_supplier_nazk",
                          return_value={"items": [{"created": False}]}) as checks, \
             patch.object(server.operational_tasks, "materialize_nazk_tasks",
                          return_value={"created": 0, "existing": 1}) as materialize:
            result = server.reconcile_supplier_nazk_after_edr_manager_change(con, "38261938")
        old_manager.assert_called_once()
        stale.assert_called_once()
        checks.assert_called_once_with(con, apply=True, supplier_codes=["38261938"])
        materialize.assert_called_once()
        self.assertEqual(result["cancelled_old_manager"], 1)
        self.assertEqual(result["tasks_existing"], 1)

    def test_no_active_qualifications_cancels_stale_tasks_without_rechecking_registry(self):
        con = object()
        with patch.object(server.operational_tasks, "reconcile_irrelevant_nazk_managers",
                          return_value={"cancelled": 1}), \
             patch.object(server.operational_tasks, "_active_application_map", return_value={}), \
             patch.object(server.operational_tasks, "reconcile_stale_nazk_tasks",
                          return_value={"cancelled": 1}) as stale, \
             patch.object(server, "reconcile_active_supplier_nazk") as checks, \
             patch.object(server.operational_tasks, "materialize_nazk_tasks") as materialize:
            result = server.reconcile_supplier_nazk_after_edr_manager_change(con, "38261938")
        stale.assert_called_once_with(con, actor="PQM confirmed EDR manager change",
                                      supplier_codes=["38261938"],
                                      active_applications={"38261938": []})
        checks.assert_not_called()
        materialize.assert_not_called()
        self.assertEqual(result["skipped"], "no_effective_active_qualifications")


if __name__ == "__main__":
    unittest.main(verbosity=2)

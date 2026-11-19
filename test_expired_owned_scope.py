"""Owned administrator scope shared by list and badge; no live reports."""
from contextlib import closing
from datetime import datetime
import unittest
from unittest.mock import patch
import test_ui_improvements as fixture
import server


class ExpiredOwnedScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.UiImprovementsTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def test_other_authorities_and_name_only_matches_are_excluded(self):
        with closing(server.db()) as con:
            with con:
                for i,code in enumerate(['42574629','other','']):
                    con.execute("INSERT INTO violation_reports(id,report_id,status,defendant_period_end,authority_code,authority_name,raw_json,synced_at) VALUES(?,?,'pending','2026-10-15',?,'Професійні закупівлі','{}','fixture')",('foreign'+str(i),'foreign'+str(i),code))
        self.assertEqual(self.fixture.count(),1)
        with patch.object(server,'datetime',wraps=datetime) as clock:
            clock.now.return_value=self.fixture.moment
            self.assertEqual([r['id'] for r in server.list_violation_reports({'response_expired':['1']})['items']],['0'])
        with closing(server.db()) as con:before=list(con.iterdump())
        for _ in range(2):self.assertEqual(self.fixture.count(),1)
        with closing(server.db()) as con:self.assertEqual(before,list(con.iterdump()))

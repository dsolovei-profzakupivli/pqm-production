"""No external calls or production writes: real importer against in-memory fixtures."""
import sqlite3
import unittest
from unittest.mock import patch
import server
import edr_sync_v2


class SupplierEdrDateTests(unittest.TestCase):
    def sheet(self,header='Дата перевірки',date='03.09.2026'):
        headers=list(edr_sync_v2.HEADERS)
        values=['']*len(headers)
        for key,value in {'Код ЄДРПОУ':'30067771','ПІБ для перевірки':'ТКАЧ ОЛЕКСАНДР ВАСИЛЬОВИЧ',
                          'Дата перевірки':date,'УО':'Тестова УО'}.items(): values[headers.index(key)]=value
        if header!='Дата перевірки': headers[headers.index('Дата перевірки')]=header
        return [headers,values]

    def test_current_and_legacy_source_headers(self):
        for header in ('Дата перевірки','Дата перевірки ЄДР'):
            with patch.object(server,'_google_sheet_values',return_value=self.sheet(header)):
                self.assertEqual(server._supplier_edr_rows('ЮО','unused')[0]['edr_checked_at'],'03.09.2026')

    def test_missing_source_date_never_becomes_import_time(self):
        for sheet in (self.sheet(date=''),[['Код ЄДРПОУ'],['30067771']]):
            with patch.object(server,'_google_sheet_values',return_value=sheet):
                self.assertEqual(server._supplier_edr_rows('ЮО','unused')[0]['edr_checked_at'],'')

    def test_current_header_priority(self):
        sheet=self.sheet();sheet[0].append('Дата перевірки ЄДР');sheet[1].append('17.08.2026')
        with patch.object(server,'_google_sheet_values',return_value=sheet):
            self.assertEqual(server._supplier_edr_rows('ЮО','unused')[0]['edr_checked_at'],'03.09.2026')

    def test_import_and_repeat_keep_verification_date_separate(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        source=sqlite3.connect('file:data/pqm.sqlite3?mode=ro',uri=True)
        try:
            for name in ('supplier_edr_profiles','supplier_managers','supplier_edr_sync_log'):
                con.execute(source.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',name)).fetchone()[0])
        finally:source.close()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,edr_checked_at,synced_at) VALUES('30067771','17.08.2026','2026-08-21T00:00:00+00:00')")
        server.sync_current_supplier_manager(con,'30067771','ТКАЧ ОЛЕКСАНДР ВАСИЛЬОВИЧ','Google Sheets: ЮО','2026-08-21T00:00:00+00:00')
        con.commit()
        cases=[('03.09.2026','2026-09-09T19:58:11+00:00','2026-09-09T19:58:11+00:00'),
               ('03.09.2026','2026-09-10T10:00:00+00:00','2026-09-09T19:58:11+00:00'),
               ('05.09.2026','2026-09-11T10:00:00+00:00','2026-09-11T10:00:00+00:00')]
        for date,stamp,expected_synced_at in cases:
            source_sheet=self.sheet(date=date)
            sheet_read=lambda name: source_sheet if name=='ЮО' else [list(edr_sync_v2.HEADERS)]
            with patch.object(server,'db',return_value=con),patch.object(server,'_google_sheet_values',side_effect=sheet_read),patch.object(server,'SUPPLIER_EDR_SHEETS',{'ФОП':'unused','ЮО':'unused'}),patch.object(server,'now_iso',return_value=stamp),patch.object(server,'SUPPLIER_EDR_SYNC_STATE',{}),patch.object(server,'refresh_current_submission_nazk_controls') as refresh:
                fingerprint=server.supplier_edr_source_snapshot()['source_fingerprint']
                server.supplier_edr_sync_worker(fingerprint,'test')
                self.assertEqual(server.SUPPLIER_EDR_SYNC_STATE['last_result'],'completed')
                row=con.execute('SELECT edr_checked_at,synced_at FROM supplier_edr_profiles').fetchone()
                self.assertEqual(tuple(row),(edr_sync_v2.normalized_date(date),expected_synced_at))
                self.assertEqual(con.execute('SELECT updated_at FROM supplier_managers').fetchone()[0],'2026-08-21T00:00:00+00:00')
                refresh.assert_not_called()


if __name__=='__main__':unittest.main()

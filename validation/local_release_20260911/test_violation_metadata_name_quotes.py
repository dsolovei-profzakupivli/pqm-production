"""Normalize entity-name substitutions in generated protocol metadata only."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server,document_metadata

class ViolationMetadataNameQuotesTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.patch=patch.object(server,'DB_PATH',Path(self.temp.name)/'synthetic.sqlite3');self.patch.start();server.init_db()
 def tearDown(self):self.patch.stop();self.temp.cleanup()
 def item(self):return {'tender_pretty_id':'UA-2026-10-06-006715-a','review':{'customer_verified_short_name':'КНП "ОКОЦ КОР"'}}
 def values(self):return {'report_id':'UA-D-2026-10-21-000001','supplier_code':'00447853','supplier_short_name':'ПРАТ "ЮРІЯ"','supplier_name':'ПРИВАТНЕ АКЦІОНЕРНЕ ТОВАРИСТВО "ЮРІЯ"'}
 def topic(self,item=None,values=None):return server._resolve_violation_protocol_metadata(item or self.item(),values or self.values())['protocol_subject']['value']
 def test_actual_topic_template_normalizes_both_entity_names(self):
  self.assertEqual(self.topic(),'Розгляд звернення UA-D-2026-10-21-000001 по закупівлі UA-2026-10-06-006715-a КНП «ОКОЦ КОР» (на ПРАТ «ЮРІЯ»; 00447853)')
 def test_sources_and_persisted_template_are_not_rewritten(self):
  item=self.item();values=self.values();before=copy.deepcopy((item,values))
  with server.db() as con:templates=con.execute('SELECT * FROM document_metadata_templates').fetchall();events=con.execute('SELECT * FROM document_metadata_template_events').fetchall()
  self.topic(item,values);self.assertEqual((item,values),before)
  with server.db() as con:self.assertEqual(con.execute('SELECT * FROM document_metadata_templates').fetchall(),templates);self.assertEqual(con.execute('SELECT * FROM document_metadata_template_events').fetchall(),events)
 def test_existing_guillemets_and_apostrophes_preserved(self):
  item=self.item();item['review']['customer_verified_short_name']='КНП «ОКОЦ КОР»';values=self.values();values['supplier_short_name']='ТОВ «М’ЯТА»';self.assertIn('КНП «ОКОЦ КОР» (на ТОВ «М’ЯТА»;',self.topic(item,values))
 def test_missing_short_supplier_uses_normalized_full_name(self):
  values=self.values();values['supplier_short_name']='';self.assertIn('ПРИВАТНЕ АКЦІОНЕРНЕ ТОВАРИСТВО «ЮРІЯ»',self.topic(values=values))
 def test_unpaired_quotes_and_non_name_fields_not_globally_replaced(self):
  item=self.item();item['review']['customer_verified_short_name']='КНП "НЕПАРНА';values=self.values();values['report_id']='ID"810"';values['supplier_code']='00"44"'
  with server.db() as con:con.execute('UPDATE document_metadata_templates SET template_text=? WHERE document_type=? AND metadata_key=?',('"Довільна цитата" {{report_id}} {{customer.short_name}} {{supplier.short_name}} {{supplier.code}}',document_metadata.VIOLATION_REVIEW_PROTOCOL,'protocol_subject'))
  topic=self.topic(item,values);self.assertIn('"Довільна цитата"',topic);self.assertIn('ID"810"',topic);self.assertIn('00"44"',topic);self.assertIn('КНП "НЕПАРНА',topic);self.assertIn('ПРАТ «ЮРІЯ»',topic)

if __name__=='__main__':unittest.main(verbosity=2)

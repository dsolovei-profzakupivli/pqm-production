"""Execute the actual parser and actual status expressions without DB/services."""
import ast,re,unittest
from datetime import datetime,timedelta
from pathlib import Path
source=ast.parse(Path('server.py').read_text(encoding='utf-8-sig'))
ns={'re':re,'datetime':datetime}
names={'analyze_mvs_extract','parse_ukrainian_date','normalized_value'}
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'server.py','exec'),ns)
def check(result,key):
 for node in ast.walk(source):
  if isinstance(node,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='key' and isinstance(v,ast.Constant) and v.value==key for k,v in zip(node.keys,node.values)):
   status=next(v for k,v in zip(node.keys,node.values) if isinstance(k,ast.Constant) and k.value=='status')
   return eval(compile(ast.Expression(status),'server.py','eval'),{'mvs_extract':result})
 raise AssertionError(key)
def parse(text):return ns['analyze_mvs_extract'](text,'','2026-11-23T10:00:00Z')
class MvsParameters(unittest.TestCase):
 def test_calendar_boundaries(self):
  for days in [0,29,30,31]:
   with self.subTest(days=days):
    date=(datetime(2026,11,23)-timedelta(days=days)).strftime('%d.%m.%Y');result=parse('ПОВНИЙ\nСТАНОМ НА '+date)
    self.assertEqual(result['age_days'],days);self.assertEqual(check(result,'mvs_age'),'ok' if days<=30 else 'error')
 def test_unknown_or_invalid_dates_warn(self):
  for text in ['ПОВНИЙ','ПОВНИЙ\nСТАНОМ НА 31.02.2026','ПОВНИЙ\nСТАНОМ НА 24.11.2026']:
   with self.subTest(text=text):self.assertEqual(check(parse(text),'mvs_age'),'warning')
 def test_types(self):
  for value,status in [('ПОВНИЙ','ok'),('СКОРОЧЕНИЙ','error'),('Тип витягу: ІНФОРМАЦІЙНИЙ','error'),('','warning')]:
   with self.subTest(value=value):self.assertEqual(check(parse(value),'mvs_extract_type'),status)
 def test_each_statement_independently(self):
  labels={'criminal_liability':'ВІДОМОСТІ ПРО ПРИТЯГНЕННЯ ДО КРИМІНАЛЬНОЇ ВІДПОВІДАЛЬНОСТІ','unspent_conviction':'ВІДОМОСТІ ПРО НАЯВНІСТЬ НЕЗНЯТОЇ ЧИ НЕПОГАШЕНОЇ СУДИМОСТІ','wanted_status':'ВІДОМОСТІ ПРО РОЗШУК'}
  for key,label in labels.items():
   for value,expected in [('ВІДСУТНІ','ok'),('Наявні відомості','error'),('НЕ ВІДСУТНІ','error'),('','warning')]:
    with self.subTest(key=key,value=value):
     statement=parse(label+': '+value)[key]
     self.assertEqual('ok' if statement['absent'] else 'error' if statement['found'] else 'warning',expected)
     if value:self.assertEqual(statement['value'],value)
 def test_missing_value_does_not_consume_next_field(self):
  result=parse('ВІДОМОСТІ ПРО РОЗШУК:\nВІДОМОСТІ ПРО ПРИТЯГНЕННЯ ДО КРИМІНАЛЬНОЇ ВІДПОВІДАЛЬНОСТІ: ВІДСУТНІ')
  self.assertFalse(result['wanted_status']['found'])
 def test_value_on_following_line(self):
  result=parse('ВІДОМОСТІ ПРО РОЗШУК\nВІДСУТНІ');self.assertTrue(result['wanted_status']['absent'])
if __name__=='__main__':unittest.main()

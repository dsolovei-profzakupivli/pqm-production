"""Layout contracts supplement real Chromium measurements, not replace them."""
from html.parser import HTMLParser
from pathlib import Path
import unittest


class ConsolidatedUiContractTests(unittest.TestCase):
    def test_history_filters_have_original_two_groups_and_valid_decisions(self):
        class Controls(HTMLParser):
            def __init__(self):
                super().__init__();self.row=None;self.row_depth=0;self.groups={};self.options=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='div' and 'history-filter-row' in attrs.get('class',''):
                    self.row=attrs['class'].split()[-1];self.row_depth=1;self.groups[self.row]=[]
                elif tag=='div' and self.row:
                    self.row_depth+=1
                if self.row and attrs.get('data-history'):
                    self.groups[self.row].append(attrs['data-history'])
                if tag=='option' and self.row=='history-filter-secondary':self.options.append(attrs.get('value'))
            def handle_endtag(self,tag):
                if tag=='div' and self.row:
                    self.row_depth-=1
                    if self.row_depth==0:self.row=None
        root=Path(__file__).parent;parser=Controls();parser.feed((root/'index.html').read_text(encoding='utf-8'))
        self.assertEqual(parser.groups['history-filter-primary'],['search','code','supplier','cpv','framework','contract','manager'])
        self.assertEqual(parser.groups['history-filter-secondary'],['remarks','officer','from','to','status'])
        self.assertEqual(parser.options,['','pending','active','unsuccessful'])
        html=(root/'index.html').read_text(encoding='utf-8')
        self.assertIn('id="historyReviewOfficerFilter"',html)
        self.assertIn('id="historyReviewOfficerSearch"',html)
        self.assertIn('id="historyReset" class="pqm-filter-reset"',html)

    def test_dynamic_officers_and_existing_personal_group_only(self):
        root=Path(__file__).parent;js=(root/'app.js').read_text(encoding='utf-8')
        self.assertNotIn('officerKpiItems',js)
        self.assertNotIn('data-officer-kpi',js)
        css=(root/'ui_improvements.css').read_text(encoding='utf-8')
        self.assertIn('#workQueueView .qualification-summary-officer{flex:0 0 auto;',css)
        self.assertNotIn('#workQueueView .qualification-summary-officer{height:',css)
        self.assertIn('#historyFilters .history-filter-secondary{grid-template-columns:minmax(200px,1.7fr) minmax(145px,1fr) minmax(145px,1fr) minmax(118px,.8fr) minmax(118px,.8fr) minmax(150px,1fr) 38px}',css)
        self.assertIn('@media(max-width:760px){#historyFilters .history-filter-primary,#historyFilters .history-filter-secondary{grid-template-columns:repeat(2,minmax(0,1fr))}',css)
        self.assertIn('#historyFilters .history-filter-secondary>.pqm-clear-wrap:has(>input[data-history="remarks"]){grid-column:1/-1}',css)

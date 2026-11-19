"""Seasonal UI policy: deterministic clocks only, no runtime/network writes."""
from pathlib import Path
import subprocess
import unittest


class HalloweenSeasonTests(unittest.TestCase):
    def test_calendar_and_actual_ui_timer_with_fake_clock(self):
        result=subprocess.run(['node','validation/halloween_season_unit.cjs'],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_policy_loads_before_decorations_and_has_no_backend_dependencies(self):
        html=Path('index.html').read_text(encoding='utf-8')
        self.assertLess(html.index('src="halloween_season.js"'),html.index('src="halloween.js"'))
        source=Path('halloween_season.js').read_text(encoding='utf-8')
        self.assertIn("timeZone='Europe/Kyiv'",source)
        self.assertIn('hourCycle:',source)
        for forbidden in ['fetch(', '/api/', 'localStorage', 'setTimeout(', 'getMonth(']:
            self.assertNotIn(forbidden,source)

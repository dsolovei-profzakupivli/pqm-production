"""TZ3 UI regressions: no application startup, DB or outbound requests."""
from pathlib import Path
import shutil
import subprocess
import unittest


class UiTz3Tests(unittest.TestCase):
    def test_navigation_filter_entry_points(self):
        result = subprocess.run(
            [shutil.which('node') or 'node', 'validation/ui_tz3_unit.cjs'],
            cwd=Path(__file__).resolve().parent, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('UI_TZ3_UNIT=PASS', result.stdout)

    def test_native_search_controls_suppressed_in_shared_component(self):
        css = (Path(__file__).parent / 'ui_improvements.css').read_text(encoding='utf-8')
        self.assertIn('input[type="search"]::-webkit-search-cancel-button', css)
        self.assertIn('display:none;-webkit-appearance:none', css)

    def test_protocol_markup_keeps_existing_actions_and_three_rows(self):
        source = (Path(__file__).parent / 'app.js').read_text(encoding='utf-8')
        line = next(line for line in source.splitlines() if line.startswith('function violationProtocolCell('))
        for token in ['request-protocol-heading', 'request-protocol-copy', 'data-protocol-askod', 'data-protocol-json', 'p.json_ready', 'p.officer', 'esc(p.url)', 'download']:
            self.assertIn(token, line)

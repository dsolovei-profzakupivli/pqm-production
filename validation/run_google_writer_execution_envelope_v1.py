"""Run the additive Apps Script envelope-size integrity overlay."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import test_sandbox_execution_envelope_limit_v1


if __name__=='__main__':
    unittest.main(module=test_sandbox_execution_envelope_limit_v1)

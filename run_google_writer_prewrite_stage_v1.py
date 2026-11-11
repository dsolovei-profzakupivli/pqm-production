"""Run the compact integrity checks for the prewrite stage contract."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import test_google_writer_prewrite_stage_integrity_v1


if __name__=='__main__':
    unittest.main(module=test_google_writer_prewrite_stage_integrity_v1)

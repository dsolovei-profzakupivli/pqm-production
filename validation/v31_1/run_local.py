"""Compatibility CLI for the shared, Git-independent V31.1 bridge."""
import argparse
from pathlib import Path
import bridge
ROOT=Path(__file__).resolve().parents[2]
validate_paths=bridge.validate_paths

def stage(target, *, baseline=False):
    return bridge.stage(ROOT,target,baseline=baseline)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=['unit','browser','measure','profile','history'],default='unit')
    args=parser.parse_args()
    bridge.phase(ROOT,args.phase,'local')
    return 0

if __name__=='__main__':raise SystemExit(main())

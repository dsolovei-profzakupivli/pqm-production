"""Stage 2B OFFLINE ONLY: streamed full-population aggregates, never live Render."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import perf_counter
from urllib.parse import quote

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import supplier_evidence_shadow_v3 as shadow


def benchmark(con, codes, as_of):
    started = perf_counter()
    count = gaps = 0
    for code in codes:  # iterator; NEVER list(codes), NEVER retain projection rows.
        result = shadow.stage_2a(con, {"offline": [code]}, as_of)
        count += 1
        gaps += result["aggregates"]["with_gaps"]
        del result
    return {"stage":"2B","suppliers":count,"with_gaps":gaps,
        "elapsed_ms":round((perf_counter()-started)*1000,3),"DB_WRITES":0}


def main():
    if os.getenv("RENDER_SERVICE_ID"):
        raise SystemExit("STOP: Stage 2B is offline only; live benchmark not approved")
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    with sqlite3.connect("file:"+quote(str(Path(args.db).resolve()),safe="/:")+"?mode=ro",uri=True) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        codes = (r[0] for r in con.execute("SELECT DISTINCT supplier_code FROM submissions ORDER BY supplier_code"))
        print(json.dumps(benchmark(con,codes,args.as_of),separators=(",",":")))


if __name__ == "__main__":
    main()

# Local performance baseline

## Final LOCAL smoke, 30.08.2026

| Request | HTTP | Measurement |
|---|---:|---:|
| `/api/health` | 200 | 177 ms |
| `/api/applications?page=1&size=1` | 200 | 3409 ms |
| `/api/applications?page=1&size=50` | 200 | 3373 ms |
| `/api/applications?page=1&size=50&search=альфа` | 200 | 4609 ms |
| `/api/framework-analytics?page=1&size=20&search=3929` | 200 | 762 ms |
| `/api/suppliers-registry?page=1&size=20` | 200 | 7433 ms |

Page-first EDR enrichment and batched NACP lookup remain enabled. The supplier registry is the slowest measured endpoint and remains a documented follow-up item; this package does not change its business SQL or schema.

Measured 30.08.2026 against the existing LOCAL server at `127.0.0.1:8080`. No sync or optimization was run.

| Request | HTTP | Warm measurement |
|---|---:|---:|
| `/api/health` | 200 | 286.5 ms |
| `/api/applications?page=1&size=1` | 200 | 2905.8 ms |
| `/api/applications?page=1&size=50` | 200 | 3386.4 ms |
| `/api/applications?page=1&size=50&search=альфа` | 200 | 4093.1 ms |

Note: the API enforces a minimum page size of 10, so `size=1` does not represent a single-row SQL workload. One preceding cold/anomalous `size=1` request took ~14.1 s; the immediate repeat returned to ~2.9 s. This is a baseline observation, not a deployment blocker or an optimization performed in this task.

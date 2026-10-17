# Halloween cat — Sandbox frontend candidate

Parent: 32aada59f24748803e1b4226f1e6e29d30b01ca8.
Custom inline SVG: existing assets have no suitable lying-cat illustration.
Attached to the institution-title strong element in the shared header, with
absolute positioning and no layout footprint. Pointer events disabled, SVG
hidden from accessibility tree. Tail/blink animations respect reduced motion.

Disable in My Account: Halloween · чорний кіт. Changes apply immediately;
preference stored only in this browser under pqm.halloween.cat.enabled.v1.
No profile API writes, dates/timers, external requests or backend changes.
Storage-disabled mode remains safe (preference cannot persist).

Local automated tests: 3/3 PASS; JS syntax and diff check PASS.
Offline Chromium: 20 combinations of 390/768/1024/1440/1920 CSS viewport,
100%/125% zoom, existing light/sandbox-dark CSS; header/logo/nav geometry and
document scroll width unchanged before/after injection; disable and reduced
motion checked. Fixtures use actual HTML/CSS with business JS disabled and
synthetic navigation; not deployed acceptance. Existing narrow navigation
overflow is not changed or claimed fixed by this decoration.

Screenshots and detailed checks: ../pqm-halloween-evidence-20261018 (workspace).
Manual appearance approval pending. No push, full gate, merge or deploy.
Rollback is removal/revert of this frontend-only candidate; no data recovery.

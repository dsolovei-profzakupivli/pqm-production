# Annual October policy — local Sandbox candidate

Parent43152ff579f86ff57dfd6cd49507686f86f6e1c1. Design CSS, all SVG illustrations,
approved WebP hashes and business code unchanged. Policy is browser-only, no
backend/API, database, scheduler, Google or kill-switch changes.

halloween_season.js is a pure Intl calendar module with explicit Europe/Kyiv.
Availability is [October1 00:00, November1 00:00) every year. Next midnight is
resolved using timezone parts, never a fixed UTC offset or browser-local month.
Unsupported timezone/invalid clock/module unavailable fail closed.

Effective visibility=October AND existing browser preference. All five components
use the same effective flag. Outside October checkbox is disabled and a forced
change event cannot enable decorations or overwrite preference. October restores
availability annually; a saved manual OFF remains OFF until the user enables it.
No new preference key or profile write is introduced.

Exactly one bounded setTimeout (maximum60seconds, no interval/network) rechecks
clock changes and targets the precise boundary for the final callback. Focus,
pageshow and visibilitychange re-evaluate immediately; pagehide clears the timer.
No page reload required. Browser/OS suspension can delay JavaScript execution;
on resume/visibility the real current Kyiv month is applied immediately. A browser
cannot guarantee executing code while its process/device is asleep. Local system
clock accuracy is assumed, as no server-time request is introduced.

Tests14/14 PASS. Actual policy and UI controller exercised by deterministic VM:
36 date/host-zone combinations, DST transition, millisecond boundaries, annual
availability, preference preservation, outside-season guard, lifecycle and a
single timer. Browser8 cases: two themes×two host zones (LA/Tokyo)×100%/125%; all
five components disappear at November midnight without navigation/reload, return
to availability next October, manual state and disabled guard work. Fixture DOM
uses actual PQM nav/badge renderers; no runtime/Live access.

New exact SHA must receive its own Linux/Docker gate before manual deployment.
Rollback can return to the previously Live32aada5, or accepted43152ff if it has
subsequently been deployed; confirm current Live at deployment time. No DB restore.
No deployment, restart, rollback, merge or Production changes authorized here.

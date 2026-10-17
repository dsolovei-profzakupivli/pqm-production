# Halloween stage 2 — local Sandbox candidate

Parent a619e1d preserves the approved cat refinements. Cat SVG SHA256 is pinned
by regression test; its dimensions, position, animations and silhouette rules
are unchanged in this stage. No Production, backend, database or API changes.

Thin web and hanging spider use CSS SVG pseudo-elements on #mainNav's existing
button.nav-active. No click handlers, observers or navigation logic added.
The active marker determines the decorated button, including rebuilt menus.
Both pseudo-elements have pointer-events:none, stay inside the button geometry
and use the existing data-halloween on/off preference. Spider motion is disabled
under prefers-reduced-motion. The spider SVG includes a fine light outline.

Targeted Python/Node tests 5/5 PASS. Offline Chromium: 60 viewport/theme/zoom/nav
mode combinations (390–1920px, light/sandbox dark, 100%/125%, text/icon/icon+text),
four tab switches each; active-only decoration, shared disable, reduced motion,
unchanged header/logo/nav/scroll dimensions checked. Clicks include navigation
scrolling on narrow fixtures. No live calls. This is isolated DOM/CSS testing,
not live Sandbox acceptance. Screenshots use synthetic navigation icons/data.

Evidence: workspace pqm-halloween-web-evidence-20261018/checks.json and screenshots.
No full release gate requested/run; no push, merge, deploy or restart.
Manual appearance approval pending. Rollback: previous local cat candidate;
no database restore required.

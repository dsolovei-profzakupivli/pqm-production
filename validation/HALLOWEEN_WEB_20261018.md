# Halloween stage 2 — local Sandbox candidate (lowered spider revision)

Parent a619e1d preserves the approved cat refinements. Cat SVG SHA256 is pinned
by regression test; its dimensions, position, animations and silhouette rules
are unchanged in this stage. No Production, backend, database or API changes.

Thin web uses a CSS pseudo-element on the existing button.nav-active. The spider
is a single fixed, non-interactive decorative SVG outside the nav overflow box,
with its body center about 15 CSS viewport pixels below the button. A read-only
MutationObserver/ResizeObserver and coalesced animation-frame positioning track
active classes, menu rebuilds, scrolling, fonts and viewport resize. A spider
whose anchor is scrolled out of view is hidden, not pinned to another button.
No navigation click handlers or business behavior changes. Both use the existing
data-halloween on/off preference; reduced motion disables animation.

Targeted Python/Node tests 5/5 PASS. Offline Chromium: 60 viewport/theme/zoom/nav
mode combinations (390–1920px, light/sandbox dark, 100%/125%, text/icon/icon+text),
four tab switches each; active-only decoration, shared disable, reduced motion,
body offset, unchanged header/logo/nav/scroll dimensions checked. Clicks include navigation
scrolling on narrow fixtures. No live calls. This is isolated DOM/CSS testing,
not live Sandbox acceptance. Screenshots use synthetic navigation icons/data.

Evidence: workspace pqm-halloween-web-evidence-20261018/checks.json and screenshots.
No full release gate requested/run; no push, merge, deploy or restart.
Manual appearance approval pending. Rollback: previous local cat candidate;
no database restore required.

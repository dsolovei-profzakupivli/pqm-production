# Stage4: pumpkin navigation badges

Paint of the existing #mainNav .action-count-badge, under the existing
data-halloween=on switch. Live number values and badge() logic are untouched.
30×30px SVG pseudo-element behind white bold live text; original22×20px layout
slot, padding/font-size/font-weight retained. No red inner disc. Stem/eyes/smile
are decorative and pointer-events:none. Zero remains hidden under the existing
badge renderer. Disabling Halloween restores the unmodified standard red badge.

All previous cat/web/spider/hat CSS/JS remains unchanged by this stage.
Targeted tests9/9 PASS. Browser8 viewport/theme/zoom cases×5 values=40 checks,
actual shipped nav_icons.js plus actual badge() renderer, no Live access.
Values0/3/9/14/27 updated without reload, on/off geometry/scroll equality
verified per value, original nav HTML/geometry retained after installation.
Widths1920/390, light/dark,100%/125%. Screenshots show fixture counts3/14,
synthetic avatar; not current runtime values. Existing standard layout change
when a zero badge disappears is preserved, not claimed removed.

Evidence: pqm-halloween-web-evidence-20261018/pumpkin-checks.json, pumpkin-*.png.
No Production/runtime/API/business logic modifications, no push/merge/deploy.
Visual approval pending; full gate not run at this local appearance stage.

Digit-readability revision: live text is wrapped in an inert span by the existing
coalesced nav observer path; textContent stays the server-supplied value. Normal
badge updates replace text as before and the span is recreated, without retries
or count computation. Only this span's paint scales1.18 (11px→about13px) with a
.3px dark outline. Its original font metrics still determine the layout, so the
badge/button sizes and padding are unchanged, including arbitrary digit lengths.
Off-state span inherits normal styling. Pumpkin SVG/colors/stem and all other
decorations unchanged. Tests10/10 PASS; browser40 value cases also assert digit
centering within .6px, transform/outline, live updates and on/off geometry.
Additional screenshots pumpkin-{light,dark}-9-27.png cover9/27 beside3/14.

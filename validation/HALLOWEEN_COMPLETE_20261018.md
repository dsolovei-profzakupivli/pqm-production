# Sandbox Halloween completion — final visual candidate

Confirmed Live baseline df7c40fb7a9478c78d0e317702725b4a0880cacb.
Based on local accepted experiment72ffbf68d329f6b6337d3cb352b212f939b5fb37.

Explicit eligible main workspaces: Work Queue, applications, history, suppliers,
EDR monitoring, framework analytics (actual frameworks route), procurements,
references (NAZK/AMCU/declension subpanels), customer appeals, operational tasks.
The unused frameworksView placeholder, administration, chat, login, dialogs and
standalone service pages are excluded. Only eligible main wrappers receive the
halloween-workspace class; no component/descendant styles are introduced.

Approved original images use cover/right-bottom (contain <=900px), preserving
aspect ratio. Paint height is remaining initial viewport, NOT table height;
scroll position is normalized back to document origin. Long pages show normal
PQM background after the first scene rather than rescaling a castle/moon to a
many-thousand-pixel table. No content min-height, width limit, card transparency
or padding changes. Reduced zoom may leave solid edges as permitted. An opaque
table naturally hides the scene behind it; do not modify the table to expose art.

Spider-only motion adjustment: ±5deg, 4.5s ease-in-out infinite; same top-of-thread
transform origin. Thread, spider size, SVG, web geometry unchanged. Reduced-motion
CSS disables animation. Cat remains the identical static WebP with no split tail.
Avatar hat, pumpkin rendering/count updates, October policy and stored preference
remain unchanged. Existing one bounded timer/lifecycle boundary checks retained.

Additional approved appeal KPI fix: sandbox_theme.css broad [class*="card"]
selector unintentionally paints request-authority-cards flex wrapper #132840.
Unused flex space is not a functional card. A scoped requests-only transparent
background override removes that fill, preserving all child buttons, card styles,
active state, counters and current delegated filter handlers. No app.js changes.

Tests:26 local unit/contracts PASS. Browser matrix320 cases across10 actual
workspaces x2 themes x2 widths(1920/800) x4 zooms(75/80/100/125%) x short/long
tables; actual component/CSS fixtures with synthetic data and APIs blocked.
Dark markup uses actual Sandbox server decorator; shared light PQM template
tested without inventing a new theme switch. Compare component geometry,
colours/fonts/opacity and document scroll before/after decoration. Test scene
height independent of rows/scroll, native tab hidden state updates, manual OFF,
November midnight without reload and next-year availability. Twenty full-page
screenshots at1920px/100% plus four KPI before/after pairs retained externally.
Browser motion checks cover normal/reduced preferences, exact cycle and matrices.

Functional business flows are not simulated by synthetic visual table rows;
full Linux/Docker gate for the new exact SHA is separately required. No live
test writes/sync, scheduler or Google execution is needed for acceptance.

Rollback: user manually returns Sandbox to df7c40f after fresh current-state
confirmation. No DB/Environment restore or migration. Keep kill-switch=1.
Render intermittent static HTTP502 remains a separate known risk; decorative
release gate cannot prove gateway delivery fixed. No Production theme switch is
part of this candidate. Only specifically authorized candidate push/gate allowed;
no merge/deploy/restart/rollback performed by agent.

Earlier experiment documentation is historical; this document supersedes its
three-workspace-only and long-table paint-height behavior descriptions.

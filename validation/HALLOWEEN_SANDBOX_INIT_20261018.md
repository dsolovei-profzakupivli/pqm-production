# Sandbox Halloween initialization compatibility

Parent: d6a55bbcf7cd157c7e3812619c69c5ad293fe52e.

The runtime Sandbox HTML decorator substitutes sandbox-brand-copy for
prod-brand-copy. The former title-only selector caused an early return before
all decorations and the preference checkbox. Accept both title containers and
scope only the cat insertion to title presence. The rest of initialization and
the October Europe/Kyiv policy remain independent. Extend cat positioning to
both containers; no artwork, geometry, API or backend changes.

Regression coverage calls sandbox_runtime.decorate_html on actual index.html
before checking the frontend contract. Also covers the unchanged Production
brand, an absent brand, season gating, preference and CSS anchoring.
Local browser matrix: real decorated Sandbox HTML / raw template / missing title,
light and dark, zoom100/125. Navigation uses existing nav_icons.js, real HTML
cards and synthetic counts; runtime API traffic blocked. Checks all decoration
groups, checkbox, manual toggle without reload, November disabled state and no
horizontal overflow. This is not authenticated Live acceptance.

Rollback is user-performed code rollback to the prior confirmed Live SHA,
d6a55bbcf7cd157c7e3812619c69c5ad293fe52e, after a fresh deploy preflight.
No schema/data/Environment changes require reversal. That rollback restores the
known missing-decoration issue. HTTP502 remains a separate delivery risk.

# Halloween stage3: avatar-bound witch hat

Frontend only, parent350bd9648f21ae3982da3dddfd63b6007c1cf1e0.
40×28px decorative SVG in a fixed, pointer-events:none overlay. Geometry tracks
#currentUserAvatar, never the account button. Head/face remains visible below
the top7px brim region; black silhouette, purple ribbon, orange buckle, dark
theme outline. Source image/src is never modified. Shared browser-only toggle
now describes all Halloween decorations. Cat/web/spider remain unchanged.

Existing header hides currentUserAvatar when there is no photo, or load fails;
it has no automatic default icon. Hat hides in that case too. No new avatar,
layout slot, profile API behavior or database data introduced. Standard SVG
icon support tested by supplying the existing group-avatar.svg to the isolated
image element; this does NOT add fallback behavior to the real application.

Tests:8/8 targeted PASS, JS syntax and diff check PASS. Offline Chromium24 cases:
light/dark,100%/125%,1920/390 viewport, synthetic raster portrait / existing SVG
icon / absent image. Actual nav_icons.js and badge renderer used, fixture
counts7/14. Checked no nav HTML/geometry changes after decoration, hat40×28,
brim offset7px, pointer-events:none, hidden when avatar absent, shared toggle.
Not a live-account test; no personal photo or runtime accessed.

Evidence: pqm-halloween-web-evidence-20261018/hat-checks.json and hat-*.png.
No full release gate, push, merge, deploy or restart performed. Appearance
approval pending. Rollback is local frontend revert, no data recovery needed.

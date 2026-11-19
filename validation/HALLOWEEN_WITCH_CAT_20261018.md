# Local witch-cat visual candidate

Parent: 44081be4985b46b39b1617fbadbb5d93efc6f9ee (Sandbox initialization fix).
Only the cat artwork and its responsive sizing change. Existing seasonal policy,
preference, spider/web, avatar hat, pumpkins and backgrounds remain unchanged.

Reference: operator-supplied Gemini screenshot, clipboard-b62cd2f7.
No standalone reference cat asset found in the application candidate.
Built-in imagegen used to reconstruct an isolated transparent cat, not the UI.
Prompt: Extract/reconstruct ONLY the black cat at the screenshot upper left.
Match long horizontal black body, curved tail left, tilted head right, dangling
paws, lime-green eyes, purple pointed witch hat and orange ribbon/buckle.
Match pose/style/proportions; complete cropped tip; genuine transparent alpha;
no UI, letters, logo, sky, background rectangle, text or extra objects.

Generated source preserved in Codex generated_images. Project asset:
assets/halloween-witch-cat.webp, 720x389 RGBA, 46,718 bytes.
Mechanical downscale/WebP encoding uses sharp; no composition edits.
Cat is a decorative non-draggable image with empty alt, aria-hidden and
pointer-events:none. No animation added; reduced-motion behavior elsewhere
unchanged. Whole-image animation would move the hat/paws together and was not
requested for this replacement.

Operator explicitly permits substantial overlap of institution title/logo.
Keep navigation and controls unobscured; 180px desktop, 100px <=900,
95px <=600, aspect ratio preserved. Image absolute positioning introduces no
layout dimensions. Local browser matrix: shared light PQM header, actual
server-transformed dark Sandbox header; 1920/800/480px, zoom100/125.
Actual DOM/cards/navigation with synthetic count/avatar, no authenticated API.
Check nav/header geometry unchanged on toggle, cat outside nav, no horizontal
overflow, image decodes, manual toggle and November season disable work.

This is local visual acceptance only. No push/merge/deploy authorized for this
candidate. Full gate for this visual candidate not run. Previous initialization
candidate gate was not dispatched (system permission rejected); do not imply
it passed. A later promotion requires a newly approved exact-SHA release gate.

# Stage5 — Work Queue background, local visual approval candidate

Parent d15bd15335237cf790ff9183320de9aebdca57ac. Only halloween.css is extended,
with three tiny local SVG assets and tests/docs. Previous decorative CSS and
all JavaScript are unchanged. No external graphics or animation.

Active selectors require data-halloween=on AND visible #workQueueView. Isolated
negative-z pseudo-layers sit above the original main background but behind all
content, with pointer-events:none. Underlying theme background is retained.
Two very low-alpha edge glows, two corner webs and three small bats; no pumpkin
silhouettes added (optional in task) to avoid visual noise. Light theme opacity
is lower; dark remains navy with restrained orange glow. Off has no pseudo-layer.

Tests12/12 PASS. Offline Chromium8 cases: themes2 × widths1920/390 × zoom100/125.
Actual loadWorkQueue() and shipped card HTML render isolated fixture summaries,
not copied or invented card markup. Actual nav_icons.js/badge() renderer used.
Card values/names, nav counts3/14 and standard SVG avatar are test fixtures, not
runtime data. All32 card/button/input/table computed styles and rectangles,
header height, page scroll width/height remain identical on/off. Other tab has
no background; decorative layers pointer-events:none and behind content.
Screenshots full-page workqueue-{theme}-{width}-{zoom}.png and checks JSON in
workspace pqm-halloween-web-evidence-20261018. Manual appearance approval pending.

No runtime/Production/API/database/automation changes, no push/merge/deploy.
No full Linux/Docker gate run at this local visual-approval stage.

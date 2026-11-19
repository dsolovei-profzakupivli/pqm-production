# Approved landscape integration — local Sandbox visual candidate

Baseline96b4bd1c3364d9a0330c2dcfbbe45bd5dc47d76b. Two approved clean WebP files
copied byte-for-byte, no generation/repainting/recoloring/crop of the resources:

| Asset | Bytes | SHA256 |
| --- | ---: | --- |
| assets/halloween-workqueue-dark.webp |99524|54201419649b53a1d41f3dc33abe38b25fe3a7d26707c7446831df233d364377|
| assets/halloween-workqueue-light.webp |224438|f11bb9e7b4f042fde5f24f2e55ea9b0895275823d0196e1780cef734f3747302|

Only visible #workQueueView under Halloween=on gets a negative-z, pointer-free
background. Desktop uses cover/right-bottom preserving source aspect ratio and
right-side focus. At<=900px contain shows the complete proportional image at
the lower edge; opaque cards naturally obscure parts of the artwork on tall
mobile layouts. No blank area/layout height is added merely to expose scenery.
An isolated ResizeObserver/hidden/resize hook computes PAINT height only, to
extend to viewport bottom without changing main/card dimensions or scroll.
Failed image leaves normal PQM background. No overlay tint, opacity or filters.

Previous Halloween CSS prefix is byte-identical; JavaScript is identical after
removing the isolated queue sizing hook. Cat/web/spider/hat/pumpkin semantics
unchanged. Old stage5 three tiny unused SVGs removed; recoverable from baseline.
No HTML, backend, API, database, scheduler, Google or kill-switch changes.

Tests12/12 PASS; JS syntax/diff check PASS. Browser16 cases: light/dark ×1920/390
×100%/125% ×available/missing image. Actual loadWorkQueue()/nav/badge renderers,
isolated synthetic counts and names; not Live runtime. All32 work element
rectangles/fonts/colors/backgrounds/borders/padding and page scroll dimensions
unchanged. Date input editing and Apply button hit-test pass. Shared switch
hides all decorations and restores standard background; other module unaffected.
Correct local image fetched by theme. No page errors or unexpected resource
errors; deliberate image404 cases recorded separately and fall back normally.

Evidence in workspace pqm-halloween-web-evidence-20261018:
landscape-checks.json, landscape-integrity.json, landscape-{theme}-{width}-{zoom}.png.
Compared with approved reference: same moon/castle/right-side placement and
landscape composition; screenshot uses real opaque HTML cards over clean image,
not AI-rendered UI. Cards/data remain existing renderer output with fixture data.
Full Linux/Docker gate not requested/run at this local visual approval stage.
No push, merge, deploy or runtime modifications. Manual approval pending.

# Sandbox Halloween candidate

`VISUAL_ACCEPTANCE=PASS` — the user approved the integrated local appearance
on 19 October 2026. Preserve the witches, spark trail, cat eyes and theme
appearance without further design changes.

Sandbox baseline: `8fa52a62641f80bb322de177a76a98bf92ce3ecb`.
Candidate branch: `codex/sandbox-halloween-candidate-20261019`.
The exact candidate revision is this commit, obtainable with `git rev-parse HEAD`.

The contacted Sandbox service `srv-dalfd77f3r2c7392uub0` reported this baseline
and `PQM_DISABLE_BACKGROUND_JOBS=1` immediately before candidate preparation.
The decorated baseline HTML matches the contacted Live HTML after CRLF/LF
normalization, SHA256
`1fa0e95b289a1f03ba82063af6d48d3f5cd738f9f6283b1e7f30df55683b5845`.

## Scope and safety

Only the Sandbox HTML decorator includes the new motion stylesheet/script;
the script also exits immediately without Sandbox identity. Shared `index.html`
and Production inclusion remain unchanged. The existing cat raster, background
artwork, Halloween preference/calendar modules, personal themes, KPI/filter/UI
code, API, scheduler, kill-switch and Google execution modules are unchanged.
`sandbox_runtime.py` changes only inside `decorate_html`; the baseline contract
checks the AST outside that function and hashes protected files.

The new layer preserves the approved flight speed across the full viewport,
supports CSS zoom without adding overflow, does not receive pointer events,
and respects the existing Halloween gate and reduced motion. The particle
population and animation-frame chain are bounded and cleared between flights.

The transfer archive was verified against all 42 listed checksums; archive
SHA256: `768662f58a3a6d777165569979cc3c4466c1dfb906949455c7285d98dc13a1e1`.
Historical Halloween files were not copied over the current Sandbox versions.

## Local validation

- Final delivered-fixture Halloween suite: 27 tests PASS, including the new
  integration contract in a source copy without `.git`.
- Final kill-switch and Sandbox personal-theme contracts: 25 tests PASS.
- Final browser integration: both themes, 100/125% zoom, narrow viewport,
  unchanged working-element geometry/colours/scrolling/hit testing, one witch,
  alternation, full exit, original speed, bounded particle lifecycle, real
  scheduled blinking, eye movement, manual OFF, reduced motion, route hiding,
  pagehide/pageshow and Kyiv October boundaries PASS. An actual first-flight
  timer expiry was observed after approximately 29 seconds.
- Before visual acceptance: 82 Python tests and 888 existing personal-theme
  browser cases PASS. Offline visual preview and eye sequences PASS.
- JS syntax and `git diff --check` PASS.

The root-level `test_halloween_motion_contract.json` comes from the immutable
baseline, not current candidate files. Tests need neither Git history nor
external services inside the release image. Regenerate the contract only when
reviewing an explicitly changed baseline; do not regenerate it to hide drift.

Browser tools use the installed local Playwright/Chromium paths on the review
machine. They render the actual decorated HTML with synthetic presentation
data; they do not execute application/API scripts or access Live databases.

## Manual Release Gate — not launched by this task

1. Open GitHub Actions → **PQM release checks** (`release-checks.yml`).
2. Select **Run workflow**, choose
   `codex/sandbox-halloween-candidate-20261019`, and dispatch manually.
3. Confirm `ci-evidence/tested-sha.txt` matches the exact published candidate SHA.
4. Review the entire container/release regression gate and retained evidence.

This commit and candidate-branch publication authorize no merge, deployment,
restart, Production promotion or workflow dispatch by the agent. Stop after
publishing and let the user run GitHub Actions manually. Full Release Gate
acceptance remains pending that manual run.

## Visually accepted atlas-frame correction

The first candidate `9ceb412639bac494b3bb14c4fc7218ccb86c10b8` passed manual
Release Gate run `39173122347`, including 1766 regression tests. A subsequent
visual review identified neighbouring-frame pixels beside the witches.

The default SVG `xMidYMid meet` alignment leaves horizontal gutters when each
source frame is fitted into the approved viewport. `viewBox` alone did not
clip the atlas to that frame, so the other witch's broom could paint there.
Each image now has an explicit `userSpaceOnUse` clip matching its source frame.
The PNG, witches, timing, dimensions, trajectory, eye animation and spark
implementation are unchanged. No background masking is used.

The user visually accepted this correction (`VISUAL_ACCEPTANCE=PASS`).
Pixel checks show 30/349 painted gutter pixels before and zero after for
witches 1/2 in both themes. Both complete subject components remain inside
their source bounds; the original PNG bytes are unchanged. The review samples
100 flight phases for each witch/theme and preserves geometry and timing.

Reproduce the local enlarged comparison with:

```text
python -B validation/render_halloween_integration.py
node validation/halloween_fragment_review.cjs before
node validation/halloween_fragment_review.cjs after
python -B validation/halloween_fragment_report.py
```

The before renderer reads only the original candidate's motion script from
Git history; it never rewrites working source. The report uses Pillow for
read-only alpha-component analysis. Open `evidence/halloween-fragment/index.html`.

The earlier successful Release Gate covers only `9ceb412...`. Run it manually
again on the new exact branch SHA; do not promote using the old result.

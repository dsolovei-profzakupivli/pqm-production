import hashlib,json,os,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sandbox_runtime
os.environ['PQM_SANDBOX']='1'
out=ROOT/'evidence'/'halloween-integration';out.mkdir(parents=True,exist_ok=True)
candidate=sandbox_runtime.decorate_html((ROOT/'index.html').read_bytes()).decode()
inclusion=('\n  <link rel="stylesheet" href="halloween_motion.css">'
          '\n  <script src="halloween_motion.js"></script>'
          '\n  <link rel="stylesheet" href="halloween_cat_season.css?v=1">'
          '\n  <script src="halloween_cat_season.js?v=1"></script>')
assert candidate.count(inclusion)==1,'Expected exactly one complete seasonal asset block in the current UI candidate'
baseline=candidate.replace(inclusion,'')
assert baseline!=candidate and all(asset not in baseline for asset in ('halloween_motion.css','halloween_motion.js','halloween_cat_season.css','halloween_cat_season.js'))
(out/'candidate.html').write_text(candidate,encoding='utf-8',newline='')
(out/'baseline.html').write_text(baseline,encoding='utf-8',newline='')
report={'comparison':'current UI candidate versus identical HTML with exactly the four seasonal asset tags removed','baseline_sha256':hashlib.sha256(baseline.encode()).hexdigest(),'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest(),'seasonal_asset_block_occurrences':1}
(out/'render-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
# Local, offline presentation fixture: actual decorated Sandbox DOM/CSS, synthetic
# counts only, application/API scripts excluded. The unmodified HTML is above.
preview=re.sub(r'<script\b[^>]*>[\s\S]*?</script>','',candidate,flags=re.I)
preview=preview.replace('<head>','<head><base href="../../">').replace('src="/assets/','src="assets/').replace('href="/assets/','href="assets/')
scripts='<script src="theme_ui.js"></script><script src="nav_icons.js"></script><script src="sandbox_contrast.js"></script><script src="halloween_season.js"></script><script src="halloween.js"></script><script src="halloween_motion.js"></script><script src="halloween_cat_season.js"></script><script src="validation/halloween_integration_fixture.js"></script><script>HalloweenIntegrationFixture.install();</script>'
preview=preview.replace('</body>',scripts+'</body>')
(out/'index.html').write_text(preview,encoding='utf-8')
print(json.dumps(report,indent=2))

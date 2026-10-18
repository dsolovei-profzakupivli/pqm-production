import hashlib,json,os,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sandbox_runtime
os.environ['PQM_SANDBOX']='1'
out=ROOT/'evidence'/'halloween-integration';out.mkdir(parents=True,exist_ok=True)
candidate=sandbox_runtime.decorate_html((ROOT/'index.html').read_bytes()).decode()
inclusion='\n  <link rel="stylesheet" href="halloween_motion.css">\n  <script src="halloween_motion.js"></script>'
baseline=candidate.replace(inclusion,'')
assert baseline!=candidate
(out/'candidate.html').write_text(candidate,encoding='utf-8',newline='')
(out/'baseline.html').write_text(baseline,encoding='utf-8',newline='')
live_sha256='1fa0e95b289a1f03ba82063af6d48d3f5cd738f9f6283b1e7f30df55683b5845'
normalized=hashlib.sha256(baseline.replace('\r\n','\n').encode()).hexdigest()
report={'decorated_baseline_matches_contacted_live_html':normalized==live_sha256,'contacted_live_sha256':live_sha256,'comparison':'normalized CRLF/LF only; Windows checkout vs Linux Live','baseline_sha256':hashlib.sha256(baseline.encode()).hexdigest(),'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest()}
assert report['decorated_baseline_matches_contacted_live_html'],report
(out/'render-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
# Local, offline presentation fixture: actual decorated Sandbox DOM/CSS, synthetic
# counts only, application/API scripts excluded. The unmodified HTML is above.
preview=re.sub(r'<script\b[^>]*>[\s\S]*?</script>','',candidate,flags=re.I)
preview=preview.replace('<head>','<head><base href="../../">').replace('src="/assets/','src="assets/').replace('href="/assets/','href="assets/')
scripts='<script src="theme_ui.js"></script><script src="nav_icons.js"></script><script src="sandbox_contrast.js"></script><script src="halloween_season.js"></script><script src="halloween.js"></script><script src="halloween_motion.js"></script><script src="validation/halloween_integration_fixture.js"></script><script>HalloweenIntegrationFixture.install();</script>'
preview=preview.replace('</body>',scripts+'</body>')
(out/'index.html').write_text(preview,encoding='utf-8')
print(json.dumps(report,indent=2))

import os,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sandbox_runtime
os.environ['PQM_SANDBOX']='1'
out=ROOT/'evidence'/'halloween-shared';out.mkdir(parents=True,exist_ok=True)
html=sandbox_runtime.decorate_html((ROOT/'index.html').read_bytes()).decode()
html=re.sub(r'<script\b[^>]*>[\s\S]*?</script>','',html,flags=re.I).replace('<head>','<head><base href="../../">').replace('src="/assets/','src="assets/').replace('href="/assets/','href="assets/')
scripts=''.join(f'<script src="{name}"></script>' for name in ['theme_ui.js','nav_icons.js','sandbox_contrast.js','halloween_season.js','halloween.js','halloween_motion.js','validation/halloween_integration_fixture.js'])
scripts+='<script>HalloweenIntegrationFixture.install();</script><script src="validation/halloween_shared_fixture.js"></script><script src="validation/halloween_shared_preview.js"></script>'
(out/'index.html').write_text(html.replace('</body>',scripts+'</body>'),encoding='utf-8')
print(out/'index.html')

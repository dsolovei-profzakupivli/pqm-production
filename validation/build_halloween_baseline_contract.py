"""One-time contract generation from the approved baseline, never current files."""
import ast,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='8fa52a62641f80bb322de177a76a98bf92ce3ecb'
files=['index.html','server.py','app.js','theme_ui.js','theme.css','sandbox_theme.css','sandbox_contrast.js','halloween.js','halloween.css','halloween_season.js','auth_access.py','background_jobs.py','scheduler_runtime.py','google_writer_execution.py','assets/halloween-witch-cat.webp','assets/halloween-workqueue-light.webp','assets/halloween-workqueue-dark.webp']
read=lambda p:subprocess.check_output(['git','show',f'{BASE}:{p}'],cwd=ROOT)
sha=lambda b:hashlib.sha256(b).hexdigest()
tree=ast.parse(read('sandbox_runtime.py').decode())
for i,node in enumerate(tree.body):
 if isinstance(node,ast.FunctionDef) and node.name=='decorate_html':tree.body[i]=ast.Pass()
contract={'baseline':BASE,'normalization':'CRLF to LF for text only','files':{p:sha(read(p) if p.endswith('.webp') else read(p).replace(b'\r\n',b'\n')) for p in files},'sandbox_runtime_outside_decorator_ast':sha(ast.dump(tree,include_attributes=False).encode())}
(ROOT/'test_halloween_motion_contract.json').write_text(json.dumps(contract,indent=2)+'\n',encoding='utf-8')

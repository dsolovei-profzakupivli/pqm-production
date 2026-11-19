import hashlib,json,subprocess
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence'/'halloween-fragment'
before=json.loads((OUT/'before.json').read_text());after=json.loads((OUT/'after.json').read_text())
checks=[]
for old,new in zip(before,after):
 assert (old['theme'],old['witch'])==(new['theme'],new['witch'])
 for key in ['viewBox','viewport','duration','phases']:
  assert old[key]==new[key],(key,old['theme'],old['witch'])
 assert old['gutters']['paintedGutterPixels']>0 and new['gutters']['paintedGutterPixels']==0
 assert new['completeFlight']['samples']==100 and new['completeFlight']['clipRectFixedToSourceFrame']
 checks.append({'theme':new['theme'],'witch':new['witch'],'painted_gutter_pixels_before':old['gutters']['paintedGutterPixels'],'painted_gutter_pixels_after':new['gutters']['paintedGutterPixels'],'geometry_timing_phases':'identical','full_flight_samples':100})
art=ROOT/'assets'/'halloween-witches-sheet.png';original=subprocess.check_output(['git','show','9ceb412639bac494b3bb14c4fc7218ccb86c10b8:assets/halloween-witches-sheet.png'],cwd=ROOT)
assert art.read_bytes()==original
# Analyse connected subject pixels in the unchanged atlas, independently of
# browser antialiasing. Neither main witch component crosses its frame bounds.
image=Image.open(art);width,height=image.size;mask=bytearray(image.getchannel('A').point(lambda v:255 if v>32 else 0).tobytes());components=[]
for start in range(len(mask)):
 if not mask[start]:continue
 mask[start]=0;stack=[start];count=0;left=right=start%width;top=bottom=start//width
 while stack:
  p=stack.pop();x=p%width;y=p//width;count+=1;left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)
  for q in ([p-1] if x else [])+([p+1] if x+1<width else [])+([p-width] if y else [])+([p+width] if y+1<height else []):
   if mask[q]:mask[q]=0;stack.append(q)
 if count>1000:components.append({'pixels':count,'bbox':[left,top,right+1,bottom+1]})
subjects=sorted(sorted(components,key=lambda c:c['pixels'],reverse=True)[:2],key=lambda c:c['bbox'][0])
assert len(subjects)==2
for subject,(left,right) in zip(subjects,[(0,1050),(1050,1983)]):
 x0,y0,x1,y1=subject['bbox'];assert left<x0<x1<right and 0<y0<y1<793
report={'status':'PASS; VISUAL_ACCEPTANCE=PASS','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'png_sha256':hashlib.sha256(original).hexdigest(),'png_bytes_unchanged':True,'subject_components_fully_inside_clip_frames':subjects,'cause':'SVG viewBox is not a clip rectangle: xMidYMid meet letterboxing let the adjacent atlas frame paint in horizontal gutters. Explicit source-frame clipPath removes only those neighbouring-frame pixels.','checks':checks}
(OUT/'REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
html='''<!doctype html><html lang="uk"><meta charset="utf-8"><title>Відьми — до/після</title><style>body{background:#202b3b;color:#eef3fc;font:16px system-ui;margin:24px}section{margin:32px 0}.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.pair img{width:100%;height:auto;border:1px solid #70839b;box-sizing:border-box}.phase{width:100%;margin-bottom:10px}a{color:#b5d5ff}summary{cursor:pointer}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style><h1>Зайвий фрагмент — до / після</h1><p>Збільшені кадри фактичного Sandbox-рендера (4×). PNG та сама відьма не змінені. Виправлено межу малювання кадру SVG; без маскування фоном.</p>'''
for theme in ['light','dark']:
 for witch in [1,2]:
  html+=f'<section><h2>{"Світла" if theme=="light" else "Темна"} тема · відьма {witch}</h2><div class="pair">'
  for stage,title in [('before','ДО'),('after','ПІСЛЯ')]:html+=f'<div><h3>{title}</h3><img src="{stage}-{theme}-witch-{witch}.png" alt="{title}"></div>'
  html+='</div><details><summary>Весь маршрут: кадри після виправлення</summary>'
  for phase in [1,100,250,500,750,840,940,999]:html+=f'<p>Фаза {phase/10:.1f}%</p><img class="phase" src="after-{theme}-witch-{witch}-phase-{phase}.png">'
  html+='</details></section>'
html+='<p>PNG побайтово незмінний. Обидві відьми повністю лежать усередині своїх кадрів; їхні розміри й координати не змінено. Чужі пікселі в бічних полях після виправлення — 0. Перевірено по 100 фаз кожної відьми в обох темах.</p></html>'
(OUT/'index.html').write_text(html,encoding='utf-8')
print(json.dumps(report,indent=2))

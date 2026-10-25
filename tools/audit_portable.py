"""Compare deliverable bytes with live secrets in server memory. Never export values."""
import ast
import io
import json
import shlex
import subprocess
import zipfile
from prepare_backup import ROOT,BASE,inventory

tree=ast.parse((BASE/'audit_snapshot.py').read_text(encoding='utf-8'))
remote=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets))
skip_parts={'.git','__pycache__','.state','archives','restore-test'}
files=[p for p in ROOT.rglob('*') if p.is_file() and not skip_parts.intersection(p.relative_to(ROOT).parts)
       and p.suffix.lower() not in ('.deb','.gz','.jpg','.png') and not p.name.endswith('.partial')]
blocked=[]
for p in files:
    rel=p.relative_to(ROOT).as_posix()
    if rel.startswith(('deployment/deploy/state/','extras/proxy-importer/runs/')) or rel.endswith(('/.env','/deploy/config.yaml')):
        blocked.append(rel)
    if p.suffix.lower() in ('.pem','.key','.dpapi','.sqlite','.db'):blocked.append(rel)
assert not blocked,'Sensitive file type found: '+','.join(blocked)
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
    for p in files:archive.writestr(p.relative_to(ROOT).as_posix(),p.read_bytes())
print('Auditing %s source/config/script files against production sensitive values; no values will be printed.'%len(files),flush=True)
p=subprocess.run(inventory.SSH+['python3 -c '+shlex.quote(remote)],input=buffer.getvalue(),capture_output=True,timeout=240)
if p.returncode:raise SystemExit('Secret scan incomplete; raw output withheld')
result=json.loads(p.stdout)
result['excluded_binary_verification']='Image OCI blobs and official Docker deb packages verified separately by SHA256; UI screenshots checked visually.'
(ROOT/'evidence/sensitive-data-audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)
if not result['passed']:raise SystemExit(1)

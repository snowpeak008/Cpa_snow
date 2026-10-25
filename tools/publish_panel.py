"""Atomically replace only management.html after checking the exact reviewed baseline."""
import base64
import hashlib
import json
import shlex
import subprocess
import sys
from prepare_backup import ROOT,inventory

page=(ROOT/'web/management.html').read_bytes()
new_hash=hashlib.sha256(page).hexdigest()
old_hash=json.loads((ROOT/'evidence/branding-build.json').read_text(encoding='utf-8'))['source_sha256']
simplified='--simplified' in sys.argv
if simplified:
 old_hash=json.loads((ROOT/'evidence/panel-publication.json').read_text(encoding='utf-8'))['after_sha256']
REMOTE=r'''
import base64,datetime,hashlib,json,os,pathlib,subprocess,sys,urllib.request
d=json.load(sys.stdin)
root=pathlib.Path('/opt/cpa');target=root/'panel/management.html'
backup=root/('panel-backups/snow-console-20261025-before-simplify.html' if d['simplified'] else 'panel-backups/snow-console-20261025-before.html')
sha=lambda x:hashlib.sha256(x).hexdigest()
def invariants():
 c=json.loads(subprocess.check_output(['docker','inspect','cli-proxy-api']))[0]
 return {'config':sha((root/'config.yaml').read_bytes()),'compose':sha((root/'docker-compose.yml').read_bytes()),
         'container_id':c['Id'],'image':c['Image'],'started_at':c['State']['StartedAt']}
before=invariants();old=target.read_bytes();new=base64.b64decode(d['html'])
assert sha(old)==d['expected_old'], 'Live page differs from reviewed baseline; refusing overwrite'
assert sha(new)==d['expected_new'], 'Transfer checksum mismatch'
backup.parent.mkdir(exist_ok=True)
if backup.exists():assert sha(backup.read_bytes())==d['expected_old'], 'Existing backup differs'
else:
 with backup.open('xb') as f:f.write(old);f.flush();os.fsync(f.fileno())
temporary=target.with_name('.management-snow-20261025.tmp')
assert not temporary.exists(),'Previous staging file exists; inspect it first'
with temporary.open('xb') as f:f.write(new);f.flush();os.fsync(f.fileno())
os.chmod(temporary,target.stat().st_mode & 0o777)
os.replace(temporary,target)
try:
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with op.open('http://127.0.0.1:8317/management.html',timeout=12) as r:
  served=r.read();status=r.status
 assert status==200 and sha(served)==d['expected_new'], 'Served page does not match'
 after=invariants()
 assert before==after,'Unexpected concurrent configuration/container change'
except Exception:
 with temporary.open('xb') as f:f.write(old);f.flush();os.fsync(f.fileno())
 os.chmod(temporary,target.stat().st_mode & 0o777);os.replace(temporary,target)
 raise
print(json.dumps({'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'deployed':True,
 'target':str(target),'backup':str(backup),'before_sha256':sha(old),'after_sha256':sha(new),
 'served_sha256':sha(served),'http_status':status,'invariant_before':before,'invariant_after':after,
 'service_restarted':False,'config_changed':False,'model_requests_sent':0}))
'''
payload=json.dumps({'html':base64.b64encode(page).decode(),'expected_old':old_hash,'expected_new':new_hash,'simplified':simplified}).encode()
p=subprocess.run(inventory.SSH+['python3 -c '+shlex.quote(REMOTE)],input=payload,capture_output=True,timeout=65)
if p.returncode:raise SystemExit('Panel publication did not complete. Raw output withheld; inspect before retrying.')
result=json.loads(p.stdout)
(ROOT/('evidence/panel-simplification-publication.json' if simplified else 'evidence/panel-publication.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)

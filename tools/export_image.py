"""Read-only docker image export over SSH; compress on the Windows workstation."""
import gzip
import hashlib
import json
import subprocess
import tarfile
import time
from pathlib import Path
from prepare_backup import ROOT, inventory

out = ROOT / 'deployment/images/cpa-v8.0.31-linux-amd64.tar.gz'
out.parent.mkdir(exist_ok=True)
if out.exists():raise SystemExit('Refusing to overwrite completed image archive')
partial=out.with_suffix(out.suffix+'.partial')
started=time.time()
with (ROOT/'evidence/image-export.stderr.txt').open('wb') as err:
    p=subprocess.Popen(inventory.SSH+['docker image save eceasy/cli-proxy-api:v8.0.31'],stdout=subprocess.PIPE,stderr=err)
    total=0
    with partial.open('wb') as target, gzip.GzipFile(filename='',fileobj=target,mode='wb',compresslevel=1,mtime=0) as zipped:
        while True:
            chunk=p.stdout.read(1024*1024)
            if not chunk:break
            zipped.write(chunk);total+=len(chunk)
            if total%(32*1024*1024)==0:print(json.dumps({'received_mib':total//(1024*1024)}),flush=True)
    if p.wait(timeout=30):raise SystemExit('Docker image export failed; partial file retained for inspection')
if total<1024*1024:raise SystemExit('Unexpectedly small image archive')
partial.replace(out)
with tarfile.open(out,'r:gz') as tar:
    names=tar.getnames()
    manifest=json.load(tar.extractfile('manifest.json')) if 'manifest.json' in names else None
    index=json.load(tar.extractfile('index.json')) if 'index.json' in names else None
h=hashlib.sha256()
with out.open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
d={'file':str(out.relative_to(ROOT)),'sha256':h.hexdigest(),'bytes':out.stat().st_size,
   'uncompressed_bytes':total,'elapsed_seconds':round(time.time()-started,2),
   'docker_manifest':manifest,'oci_index':index,'tar_member_count':len(names),
   'production_action':'docker image save only; no container restart or image rebuild'}
(ROOT/'evidence/image-export.json').write_text(json.dumps(d,indent=2),encoding='utf-8')
print(json.dumps(d),flush=True)

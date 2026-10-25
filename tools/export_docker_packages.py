"""Save exact Docker package versions using existing APT metadata, without installing."""
import concurrent.futures
import hashlib
import json
import subprocess
import urllib.request
from prepare_backup import ROOT,inventory

remote=r'''
import json,subprocess
names=['docker-ce','docker-ce-cli','containerd.io','docker-buildx-plugin','docker-compose-plugin']
out=[]
for name in names:
 version=subprocess.check_output(['dpkg-query','-W','-f=${Version}',name],text=True).strip()
 raw=subprocess.check_output(['apt-cache','show',name+'='+version],text=True)
 fields={}
 for line in raw.splitlines():
  if ': ' in line and not line.startswith(' '):
   k,v=line.split(': ',1);fields.setdefault(k,v)
 out.append({k:fields.get(k) for k in ['Package','Version','Architecture','Filename','SHA256','Size','Depends']})
print(json.dumps(out))
'''
p=subprocess.run(inventory.SSH+['python3 -'],input=remote.encode(),capture_output=True,timeout=40)
if p.returncode:raise SystemExit('Could not obtain exact package metadata; raw output withheld')
packages=json.loads(p.stdout)
dest=ROOT/'deployment/docker-packages/ubuntu-22.04-amd64';dest.mkdir(parents=True,exist_ok=True)
def download(item):
    name=item['Filename']
    if not name or not name.startswith('dists/jammy/pool/stable/amd64/') or not item['SHA256']:
        raise RuntimeError('Package source is not the expected official Ubuntu 22.04 amd64 repository')
    url='https://download.docker.com/linux/ubuntu/'+name
    target=dest/name.rsplit('/',1)[-1]
    if not target.exists():
        partial=target.with_suffix('.deb.partial')
        req=urllib.request.Request(url,headers={'User-Agent':'Snow-Backup/1.0'})
        with urllib.request.urlopen(req,timeout=90) as response,partial.open('wb') as f:
            while chunk:=response.read(1024*1024):f.write(chunk)
        if hashlib.sha256(partial.read_bytes()).hexdigest()!=item['SHA256']:raise RuntimeError('Package checksum mismatch')
        partial.replace(target)
    assert hashlib.sha256(target.read_bytes()).hexdigest()==item['SHA256']
    item['url']=url;item['relative_path']=target.relative_to(ROOT/'deployment').as_posix()
    print(json.dumps({'downloaded':item['Package'],'bytes':target.stat().st_size}),flush=True)
    return item
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:result=list(pool.map(download,packages))
(ROOT/'deployment/docker-packages/manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(ROOT/'evidence/docker-packages.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('All five pinned Docker packages downloaded and SHA256 verified.',flush=True)

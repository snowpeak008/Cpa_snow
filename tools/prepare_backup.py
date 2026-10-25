"""Export a credential-free, pinned CPA reproduction kit. Never changes production."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
BASE = PROJECT / 'cpa-validation/github-backup-20261025'
spec = importlib.util.spec_from_file_location('inventory', BASE / 'inspect_production.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):h.update(chunk)
    return h.hexdigest()

def main():
    remote = inventory.REMOTE.replace('print(json.dumps(result))', '''
result['os_release']=pathlib.Path('/etc/os-release').read_text()
result['docker_version']=subprocess.check_output(['docker','version','--format','{{.Server.Version}}'],text=True).strip()
result['compose_version']=subprocess.check_output(['docker','compose','version','--short'],text=True).strip()
result['opt_directory_names']=[p.name for p in pathlib.Path('/opt').iterdir() if p.is_dir()]
result['image_size_bytes']=img.get('Size')
print(json.dumps(result))
''')
    p = subprocess.run(inventory.SSH + ['python3 -'], input=remote.encode(), capture_output=True, timeout=75)
    if p.returncode:raise RuntimeError('Read-only inventory failed; raw output withheld')
    data = json.loads(p.stdout)
    cfg = inventory.yaml.safe_load(data.pop('config_text'))
    compose = inventory.yaml.safe_load(data.pop('compose_text'))
    plugins = data.pop('plugins_raw')
    data['plugins'] = [{'id':v.get('id'), 'registered':v.get('registered'),
                        'enabled':v.get('effective_enabled'),
                        'version':(v.get('metadata') or {}).get('version')} for v in plugins]
    data['concurrency'] = {k:data['concurrency'].get(k) for k in ('max_per_key','max_per_account','active_requests')}
    (ROOT/'evidence/live-inventory.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    (ROOT/'evidence/config.sanitized.yaml').write_text(inventory.yaml.safe_dump(inventory.scrub(cfg),allow_unicode=True,sort_keys=False),encoding='utf-8')
    (ROOT/'evidence/compose.sanitized.yaml').write_text(inventory.yaml.safe_dump(inventory.scrub(compose),allow_unicode=True,sort_keys=False),encoding='utf-8')
    old = json.loads((BASE/'production-inventory.json').read_text(encoding='utf-8'))
    if any(data[k]!=old[k] for k in ('config_sha256','compose_sha256')):
        raise RuntimeError('Live configuration differs from sanitized baseline; adapt template before continuing')
    source=BASE/'Cpa_snow'
    for item in data['libraries']:
        p=source/'runtime/plugins/linux/amd64'/item['name']
        if sha(p)!=item['sha256']:raise RuntimeError('Live plugin differs from archived source: '+item['name'])
    out=ROOT/'deployment'
    if out.exists():raise RuntimeError('Refusing to overwrite deployment package')
    out.mkdir()
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=source).decode().split('\0')
    for rel in filter(None,paths):
        src=source/rel;dst=out/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
    shutil.copy2(out/'runtime/panel/management.html',ROOT/'web/upstream-management.html')
    print(json.dumps({'ok':True,'image':data['runtime']['image'],'image_size_bytes':data['image_size_bytes'],
                      'docker_version':data['docker_version'],'compose_version':data['compose_version'],
                      'os_release':data['os_release'],'opt_directory_names':data['opt_directory_names'],
                      'plugins':data['plugins'],'copied_files':len(list(filter(None,paths)))}))

if __name__=='__main__':main()

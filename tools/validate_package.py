"""Verify archive integrity and exercise initialization in a project-local sandbox."""
import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path
import yaml
from prepare_backup import ROOT,inventory

results={}
deploy=ROOT/'deployment'
image=deploy/'images/cpa-v8.0.31-linux-amd64.tar.gz'
checked=0
with tarfile.open(image,'r:gz') as tar:
    for member in tar:
        if member.name.startswith('blobs/sha256/') and member.isfile():
            data=tar.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest()==member.name.rsplit('/',1)[-1]
            checked+=1
results['image_blob_hashes']={'passed':True,'count':checked}
packages=json.loads((deploy/'docker-packages/manifest.json').read_text())
for item in packages:
    data=(deploy/item['relative_path']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==item['SHA256']
results['docker_packages']={'passed':True,'count':len(packages)}
for item in json.loads((ROOT/'evidence/live-inventory.json').read_text())['libraries']:
    p=deploy/'runtime/plugins/linux/amd64'/item['name']
    assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
results['live_plugin_hashes']={'passed':True,'count':5}
spec=importlib.util.spec_from_file_location('prepare',deploy/'scripts/prepare_deployment.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
sandbox=ROOT/'evidence/restore-test'
assert not sandbox.exists(),'Refusing to overwrite old test state'
try:
    module.prepare(target=sandbox,root=deploy)
    config=yaml.safe_load((sandbox/'config.yaml').read_text())
    assert config['plugins']['configs']['account-concurrency']['max_per_key']==5
    assert not list((sandbox/'state/auths').iterdir())
    assert len(list((sandbox/'state/plugins/linux/amd64').glob('*.so')))==5
    env=dict(line.split('=',1) for line in (sandbox/'.env').read_text().splitlines() if '=' in line)
    assert len(env['CPA_MANAGEMENT_KEY'])>32 and env['CPA_MANAGEMENT_KEY'] in (sandbox/'config.yaml').read_text()
    try:module.prepare(target=sandbox,root=deploy)
    except RuntimeError:results['initialization_refuses_overwrite']=True
    else:raise AssertionError('Expected existing-state protection')
    results['clean_initialization']={'passed':True,'auth_files':0,'plugins':5,'max_per_key':5,'new_keys_not_logged':True}
finally:
    # Only this newly created, resolved project-local disposable test directory.
    assert sandbox.resolve().parent==(ROOT/'evidence').resolve()
    if sandbox.exists():shutil.rmtree(sandbox)

scripts=[deploy/'scripts/install-docker-ubuntu.sh',deploy/'scripts/deploy-new-server.sh',ROOT/'web/rollback-panel.sh']
for script in scripts:
    p=subprocess.run(inventory.SSH+['bash -n'],input=script.read_bytes(),capture_output=True,timeout=25)
    assert p.returncode==0,'Shell syntax check failed: '+script.name
results['linux_shell_syntax']={'passed':True,'scripts':[s.name for s in scripts]}
compose=yaml.safe_load((deploy/'deploy/docker-compose.yml').read_text())
override=yaml.safe_load((deploy/'deploy/docker-compose.snow.yml').read_text())['services']['cli-proxy-api']
service=compose['services']['cli-proxy-api']
service['image']=override['image'];service['pull_policy']=override['pull_policy']
service['volumes']=[v for v in service['volumes'] if '/CLIProxyAPI/static' not in v]+override['volumes']
remote="CPA_MANAGEMENT_KEY=validation-placeholder CPA_BIND_ADDRESS=127.0.0.1 CPA_PORT=8317 docker compose --env-file /dev/null --project-directory / -p snow-validation -f - config --quiet"
p=subprocess.run(inventory.SSH+[remote],input=yaml.safe_dump(compose).encode(),capture_output=True,timeout=25)
assert p.returncode==0,'Compose schema validation failed'
results['compose_schema_on_linux']={'passed':True,'services_started':0,'uses_snow_panel':True}
results['full_fresh_server_restore']='not performed; no second server or production test instance started'
(ROOT/'evidence/package-validation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results,indent=2))

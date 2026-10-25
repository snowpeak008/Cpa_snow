"""Create reproducible file checksums and one transport ZIP, excluding runtime secrets."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','__pycache__','.state','archives','restore-test','runs'}
def files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and not SKIP.intersection(p.relative_to(root).parts)
                  and not p.name.endswith('.partial'))
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

for p in [*ROOT.glob('*.cmd'),ROOT/'web/打开本地预览.cmd']:
    text=p.read_text(encoding='utf-8').replace('\r\n','\n')
    p.write_bytes(text.replace('\n','\r\n').encode('utf-8'))
deploy=ROOT/'deployment'
manifest=deploy/'metadata/portable-files.sha256.json'
hashes={p.relative_to(deploy).as_posix():sha(p) for p in files(deploy) if p!=manifest}
manifest.write_text(json.dumps(hashes,indent=2,ensure_ascii=False),encoding='utf-8')
subprocess.run([sys.executable,str(deploy/'scripts/verify_portable.py')],check=True)
simplified='--simplified' in sys.argv
archive=ROOT/('archives/Snow-Console-20261025-v2.zip' if simplified else 'archives/Snow-Console-20261025.zip');archive.parent.mkdir(exist_ok=True)
assert not archive.exists(),'Refusing to replace a completed archive'
sources=files(ROOT)
for p in sources:
    rel=p.relative_to(ROOT).as_posix()
    assert rel not in ('deployment/deploy/.env','deployment/deploy/config.yaml')
    assert not rel.startswith('deployment/deploy/state/')
    assert p.suffix.lower() not in ('.dpapi','.db','.sqlite','.key','.pem')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
    for p in sources:
        kind=zipfile.ZIP_STORED if p.suffix.lower() in ('.gz','.deb','.jpg','.png') else zipfile.ZIP_DEFLATED
        z.write(p,'Snow-Console/'+p.relative_to(ROOT).as_posix(),compress_type=kind)
with zipfile.ZipFile(archive) as z:assert z.testzip() is None,'ZIP CRC verification failed'
summary={'archive':archive.relative_to(ROOT).as_posix(),'bytes':archive.stat().st_size,
         'sha256':sha(archive),'files':len(sources),'zip_crc_check':True,
         'deployment_manifest_files':len(hashes),'oauth_credentials_included':False,
         'api_keys_included':False,'ssh_private_keys_included':False,'vpn_3xui_included':False}
(ROOT/('evidence/delivery-summary-v2.json' if simplified else 'evidence/delivery-summary.json')).write_text(json.dumps(summary,indent=2),encoding='utf-8')
(archive.with_suffix('.zip.sha256')).write_text(summary['sha256']+'  '+archive.name+'\n',encoding='ascii')
print(json.dumps(summary,indent=2))

"""Package the reviewed tracked checkout. No server connection or credential access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',version),'Invalid version'
subprocess.run([sys.executable,str(ROOT/'deployment/scripts/verify_portable.py')],check=True)
raw=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT)
files=[ROOT/p.decode('utf-8') for p in raw.split(b'\0') if p]
assert files,'No tracked files to package'
for path in files:
    rel=path.relative_to(ROOT)
    assert not path.is_symlink() and path.is_file(), 'Unsupported tracked file: '+str(rel)
    assert not {'.git','.state','archives','private','__pycache__'}.intersection(rel.parts),str(rel)
    assert 'auths' not in rel.parts or (path.name=='.gitkeep' and path.stat().st_size==0),str(rel)
    assert path.name not in ('.env','.env.local') and path.suffix.lower() not in ('.pem','.key','.dpapi','.db','.sqlite'),str(rel)
folder=ROOT/'archives';folder.mkdir(exist_ok=True)
archive=folder/f'Snow-Console-{version}.zip'
assert not archive.exists(),'Completed archive already exists; retain it or choose a new VERSION'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
    for p in files:
        kind=zipfile.ZIP_STORED if p.suffix.lower() in ('.gz','.deb','.png','.jpg') else zipfile.ZIP_DEFLATED
        z.write(p,f'Snow-Console-{version}/'+p.relative_to(ROOT).as_posix(),compress_type=kind)
with zipfile.ZipFile(archive) as z:assert z.testzip() is None,'ZIP verification failed'
with archive.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
print(json.dumps({'archive':str(archive),'sha256':digest,'files':len(files),'crc_ok':True}))

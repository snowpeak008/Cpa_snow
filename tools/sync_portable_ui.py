"""Sync a locally built page into the restore kit. Does not contact a server."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
page=ROOT/'web/management.html'
build=json.loads((ROOT/'evidence/branding-build.json').read_text(encoding='utf-8'))
digest=hashlib.sha256(page.read_bytes()).hexdigest()
assert digest==build['output_sha256'],'Rebuild management.html before syncing'
# Verify existing restore materials before updating the single intended file.
subprocess.run([sys.executable,str(ROOT/'deployment/scripts/verify_portable.py')],check=True)
relative='runtime/snow-panel/management.html'
shutil.copyfile(page,ROOT/'deployment'/relative)
manifest=ROOT/'deployment/metadata/portable-files.sha256.json'
data=json.loads(manifest.read_text(encoding='utf-8'));data[relative]=digest
manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Restore kit page synchronized: '+digest)

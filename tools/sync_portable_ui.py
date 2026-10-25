"""Sync a reviewed local UI into either repository layout. No network access."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deployment' if (ROOT / 'deployment/metadata/files.sha256.json').is_file() else ROOT
def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

page = ROOT / 'web/management.html'
build = json.loads((ROOT / 'evidence/branding-build.json').read_text(encoding='utf-8'))
assert digest(page) == build['output_sha256'], 'Rebuild before syncing'
manifests = [DEPLOY / 'metadata/files.sha256.json', DEPLOY / 'metadata/portable-files.sha256.json']
# Validate all original restore files before rewriting the intended UI entries.
for manifest in manifests:
    if not manifest.exists(): continue
    data = json.loads(manifest.read_text(encoding='utf-8'))
    for name, expected in data.items():
        target = (DEPLOY / name).resolve()
        assert target.is_relative_to(DEPLOY.resolve()), name
        assert digest(target) == expected, 'Existing file differs: '+name
targets = ['runtime/panel/management.html']
if (DEPLOY / 'runtime/snow-panel').is_dir(): targets.append('runtime/snow-panel/management.html')
for name in targets:
    shutil.copyfile(page, DEPLOY / name)
for manifest in manifests:
    if not manifest.exists(): continue
    data = json.loads(manifest.read_text(encoding='utf-8'))
    for name in targets:
        if name in data: data[name] = digest(DEPLOY / name)
    if 'metadata/files.sha256.json' in data:
        data['metadata/files.sha256.json'] = digest(manifests[0])
    write(manifest, data)
for script in ['verify_snapshot.py', 'verify_portable.py']:
    if (DEPLOY / 'scripts' / script).exists():
        subprocess.run([sys.executable, str(DEPLOY / 'scripts' / script)], check=True)
print(json.dumps({'synchronized': targets, 'sha256': digest(page)}))

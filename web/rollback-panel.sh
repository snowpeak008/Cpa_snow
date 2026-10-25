#!/usr/bin/env bash
# Restores only the pre-Snow static page. No container restart or configuration change.
set -euo pipefail
if [[ ${1:-} != --restore-original ]]; then
  echo 'Usage on the original server: bash rollback-panel.sh --restore-original'
  exit 0
fi
python3 - <<'PY'
import hashlib,os,pathlib,urllib.request
target=pathlib.Path('/opt/cpa/panel/management.html')
backup=pathlib.Path('/opt/cpa/panel-backups/snow-console-20261025-before.html')
expected_old='351c286e3a6bf986cb3d4a7763020c30fc8b8c8a97ee7455441b5badc647b4c2'
expected_new='c9be8aeb7f96934e2e88e95ec4c465357bca0e6affb5037f97be338caacc19ab'
sha=lambda b:hashlib.sha256(b).hexdigest()
data=backup.read_bytes()
assert sha(data)==expected_old,'Original backup checksum mismatch'
current=sha(target.read_bytes())
assert current in (expected_old,expected_new,'5efcaf38e363bc2c6b2341e1723ceabb1d8dff612467bcd1925b1617c4bd2d72'),'Page changed since rollout; refusing overwrite'
if current!=expected_old:
 tmp=target.with_name('.management-snow-rollback.tmp')
 with tmp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.chmod(tmp,target.stat().st_mode & 0o777);os.replace(tmp,target)
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open('http://127.0.0.1:8317/management.html',timeout=10) as r:
 assert r.status==200 and sha(r.read())==expected_old
print('Original management page restored and verified. No service restart.')
PY

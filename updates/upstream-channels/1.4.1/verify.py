import pathlib,json,hashlib
root=pathlib.Path(__file__).resolve().parent
manifest=json.loads((root/'files.sha256.json').read_text(encoding='utf-8'))
for rel,expected in manifest.items():
 p=(root/rel).resolve()
 assert p.is_relative_to(root) and p.is_file(),rel
 assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,rel
build=json.loads((root/'build.json').read_text(encoding='utf-8'))
assert hashlib.sha256((root/'management.html').read_bytes()).hexdigest()==build['ui_sha256']
assert hashlib.sha256((root/'linux-amd64/account-concurrency-v1.4.1-upstream-channels.so').read_bytes()).hexdigest()==build['plugin_sha256']
assert json.loads((root/'evidence/isolated-verification.json').read_text())['passed']
print('Upstream channel upgrade verified:',len(manifest),'files')

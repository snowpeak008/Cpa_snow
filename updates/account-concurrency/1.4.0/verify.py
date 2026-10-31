import hashlib,json,pathlib
root=pathlib.Path(__file__).resolve().parent
manifest=json.loads((root/'files.sha256.json').read_text())
for rel,want in manifest.items():
 p=(root/rel).resolve()
 assert p.is_relative_to(root) and p.is_file(),rel
 assert hashlib.sha256(p.read_bytes()).hexdigest()==want,rel
print('Upgrade package verified:',len(manifest),'files')

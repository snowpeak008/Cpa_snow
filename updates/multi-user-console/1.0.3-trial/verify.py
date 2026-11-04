import pathlib,json,hashlib
r=pathlib.Path(__file__).resolve().parent
m=json.loads((r/'files.sha256.json').read_text())
for name,expected in m.items():
 p=(r/name).resolve()
 assert p.is_relative_to(r) and p.is_file(),name
 assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,name
b=json.loads((r/'build.json').read_text())
for name,expected in b['runtime_sha256'].items():assert hashlib.sha256((r/name).read_bytes()).hexdigest()==expected,name
print('Independent trial package verified:',len(m),'files; native CPA is not connected.')

import getpass,hashlib
key=getpass.getpass('API Key (hidden, not saved): ').strip()
if not key:raise SystemExit('No Key entered')
print(hashlib.sha256(('cli-proxy-api:caller-scope:v1\0'+key).encode()).hexdigest())

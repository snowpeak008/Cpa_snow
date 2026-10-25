"""Initialize an empty local deployment directory; never start or restart services."""
import os
from pathlib import Path
import secrets
import shutil

ROOT = Path(__file__).resolve().parents[1]


def prepare(target=None, root=ROOT):
    root = Path(root)
    target = Path(target) if target is not None else root/'deploy'
    target.mkdir(parents=True,exist_ok=True)
    for name in ('config.yaml','.env','state'):
        if (target/name).exists():
            raise RuntimeError('Deployment state already exists; refusing to overwrite: '+name)
    text = (root/'deploy/config.example.yaml').read_text(encoding='utf-8')
    management = 'mgmt_' + secrets.token_hex(32)
    client = 'sk-local-' + secrets.token_hex(32)
    text = text.replace('REPLACE_WITH_LOCAL_MANAGEMENT_KEY',management).replace('REPLACE_WITH_LOCAL_CLIENT_KEY',client)
    if 'REPLACE_' in text:
        raise RuntimeError('Unexpected unfilled placeholder in configuration')
    previous = os.umask(0o077)
    try:
        (target/'state/auths').mkdir(parents=True)
        (target/'state/logs').mkdir()
        shutil.copytree(root/'runtime/plugins',target/'state/plugins')
        (target/'config.yaml').write_text(text,encoding='utf-8')
        (target/'.env').write_text('CPA_BIND_ADDRESS=127.0.0.1\nCPA_PORT=8317\nCPA_MANAGEMENT_KEY='+management+
                                 '\nCPA_CLIENT_API_KEY='+client+'\nDEPLOY=\n',encoding='utf-8')
    finally:
        os.umask(previous)
    print('Prepared local configuration and fresh credentials in: '+str(target))
    print('Credentials are in .env; they are not printed or committed. No service was started.')


if __name__ == '__main__':
    prepare()

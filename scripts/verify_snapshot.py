"""Read-only SHA256 verification for the archived files."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    manifest = json.loads((ROOT/'metadata/files.sha256.json').read_text(encoding='utf-8'))
    failures = []
    for relative, expected in manifest.items():
        file = (ROOT/relative).resolve()
        if not file.is_relative_to(ROOT.resolve()) or not file.is_file():
            failures.append(relative)
        elif hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            failures.append(relative)
    if failures:
        raise SystemExit('Snapshot differs: '+', '.join(failures))
    print('Verified '+str(len(manifest))+' files. No service or account was changed.')


if __name__ == '__main__':
    verify()

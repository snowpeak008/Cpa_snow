"""Verify the immutable portable package files; ignores newly created runtime state."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
    manifest=json.loads((ROOT/'metadata/portable-files.sha256.json').read_text(encoding='utf-8'))
    failures=[]
    for rel,expected in manifest.items():
        p=(ROOT/rel).resolve()
        if not p.is_relative_to(ROOT.resolve()) or not p.is_file():failures.append(rel);continue
        h=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=expected:failures.append(rel)
    if failures:raise SystemExit('Hash verification failed: '+', '.join(failures))
    print('Portable package verified: %s files.'%len(manifest))
if __name__=='__main__':main()

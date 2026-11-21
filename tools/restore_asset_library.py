"""Restore preserved optional assets byte-for-byte, without changing existing files."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = '67a243faaddf9cd9ca88b4bf9feb624df6476f8e'
SOURCE_BRANCH = 'codex/asset-library-preservation-20261121'

def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True).stdout

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Fetch the preserved public source ref before restoring')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'asset-library/library-manifest.json').read_text(encoding='utf-8'))
    if manifest['source_commit'] != SOURCE_COMMIT:
        raise ValueError('Unexpected preservation commit')
    if args.fetch:
        remote = git('remote', 'get-url', 'origin').decode().strip()
        allowed = ('https://github.com/m8appz-dotcom/longform-video-engine.git', 'https://github.com/m8appz-dotcom/longform-video-engine', 'git@github.com:m8appz-dotcom/longform-video-engine.git')
        if remote not in allowed:
            raise ValueError('Inspect origin before fetching the preservation ref')
        git('fetch', 'origin', 'refs/heads/'+SOURCE_BRANCH)
    git('cat-file', '-e', SOURCE_COMMIT+'^{commit}')
    restored = 0
    for record in manifest['files']:
        rel = PurePosixPath(record['path'])
        if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != 'asset-library':
            raise ValueError('Unsafe asset path')
        if not re.fullmatch(r'[a-f0-9]{64}', record['sha256']):
            raise ValueError('Invalid content digest')
        dest = (ROOT/Path(*rel.parts)).resolve()
        if not dest.is_relative_to((ROOT/'asset-library').resolve()):
            raise ValueError('Asset destination leaves library')
        if dest.exists():
            if not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('Preserving modified local asset: '+record['path'])
            continue
        data = git('show', SOURCE_COMMIT+':'+rel.as_posix())
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Preserved content failed integrity check')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        restored += 1
    print(json.dumps({'verifiedFiles':len(manifest['files']), 'restored':restored, 'byteForByte':True}))

if __name__ == '__main__':
    main()

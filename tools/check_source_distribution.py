"""Verify that the tracked source distribution excludes optional media."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'asset-library/README.md', 'asset-library/library-manifest.json'}

def main():
    result = subprocess.run(
        ['git', 'ls-files', '-z', '--', 'asset-library/'],
        cwd=ROOT, check=True, capture_output=True,
    )
    tracked = set(filter(None, result.stdout.decode('utf-8').split('\0')))
    unexpected = sorted(tracked - ALLOWED)
    missing = sorted(ALLOWED - tracked)
    if unexpected or missing:
        raise SystemExit(f'Unexpected tracked library files: {unexpected}; missing source manifests: {missing}')
    print('Lightweight source distribution verified: README and manifest only.')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Make the zip that gets submitted, and record exactly what is inside it.

The zip is the artefact a reviewer opens, so the evidence has to be about the zip
and not about the working tree. This writes evidence/dist.json with a sha256 per
entry, which is what tools/readme_test.py compares the shipped files against.
"""
import hashlib
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = 'internal-link-audit'
SRC = os.path.join(HERE, 'plugin')
# Screenshots live in SVN /assets, not in the plugin zip: shipping them would put
# 100 KB of pictures into every install for no reason.
SKIP = {'.DS_Store'}


def main():
    ver = None
    for ln in open(os.path.join(SRC, '%s.php' % SLUG), encoding='utf-8'):
        if ln.strip().startswith('* Version:'):
            ver = ln.split(':', 1)[1].strip()
            break
    if not ver:
        print('no Version header'); return 2
    out_dir = os.path.join(HERE, 'dist')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, '%s-%s.zip' % (SLUG, ver))
    entries = []
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(SRC):
            dirs[:] = sorted(d for d in dirs if d != '__pycache__')
            for f in sorted(files):
                if f in SKIP:
                    continue
                full = os.path.join(base, f)
                rel = os.path.relpath(full, SRC)
                arc = '%s/%s' % (SLUG, rel)
                z.write(full, arc)
                entries.append({'name': arc, 'bytes': os.path.getsize(full),
                                'sha256': hashlib.sha256(open(full, 'rb').read()).hexdigest()})
    man = {'file': os.path.relpath(out, HERE), 'version': ver,
           'bytes': os.path.getsize(out),
           'sha256': hashlib.sha256(open(out, 'rb').read()).hexdigest(),
           'entries': entries}
    with open(os.path.join(HERE, 'evidence', 'dist.json'), 'w') as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print(json.dumps({'file': man['file'], 'bytes': man['bytes'],
                      'entries': [e['name'] for e in entries]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())

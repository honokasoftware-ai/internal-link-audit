#!/usr/bin/env python3
"""Download the published GitHub release asset as a logged out stranger and record it.

Why this exists (2026-10-04): the repository now tells people to install the plugin
from the Releases page, which is a claim about a file sitting on somebody else's
server. evidence/dist.json only proves that the zip on this disk matches the files on
this disk. It cannot notice a release that was never uploaded, a draft release nobody
outside can see, a tag pointing at the wrong commit, or a zip that was rebuilt here
after the upload. Those are exactly the ways the install instruction goes stale.

So: fetch the release anonymously, hash the bytes that actually came back, and write
evidence/release_asset.json. readme_test R29 refuses to pass unless that record shows a
published (not draft, not prerelease) release tagged for the shipped version whose
asset hashes to the zip we built.

No token is used on purpose. A private or draft release answers a logged out reader
with 404, and 404 is the honest answer to "can a stranger install this".

Usage: python3 tools/check_release_asset.py
"""
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHP = os.path.join(ROOT, 'plugin', 'honoka-internal-link-audit.php')
DIST = os.path.join(ROOT, 'evidence', 'dist.json')
OUT = os.path.join(ROOT, 'evidence', 'release_asset.json')
UA = {'User-Agent': 'Honoka-Software-release-check/1.0'}


def header(php, field):
    m = re.search(r'^\s*\*\s*%s:\s*(\S+)\s*$' % re.escape(field), php, re.M)
    return m.group(1) if m else None


def get(url, binary=False):
    req = urllib.request.Request(url, method='GET', headers=dict(UA))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.geturl(), (r.read() if binary else r.read(400000))
    except urllib.error.HTTPError as e:
        return e.code, url, b''


def main():
    php = open(PHP, encoding='utf-8').read()
    version = header(php, 'Version')
    uri = header(php, 'Plugin URI')
    if not version or not uri:
        print('the header is missing Version or Plugin URI', file=sys.stderr)
        return 3
    repo = uri.rstrip('/').split('github.com/', 1)[-1]
    tag = 'v' + version

    status, _, body = get('https://api.github.com/repos/%s/releases/tags/%s' % (repo, tag))
    rec = {
        'repo': repo,
        'tag': tag,
        'version': version,
        'api_status': status,
        # No Authorization header is sent, so everything here is what a logged out
        # reader sees. A draft release would answer 404 to this request.
        'anonymous': True,
        'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    if status == 200:
        rel = json.loads(body)
        rec['draft'] = bool(rel.get('draft'))
        rec['prerelease'] = bool(rel.get('prerelease'))
        rec['html_url'] = rel.get('html_url')
        rec['target_sha'] = None
        assets = rel.get('assets') or []
        rec['asset_names'] = [a.get('name') for a in assets]
        want = os.path.basename(json.loads(open(DIST, encoding='utf-8').read())['file'])
        hit = next((a for a in assets if a.get('name') == want), None)
        if hit:
            dstatus, final, blob = get(hit['browser_download_url'], binary=True)
            rec['asset'] = want
            rec['download_status'] = dstatus
            rec['download_url'] = hit['browser_download_url']
            # The redirect lands on a signed, short lived URL. Only the host and
            # path go in the record: the query string is a one hour credential and
            # does not belong in a committed file.
            import urllib.parse as _up
            _u = _up.urlsplit(final)
            rec['final_host_path'] = _u.netloc + _u.path
            rec['downloaded_bytes'] = len(blob)
            rec['downloaded_sha256'] = hashlib.sha256(blob).hexdigest() if blob else None
            rec['asset_state'] = hit.get('state')
        else:
            rec['asset'] = None
            rec['expected_asset'] = want
        # The tag has to exist and point at a real commit. It deliberately is NOT
        # compared against HEAD: a release tag is supposed to stay behind as work
        # continues, so "tag == HEAD" would turn false on the next commit and say
        # nothing about the release. The claim worth checking is the other one, that
        # the zip people download is the code the tag shows. So fetch each shipped
        # file from the tag and hash it against evidence/dist.json.
        tstatus, _, tbody = get('https://api.github.com/repos/%s/git/ref/tags/%s' % (repo, tag))
        if tstatus == 200:
            rec['target_sha'] = json.loads(tbody).get('object', {}).get('sha')
        rec['tag_commit_status'] = tstatus
        entries = json.loads(open(DIST, encoding='utf-8').read()).get('entries', [])
        files, match = [], True
        for e in entries:
            inner = e['name'].split('/', 1)[1]
            fstatus, _, blob = get('https://raw.githubusercontent.com/%s/%s/plugin/%s'
                                   % (repo, tag, inner), binary=True)
            got = hashlib.sha256(blob).hexdigest() if fstatus == 200 else None
            files.append({'name': inner, 'status': fstatus, 'sha256': got,
                          'same_as_zip': got == e['sha256']})
            match = match and got == e['sha256']
        rec['tag_files'] = files
        rec['tag_files_match_zip'] = match

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rec, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if rec.get('download_status') == 200 else 1


if __name__ == '__main__':
    sys.exit(main())

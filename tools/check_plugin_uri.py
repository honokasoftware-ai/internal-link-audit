#!/usr/bin/env python3
"""Fetch the Plugin URI in the plugin header and record what the network actually said.

Why this exists (2026-10-03): the header carried a Plugin URI whose repository
returned 404. Nothing in the test suite could notice, because every check read the
header and compared it against another string we had written ourselves. A URL is a
claim about the outside world, so only the outside world can confirm it. This writes
evidence/plugin_uri.json; readme_test R28 refuses to pass unless that file shows a
200 for the exact URL the header carries today.

Usage: python3 tools/check_plugin_uri.py
"""
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHP = os.path.join(ROOT, 'plugin', 'honoka-internal-link-audit.php')
OUT = os.path.join(ROOT, 'evidence', 'plugin_uri.json')


def header_uri(php):
    m = re.search(r'^\s*\*\s*Plugin URI:\s*(\S+)\s*$', php, re.M)
    return m.group(1) if m else None


def main():
    uri = header_uri(open(PHP, encoding='utf-8').read())
    if not uri:
        print('no Plugin URI in the header; nothing to measure', file=sys.stderr)
        return 3
    req = urllib.request.Request(uri, method='GET',
                                 headers={'User-Agent': 'Honoka-Software-link-check/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, final = r.status, r.geturl()
            body = r.read(200000).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        status, final, body = e.code, uri, ''
    rec = {
        'uri': uri,
        'status': status,
        'final_url': final,
        # A repository that exists but is private also 404s to an anonymous reader,
        # so "200" here means "a logged out stranger can open it", which is the only
        # thing the header promises.
        'anonymous': True,
        # the repository name, not the plugin slug: the plugin was renamed to
        # honoka-internal-link-audit on 2026-10-07 but the repository was not
        'title_seen': bool(re.search(r'internal-link-audit', body, re.I)),
        'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rec, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if status == 200 else 1


if __name__ == '__main__':
    sys.exit(main())

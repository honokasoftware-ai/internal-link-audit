#!/usr/bin/env python3
"""Break the plugin on purpose and check that tools/harness.py notices.

A green test suite is worth nothing until you have seen it go red for the right
reason. Each entry below removes exactly one rule the plugin claims to follow,
reinstalls the plugin in the live sandbox, re-runs the whole HTTP scan, and records
which checks failed. A rule nobody is watching shows up here as NO FANGS.

Two entries are not sabotage:
  * one is a deliberate no-op (a rewrite that changes bytes but not meaning). It
    must come back 15/15. Without it, "all checks passed" could not be told apart
    from "the harness is asleep".
  * one is an invariance: shrinking the batch size must change how many requests
    the scan takes without changing a single number.

    python3 tools/teeth_test.py           # needs the sandbox up and harness.py all run once

Note that this rewrites plugin/internal-link-audit.php and puts it back. The
original is kept in plugin/.internal-link-audit.php.orig until the run ends.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import harness                                              # noqa: E402

MAIN = os.path.join(HERE, 'plugin', 'internal-link-audit.php')
BACKUP = os.path.join(HERE, 'plugin', '.internal-link-audit.php.orig')

# name, old, new, which checks should fail, kind
CASES = [
    ('S1 a self link rescues the post',
     'if ( $id && $id !== (int) $post->ID ) {',
     'if ( $id ) {',
     ['V10 self link does not rescue'], 'sabotage'),
    ('S2 HTML comments are counted',
     "\t$html = preg_replace( '/<!--.*?(?:-->|$)/s', '', $html );\n",
     '',
     ['V9 HTML comments ignored'], 'sabotage'),
    ('S3 read stored content, not the rendered page',
     "$html = (string) apply_filters( 'the_content', $post->post_content );",
     '$html = (string) $post->post_content;',
     ['V8 the_content filters ran'], 'sabotage'),
    ('S4 alt="" is reported as missing',
     '\'/\\balt\\s*=\\s*(?:"[^"]*"|\\\'[^\\\']*\\\'|[^\\s"\\\'>][^\\s>]*)/i\'',
     '\'/\\balt\\s*=\\s*(?:"[^"]+"|\\\'[^\\\']+\\\'|[^\\s"\\\'>][^\\s>]*)/i\'',
     ['V4 images', 'V11 empty alt is not missing'], 'sabotage'),
    ('S5 tel: and mailto: count as internal links',
     "\tif ( '' !== $scheme && 'http' !== $scheme && 'https' !== $scheme ) {\n\t\treturn false;\n\t}\n",
     '',
     ['V5 internal links total'], 'sabotage'),
    ('S6 only double quoted href is read',
     '\'/<a[ \\t\\r\\n\\f][^>]*?\\bhref\\s*=\\s*(?:"([^"]*)"|\\\'([^\\\']*)\\\'|([^\\s"\\\'>\\\\\\\\][^\\s"\\\'>]*))/i\'',
     '\'/<a[ \\t\\r\\n\\f][^>]*?\\bhref\\s*=\\s*(?:"([^"]*)")/i\'',
     ['V5 internal links total'], 'sabotage'),
    ('S7 pages are scanned as well as posts',
     "\t\t\t'post_type'        => 'post',",
     "\t\t\t'post_type'        => array( 'post', 'page' ),",
     ['V1 posts read'], 'sabotage'),
    ('S8 the mean is shown where the median is promised',
     "\t\t$median = ( 0 === $n % 2 )\n\t\t\t? ( $internal[ $n / 2 - 1 ] + $internal[ $n / 2 ] ) / 2\n\t\t\t: (float) $internal[ ( $n - 1 ) / 2 ];",
     '\t\t$median = array_sum( $internal ) / $n;',
     ['V6 internal links median'], 'sabotage'),
    ('S11 the plugin trusts WordPress to have checked the capability',
     "\tif ( ! current_user_can( 'manage_options' ) ) {\n"
     "\t\twp_die( esc_html__( 'You do not have permission to view this report.',"
     " 'internal-link-audit' ) );\n\t}\n",
     '',
     ['V24 the plugin refuses on its own'], 'sabotage'),
    ('S12 the screen is registered at a capability a reader has',
     "\t\t'manage_options',\n\t\tILAUDIT_SLUG,",
     "\t\t'read',\n\t\tILAUDIT_SLUG,",
     ['V23 the menu item is not shown to them'], 'sabotage'),
    ('S9 a rewrite that changes nothing',
     "\t\t$state['done']++;",
     "\t\t$state['done'] = $state['done'] + 1;",
     [], 'no-op'),
    ('S10 two posts per request instead of a hundred',
     "define( 'ILAUDIT_BATCH', 100 );",
     "define( 'ILAUDIT_BATCH', 2 );",
     [], 'invariance'),
]


def run_once():
    harness.install_plugin()
    html, rounds = harness.run_scan()
    gate = harness.permission_gate(html)
    checks = harness.verify(html, rounds, gate)
    return rounds, checks


def main():
    shutil.copy(MAIN, BACKUP)
    original = open(MAIN, encoding='utf-8').read()
    results = []
    try:
        base_rounds, base_checks = run_once()
        base_failed = [c['name'] for c in base_checks if not c['ok']]
        if base_failed:
            print('the unmodified plugin does not pass: %s' % base_failed)
            return 2
        print('baseline %d/%d in %d request(s)\n' % (len(base_checks), len(base_checks), base_rounds))

        for name, old, new, expect, kind in CASES:
            if old not in original:
                results.append({'case': name, 'kind': kind, 'verdict': 'BROKEN TEST',
                                'why': 'the text this case edits is no longer in the plugin'})
                continue
            if original.count(old) != 1:
                results.append({'case': name, 'kind': kind, 'verdict': 'BROKEN TEST',
                                'why': 'the text this case edits appears %d times' % original.count(old)})
                continue
            open(MAIN, 'w', encoding='utf-8').write(original.replace(old, new, 1))
            rounds, checks = run_once()
            failed = [c['name'] for c in checks if not c['ok']]
            r = {'case': name, 'kind': kind, 'rounds': rounds,
                 'failed': failed, 'expected_to_fail': expect}
            if kind == 'sabotage':
                if not failed:
                    r['verdict'] = 'NO FANGS'
                elif sorted(failed) == sorted(expect):
                    r['verdict'] = 'CAUGHT'
                else:
                    r['verdict'] = 'CAUGHT, other checks too'
            elif kind == 'no-op':
                r['verdict'] = 'NO-OP CONFIRMED' if not failed else 'NOT A NO-OP'
            else:  # invariance
                ok = (not failed) and rounds > base_rounds
                r['verdict'] = 'HELD' if ok else 'BROKE'
                r['why'] = 'rounds %d vs baseline %d, failures %s' % (rounds, base_rounds, failed)
            results.append(r)
            print('%-18s %s' % (r['verdict'], name))
            if failed:
                print('                   failed: %s' % ', '.join(failed))
    finally:
        open(MAIN, 'w', encoding='utf-8').write(original)
        os.remove(BACKUP)
        harness.install_plugin()

    sab = [r for r in results if r['kind'] == 'sabotage']
    caught = [r for r in sab if r['verdict'].startswith('CAUGHT')]
    exact = [r for r in sab if r['verdict'] == 'CAUGHT']
    out = {'sabotages': len(sab), 'caught': len(caught), 'caught_exactly': len(exact),
           'results': results}
    json.dump(out, open(os.path.join(HERE, 'evidence', 'teeth.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\nfangs %d/%d sabotages caught (%d of them hit exactly the expected checks)'
          % (len(caught), len(sab), len(exact)))
    for r in results:
        if r['kind'] != 'sabotage':
            print('%s: %s' % (r['case'], r['verdict']))
    bad = [r for r in results if r['verdict'] in ('NO FANGS', 'BROKEN TEST', 'NOT A NO-OP', 'BROKE')]
    return 0 if not bad else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the WordPress.org Plugin Review Team's own tool against this plugin.

Why this exists: everything else in tools/ is a check we wrote. The directory a
submission is judged against has its own, and it is a published plugin
("plugin-check", PCP) maintained by the Plugin Review Team. Reading their
guidelines and grading ourselves is not the same measurement as running their
grader, and a rejection costs weeks in a review queue.

It found two real things on 2026-10-04, the day before this plugin was due to be
submitted (see evidence/plugin_check-before.json):

  ERROR   suppress_filters => true is prohibited
  WARNING a plugin should not invoke the core hook the_content

The warning was not a style note. Running the the_content chain meant any other
plugin hooked there wrote part of our report: on a seven post fixture with one
related posts plugin active, 8 internal links became 15, 7 images became 14, and
an orphaned post stopped looking orphaned. harness.py checks V25 and V26 now hold
that shut.

    python3 tools/plugin_check.py            # check, write evidence, fail on any finding
    python3 tools/plugin_check.py --prove     # put the two old defects back and
                                              # confirm PCP still reports them

--prove is the part that matters most. A checker that cannot be made to speak is
indistinguishable from one that is broken, and this one runs inside a container
we built, against a plugin we installed, so there are several ways for it to go
quiet without saying so.

Needs tools/wp-sandbox to be up (../../tools/wp-sandbox/up.sh).
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'honoka-wp-sandbox')
NET, WP, DB = 'honoka-wp-net', 'honoka-wp', 'honoka-wp-db'
SLUG = 'honoka-internal-link-audit'
MAIN = os.path.join(HERE, 'plugin', 'honoka-internal-link-audit.php')

# The two findings of 2026-10-04, as the edits that bring them back.
DEFECTS = [
    ('the_content is invoked by the plugin',
     '$html = do_shortcode( do_blocks( (string) $post->post_content ) );',
     "$html = (string) apply_filters( 'the_content', $post->post_content );",
     'WordPress.NamingConventions.PrefixAllGlobals.NonPrefixedHooknameFound'),
    ('query filters are suppressed',
     "'suppress_filters' => false,",
     "'suppress_filters' => true,",
     'WordPressVIPMinimum.Performance.WPQueryParams.SuppressFilters_suppress_filters'),
]


def sh(cmd, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.stderr.write('failed (%d): %s\n%s\n%s\n' % (p.returncode, ' '.join(cmd), p.stdout, p.stderr))
        raise SystemExit(2)
    return p


def wpcli(args, check=True):
    pw = open(os.path.join(WORK, '.pw')).read().strip()
    return sh(['docker', 'run', '--rm', '--network', NET, '--volumes-from', WP, '--user', '33:33',
               '-e', 'WORDPRESS_DB_HOST=%s' % DB, '-e', 'WORDPRESS_DB_USER=root',
               '-e', 'WORDPRESS_DB_PASSWORD=%s' % pw, '-e', 'WORDPRESS_DB_NAME=wordpress',
               'wordpress:cli', 'wp'] + args, check=check)


def install_pcp():
    """Install the Plugin Review Team's checker, from wordpress.org, if it is not here."""
    p = wpcli(['plugin', 'get', 'plugin-check', '--field=version'], check=False)
    if p.returncode != 0:
        wpcli(['plugin', 'install', 'plugin-check', '--activate'])
        p = wpcli(['plugin', 'get', 'plugin-check', '--field=version'])
    else:
        wpcli(['plugin', 'activate', 'plugin-check'], check=False)
    return p.stdout.strip()


def install_plugin():
    dest = '%s:/var/www/html/wp-content/plugins/%s' % (WP, SLUG)
    sh(['docker', 'exec', WP, 'rm', '-rf', '/var/www/html/wp-content/plugins/%s' % SLUG])
    sh(['docker', 'cp', os.path.join(HERE, 'plugin'), dest])
    sh(['docker', 'exec', WP, 'chown', '-R', '33:33',
        '/var/www/html/wp-content/plugins/%s' % SLUG])


ARGS = ['plugin', 'check', SLUG, '--format=json', '--include-experimental',
        '--include-low-severity-errors', '--include-low-severity-warnings',
        '--slug=%s' % SLUG]


def check():
    """Run PCP and hand back its findings as a list."""
    install_plugin()
    p = wpcli(ARGS, check=False)
    out = p.stdout.strip()
    if out.startswith('Success'):
        return []
    start = out.find('[')
    if start < 0:
        sys.stderr.write('could not read PCP output:\n%s\n%s\n' % (out, p.stderr))
        raise SystemExit(2)
    return json.loads(out[start:])


def one_line(f):
    return '%s %s line %s: %s' % (f.get('type'), f.get('code'), f.get('line'),
                                  (f.get('message') or '')[:120])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prove', action='store_true',
                    help='put the 2026-10-04 defects back one at a time and check PCP reports them')
    a = ap.parse_args()

    pcp = install_pcp()
    wp = wpcli(['core', 'version']).stdout.strip()
    php = sh(['docker', 'exec', WP, 'php', '-r', 'echo PHP_VERSION;']).stdout.strip()
    env = {'pcp_version': pcp, 'wp_version': wp, 'php_version': php,
           'command': 'wp ' + ' '.join(ARGS)}

    if not a.prove:
        findings = check()
        rec = dict(env, findings=findings, count=len(findings),
                   errors=sum(1 for f in findings if f.get('type') == 'ERROR'),
                   warnings=sum(1 for f in findings if f.get('type') == 'WARNING'))
        with open(os.path.join(HERE, 'evidence', 'plugin_check.json'), 'w') as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        print('plugin-check %s on WordPress %s / PHP %s' % (pcp, wp, php))
        for f in findings:
            print('  ' + one_line(f))
        print('%d finding(s)' % len(findings))
        return 0 if not findings else 1

    original = open(MAIN, encoding='utf-8').read()
    results = []
    try:
        base = check()
        if base:
            print('the plugin as it stands is not clean, so --prove cannot tell '
                  'a reported defect from a pre-existing one:')
            for f in base:
                print('  ' + one_line(f))
            return 2
        for name, now, broken, code in DEFECTS:
            if original.count(now) != 1:
                results.append({'defect': name, 'verdict': 'BROKEN TEST',
                                'why': 'the text this case edits appears %d times'
                                       % original.count(now)})
                continue
            open(MAIN, 'w', encoding='utf-8').write(original.replace(now, broken, 1))
            got = check()
            codes = [f.get('code') for f in got]
            results.append({'defect': name, 'expected_code': code, 'got_codes': codes,
                            'verdict': 'REPORTED' if code in codes else 'MISSED'})
            print('%-12s %s' % (results[-1]['verdict'], name))
    finally:
        open(MAIN, 'w', encoding='utf-8').write(original)
        install_plugin()

    rec = dict(env, baseline_findings=0, proofs=results,
               reported=sum(1 for r in results if r['verdict'] == 'REPORTED'),
               total=len(results))
    with open(os.path.join(HERE, 'evidence', 'plugin_check_teeth.json'), 'w') as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print('\n%d/%d defects reported by plugin-check %s' % (rec['reported'], rec['total'], pcp))
    return 0 if rec['reported'] == rec['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

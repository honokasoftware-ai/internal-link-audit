#!/usr/bin/env python3
"""Check readme.txt against the code and the measurements, not against itself.

readme.txt is the listing. Every sentence in it is a claim made to people who have
not installed the plugin yet, so each number in it has to come from somewhere that
can be re-read: the plugin source, evidence/verify.json (the run on a real
WordPress) or evidence/screenshot.json (the picture on the listing). A readme that
only agreed with itself would pass no matter how wrong it was.

    python3 tools/readme_test.py              # check
    python3 tools/readme_test.py --sabotage   # break things on purpose and prove the checks bite

Nothing here needs Docker: it reads files. The run on a real WordPress is
tools/harness.py and its result is an input to this.
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = 'internal-link-audit'

REQUIRED_HEADERS = ['Contributors', 'Tags', 'Requires at least', 'Tested up to',
                    'Requires PHP', 'Stable tag', 'License', 'License URI']
REQUIRED_SECTIONS = ['Description', 'Installation', 'Frequently Asked Questions',
                     'Screenshots', 'Changelog']
# Guideline 7 forbids tracking. The readme says the plugin cannot talk out at all,
# so the names it would have to use must be absent from the source.
NETWORK_CALLS = ['wp_remote_get', 'wp_remote_post', 'wp_remote_request',
                 'wp_safe_remote_get', 'curl_init', 'fsockopen', 'file_get_contents(']
MONEY_WORDS = ['pro version', 'premium', 'upgrade to', 'license key', 'licence key',
               'trial', 'buy now', 'paypal', 'stripe']


class Checks(object):
    def __init__(self):
        self.rows = []

    def ck(self, name, got, want, why):
        ok = got == want
        self.rows.append({'name': name, 'got': got, 'want': want, 'ok': ok, 'why': why})
        return ok

    def failed(self):
        return [r['name'] for r in self.rows if not r['ok']]


def read(root, *parts):
    return io.open(os.path.join(root, *parts), encoding='utf-8').read()


def header_block(readme):
    """The lines between the === title === line and the first blank line."""
    lines = readme.split('\n')
    out = {}
    for ln in lines[1:]:
        if not ln.strip():
            break
        if ':' in ln:
            k, v = ln.split(':', 1)
            out[k.strip()] = v.strip()
    return out


def short_description(readme):
    """The one line after the header block, before the first == section ==."""
    body = readme.split('\n')
    i = 1
    while i < len(body) and body[i].strip():
        i += 1
    while i < len(body) and not body[i].strip():
        i += 1
    return body[i].strip() if i < len(body) else ''


def php_header(php):
    out = {}
    for m in re.finditer(r'^\s*\*\s*([A-Za-z][A-Za-z ]+?):\s+(.+?)\s*$', php[:php.find('*/')], re.M):
        out[m.group(1).strip()] = m.group(2).strip()
    return out


def define_of(php, name):
    m = re.search(r"define\(\s*'%s'\s*,\s*'?([^',)]+)'?\s*\)" % name, php)
    return m.group(1).strip() if m else None


def translatable(php):
    """Every literal passed to a gettext call with our text domain."""
    out = set()
    pat = re.compile(r"\b(?:esc_html__|esc_attr__|__|_e)\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*'%s'\s*\)" % SLUG)
    for m in pat.finditer(php):
        out.add(m.group(1).replace("\\'", "'").replace('\\\\', '\\'))
    return out


def pot_msgids(pot):
    out = set()
    for m in re.finditer(r'^msgid "((?:[^"\\]|\\.)*)"', pot, re.M):
        s = m.group(1)
        if s:
            out.add(s.replace('\\"', '"').replace('\\\\', '\\'))
    return out


def run(root, verbose=True):
    c = Checks()
    readme = read(root, 'plugin', 'readme.txt')
    php = read(root, 'plugin', '%s.php' % SLUG)
    pot = read(root, 'plugin', 'languages', '%s.pot' % SLUG)
    runs = []
    for fn in sorted(os.listdir(os.path.join(root, 'evidence'))):
        m = re.match(r'^verify-(\d+)\.(\d+)\.', fn)
        if m:
            d = json.loads(read(root, 'evidence', fn))
            if d.get('passed') == d.get('total'):           # a failed run is not a version we support
                runs.append((int(m.group(1)), int(m.group(2)), d))
    runs.sort()
    shot = json.loads(read(root, 'evidence', 'screenshot.json'))
    h, ph = header_block(readme), php_header(php)

    c.ck('R1 required headers', sorted(k for k in REQUIRED_HEADERS if k in h),
         sorted(REQUIRED_HEADERS), 'the listing will not build without these')
    c.ck('R2 stable tag is the shipped version', h.get('Stable tag'), ph.get('Version'),
         'a stable tag that is not the version in the file ships the wrong code')
    c.ck('R3 requires at least agrees with the code', h.get('Requires at least'),
         ph.get('Requires at least'), 'two places state the same minimum')
    c.ck('R4 requires php agrees with the code', h.get('Requires PHP'), ph.get('Requires PHP'),
         'same')
    c.ck('R5 tested up to is the newest version we ran on', h.get('Tested up to'),
         '%d.%d' % runs[-1][:2] if runs else None,
         'evidence/verify-<version>.json records a full pass on that WordPress')
    c.ck('R24 requires at least is the oldest version we ran on', h.get('Requires at least'),
         '%d.%d' % runs[0][:2] if runs else None,
         'a minimum nobody tried is a guess, and this one was run: 24/24 on 6.0.3 with PHP 7.4.32')
    sd = short_description(readme)
    c.ck('R6 short description length', bool(sd) and len(sd) <= 150, True,
         'WordPress.org truncates over 150 characters, and a cut sentence reads as sloppy')
    c.ck('R7 at most five tags', len([t for t in h.get('Tags', '').split(',') if t.strip()]) <= 5,
         True, 'only the first five are used')
    c.ck('R8 required sections', sorted(s for s in REQUIRED_SECTIONS
                                        if ('== %s ==' % s) in readme),
         sorted(REQUIRED_SECTIONS), 'the listing tabs come from these')
    c.ck('R9 changelog covers the stable tag', ('= %s =' % h.get('Stable tag')) in readme, True,
         'a release with no changelog entry')

    shots = sorted(f for f in os.listdir(os.path.join(root, 'assets'))
                   if re.match(r'^screenshot-\d+\.png$', f)) if os.path.isdir(os.path.join(root, 'assets')) else []
    caps = re.findall(r'^(\d+)\.\s+\S', readme.split('== Screenshots ==')[-1].split('==')[0], re.M)
    c.ck('R10 one caption per screenshot file', (len(caps), len(shots)), (len(shots), len(shots)),
         'an uncaptioned image, or a caption for an image that is not in the zip')
    c.ck('R11 the screenshot is the one we took', shot.get('status'), 200,
         'the picture came from a real admin screen that answered 200')
    c.ck('R12 the screenshot file is the one measured',
         os.path.basename(shot.get('file', '')), 'screenshot-1.png',
         'the recorded hash has to belong to the file that ships')

    # The readme says six figures are on the summary. Count them on the picture's own screen.
    n_cells = len(shot.get('screen_cells') or {})
    said = re.search(r'summary of (\w+) figures', readme)
    words = {'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8}
    c.ck('R13 caption counts the figures that are there',
         words.get((said.group(1) if said else '').lower()), n_cells,
         'the caption describes the picture, and the picture is the screen')

    c.ck('R14 the privacy claim holds in the code',
         [n for n in NETWORK_CALLS if n in php], [],
         'guideline 7: the readme says it cannot talk out, so the names must be absent')
    # Comments are stripped first: the file's own promise that there is no trial must
    # not be what satisfies the check. And each word is matched with its edges, or
    # "striped" in a table class counts as Stripe.
    code = re.sub(r'/\*.*?\*/', ' ', php, flags=re.S)
    code = re.sub(r'(^|\s)//[^\n]*', ' ', code).lower()
    c.ck('R15 nothing is for sale in the code',
         [w for w in MONEY_WORDS
          if re.search(r'(?<![a-z])%s(?![a-z])' % re.escape(w), code)], [],
         'guideline 5: the readme says everything is free')
    c.ck('R16 post ceiling in the faq', re.search(r'([\d,]+) published posts\.', readme).group(1),
         '{:,}'.format(int(define_of(php, 'ILAUDIT_MAX_POSTS'))),
         'the number a buyer plans around')
    c.ck('R17 batch size in the installation steps',
         re.search(r'reads (\d+) posts per request', readme).group(1),
         define_of(php, 'ILAUDIT_BATCH'), 'same')
    c.ck('R18 the stored option is the one named',
         'ilaudit_state' in readme and define_of(php, 'ILAUDIT_STATE') == 'ilaudit_state', True,
         'the readme tells people what to delete')
    i = php.find('add_management_page(')
    cap = re.search(r"'(manage_[a-z_]+)'", php[i:i + 400]) if i >= 0 else None
    c.ck('R19 the capability the faq promises', cap.group(1) if cap else None, 'manage_options',
         'the readme says who can see the report')
    # R19 reads one argument in the source. R27 asks whether anybody ever sat in a
    # reader's chair and was turned away, which is what the FAQ sentence claims.
    promise = 'The screen refuses anyone else' in readme
    gates = [d.get('permission_gate') for _, _, d in runs if d.get('permission_gate')]
    served = sorted(r for g in gates for r, v in g['roles'].items()
                    if v['get_showed_report'] or v['post_showed_report'])
    c.ck('R27 the faq answer on who can see it was measured',
         (promise, len(gates) > 0, served,
          all(g['state_unchanged'] for g in gates),
          sorted({w for g in gates for w in g['own_guard_said']})),
         (True, True, [], True, ['plugin']),
         'a capability named in the source is not a refusal anyone observed; '
         'evidence/verify-<version>.json has to show a logged in non administrator '
         'being turned away and the scan not running for them')
    # R28: a URL in the header is a claim about somewhere else, so no amount of
    # reading our own files can confirm it. On 2026-10-03 the header pointed at a
    # repository that 404ed and every check still passed. The only admissible
    # evidence is a recorded fetch (tools/check_plugin_uri.py).
    uri = ph.get('Plugin URI')
    try:
        pu = json.loads(read(root, 'evidence', 'plugin_uri.json'))
    except Exception:
        pu = {}
    c.ck('R28 the plugin uri was opened and answered',
         (uri is not None, pu.get('uri'), pu.get('status'), pu.get('title_seen')),
         (True, uri, 200, True),
         'a header url nobody fetched can be a 404; evidence/plugin_uri.json has to '
         'show a 200 for this exact url with the repository name in the page')

    c.ck('R20 text domain matches the slug', ph.get('Text Domain'), SLUG,
         'translations load by slug on WordPress.org')

    strings, ids = translatable(php), pot_msgids(pot)
    c.ck('R21 every translatable string is in the pot', sorted(strings - ids), [],
         'a string missing from the pot can never be translated')
    c.ck('R22 the pot carries the right domain', ('X-Domain: %s' % SLUG) in pot, True,
         'wrong domain in the pot means the translations never load')
    dist_p = os.path.join(root, 'evidence', 'dist.json')
    dist = json.loads(read(root, 'evidence', 'dist.json')) if os.path.exists(dist_p) else {'entries': []}
    import hashlib
    stale = []
    for e in dist.get('entries', []):
        f = os.path.join(root, 'plugin', e['name'].split('/', 1)[1])
        now = hashlib.sha256(open(f, 'rb').read()).hexdigest() if os.path.exists(f) else None
        if now != e['sha256']:
            stale.append(e['name'])
    c.ck('R25 the zip holds the files as they are now', stale, [],
         'a zip built before the last edit submits code nobody checked')
    c.ck('R26 the zip carries the required files',
         sorted(e['name'].split('/', 1)[1] for e in dist.get('entries', [])),
         sorted(['%s.php' % SLUG, 'readme.txt', 'uninstall.php',
                 'languages/%s.pot' % SLUG]),
         'readme.txt and the main file are what the reviewer opens')

    c.ck('R23 no em dash in the listing', '—' in readme, False,
         'house style: an em dash is the surface marker we remove everywhere else')

    if verbose:
        for r in c.rows:
            print('%-4s %-46s got=%r want=%r  %s'
                  % ('PASS' if r['ok'] else 'FAIL', r['name'], r['got'], r['want'], r['why']))
        print('%d/%d' % (sum(1 for r in c.rows if r['ok']), len(c.rows)))
    return c


# ----------------------------------------------------------------- sabotage
def sab_stable_tag(root):
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt').replace('Stable tag: 1.0.0', 'Stable tag: 1.1.0')
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_tested_up(root):
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt').replace('Tested up to: 7.1', 'Tested up to: 9.9')
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_long_short_desc(root):
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt')
    old = short_description(s)
    io.open(p, 'w', encoding='utf-8').write(s.replace(old, old + ' ' + 'and more. ' * 12))


def sab_requires_lower(root):
    """Claim support for a WordPress nobody ever ran the plugin on."""
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt').replace('Requires at least: 6.0', 'Requires at least: 4.9')
    io.open(p, 'w', encoding='utf-8').write(s)
    p2 = os.path.join(root, 'plugin', '%s.php' % SLUG)
    s2 = read(root, 'plugin', '%s.php' % SLUG).replace('Requires at least: 6.0', 'Requires at least: 4.9')
    io.open(p2, 'w', encoding='utf-8').write(s2)


def sab_six_tags(root):
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt')
    io.open(p, 'w', encoding='utf-8').write(
        s.replace('Tags: internal links,', 'Tags: seo, internal links,'))


def sab_phone_home(root):
    p = os.path.join(root, 'plugin', '%s.php' % SLUG)
    s = read(root, 'plugin', '%s.php' % SLUG).replace(
        "add_action( 'admin_menu', 'ilaudit_menu' );",
        "add_action( 'admin_menu', 'ilaudit_menu' );\nwp_remote_get( 'https://example.org/ping' );")
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_ceiling_drift(root):
    p = os.path.join(root, 'plugin', '%s.php' % SLUG)
    s = read(root, 'plugin', '%s.php' % SLUG).replace("ILAUDIT_MAX_POSTS', 5000", "ILAUDIT_MAX_POSTS', 2000")
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_capability(root):
    p = os.path.join(root, 'plugin', '%s.php' % SLUG)
    s = read(root, 'plugin', '%s.php' % SLUG).replace("'manage_options',\n\t\tILAUDIT_SLUG",
                                                      "'edit_posts',\n\t\tILAUDIT_SLUG")
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_new_untranslated(root):
    """A new screen string that was added after the pot was last generated."""
    p = os.path.join(root, 'plugin', '%s.php' % SLUG)
    s = read(root, 'plugin', '%s.php' % SLUG).replace(
        "echo '<h2>' . esc_html__( 'Summary', 'internal-link-audit' ) . '</h2>",
        "echo '<p>' . esc_html__( 'A brand new sentence nobody translated.', 'internal-link-audit' ) . '</p>';\n\techo '<h2>' . esc_html__( 'Summary', 'internal-link-audit' ) . '</h2>")
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_caption_count(root):
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt').replace('summary of six figures', 'summary of eight figures')
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_stale_zip(root):
    """Edit the plugin after the zip was built, which is how a shipped file goes stale."""
    p = os.path.join(root, 'plugin', '%s.php' % SLUG)
    s = read(root, 'plugin', '%s.php' % SLUG).replace('ILAUDIT_BATCH', 'ILAUDIT_BATCH ')
    io.open(p, 'w', encoding='utf-8').write(s)


def sab_noop(root):
    """Changes bytes without changing meaning, and re-ships. Nothing may fail.

    The re-ship is part of the no-op: R25 compares the zip with the tree on purpose,
    so an edit that was never rebuilt is a real fault, not a no-op.
    """
    import hashlib
    p = os.path.join(root, 'plugin', 'readme.txt')
    s = read(root, 'plugin', 'readme.txt').replace('== Changelog ==', '== Changelog ==\n')
    io.open(p, 'w', encoding='utf-8').write(s)
    dp = os.path.join(root, 'evidence', 'dist.json')
    d = json.loads(io.open(dp, encoding='utf-8').read())
    for e in d['entries']:
        f = os.path.join(root, 'plugin', e['name'].split('/', 1)[1])
        e['sha256'] = hashlib.sha256(open(f, 'rb').read()).hexdigest()
        e['bytes'] = os.path.getsize(f)
    io.open(dp, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))


def sab_gate_served(root):
    """Record a run in which a reader was handed the report, and leave the promise standing."""
    for fn in os.listdir(os.path.join(root, 'evidence')):
        if not re.match(r'^verify-\d+\.\d+\.', fn):
            continue
        fp = os.path.join(root, 'evidence', fn)
        d = json.loads(io.open(fp, encoding='utf-8').read())
        g = d.get('permission_gate')
        if g:
            g['roles']['editor']['get_showed_report'] = True
            io.open(fp, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))


def sab_gate_unproved(root):
    """Delete the permission measurement but keep the sentence that depends on it."""
    for fn in os.listdir(os.path.join(root, 'evidence')):
        if not re.match(r'^verify-\d+\.\d+\.', fn):
            continue
        fp = os.path.join(root, 'evidence', fn)
        d = json.loads(io.open(fp, encoding='utf-8').read())
        d.pop('permission_gate', None)
        io.open(fp, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))


def sab_plugin_uri_404(root):
    """Point the header at a repository that does not exist, leaving the old evidence."""
    fp = os.path.join(root, 'plugin', '%s.php' % SLUG)
    t = io.open(fp, encoding='utf-8').read()
    io.open(fp, 'w', encoding='utf-8').write(
        t.replace('/internal-link-audit\n', '/internal-link-audit-does-not-exist\n', 1))


def sab_plugin_uri_unfetched(root):
    """Keep the url but throw away the proof that anyone ever opened it."""
    fp = os.path.join(root, 'evidence', 'plugin_uri.json')
    if os.path.exists(fp):
        os.remove(fp)


SABOTAGES = [
    ('S1 stable tag drifts from the version', sab_stable_tag, ['R2 stable tag is the shipped version', 'R9 changelog covers the stable tag']),
    ('S2 tested up to a version never run', sab_tested_up, ['R5 tested up to is the newest version we ran on']),
    ('S3 short description over the limit', sab_long_short_desc, ['R6 short description length']),
    ('S3b a minimum nobody ran', sab_requires_lower, ['R24 requires at least is the oldest version we ran on']),
    ('S4 a sixth tag', sab_six_tags, ['R7 at most five tags']),
    ('S5 the plugin starts phoning home', sab_phone_home, ['R14 the privacy claim holds in the code']),
    ('S6 the ceiling changes and the faq does not', sab_ceiling_drift, ['R16 post ceiling in the faq']),
    ('S7 the capability is loosened', sab_capability, ['R19 the capability the faq promises']),
    ('S8 a new string never reaches the pot', sab_new_untranslated, ['R21 every translatable string is in the pot']),
    ('S9b the zip is older than the code', sab_stale_zip, ['R25 the zip holds the files as they are now']),
    ('S9 the caption miscounts the picture', sab_caption_count, ['R13 caption counts the figures that are there']),
    ('S11 a reader was served the report', sab_gate_served, ['R27 the faq answer on who can see it was measured']),
    ('S12 the permission run is thrown away', sab_gate_unproved, ['R27 the faq answer on who can see it was measured']),
    ('S13 the header points at a repository that is not there', sab_plugin_uri_404, ['R28 the plugin uri was opened and answered']),
    ('S14 the url is claimed but never opened', sab_plugin_uri_unfetched, ['R28 the plugin uri was opened and answered']),
]


def sabotage():
    base = run(HERE, verbose=False)
    if base.failed():
        print('refusing to measure teeth: the real tree already fails %s' % base.failed())
        return 2
    out, caught = [], 0
    for name, fn, expect in SABOTAGES + [('S10 no-op rewrite', sab_noop, [])]:
        tmp = tempfile.mkdtemp(prefix='ilaudit-readme-')
        root = os.path.join(tmp, 'p')
        shutil.copytree(HERE, root, ignore=shutil.ignore_patterns('__pycache__', 'dist'))
        try:
            fn(root)
            failed = run(root, verbose=False).failed()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if expect:
            hit = sorted(set(failed) & set(expect)) == sorted(set(expect))
            verdict = ('CAUGHT' if sorted(failed) == sorted(expect) else
                       'CAUGHT, other checks too' if hit else 'MISSED')
            caught += 1 if hit else 0
        else:
            verdict = 'QUIET' if not failed else 'NOISE: a no-op made %s fail' % failed
        out.append({'case': name, 'failed': failed, 'expected': expect, 'verdict': verdict})
        print('%-28s %-24s failed=%s' % (name, verdict, failed))
    print('caught %d/%d' % (caught, len(SABOTAGES)))
    with io.open(os.path.join(HERE, 'evidence', 'readme_teeth.json'), 'w', encoding='utf-8') as f:
        json.dump({'sabotages': len(SABOTAGES), 'caught': caught, 'results': out}, f,
                  ensure_ascii=False, indent=1)
    return 0 if caught == len(SABOTAGES) and not out[-1]['failed'] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    a = ap.parse_args()
    if a.sabotage:
        return sabotage()
    c = run(HERE)
    with io.open(os.path.join(HERE, 'evidence', 'readme.json'), 'w', encoding='utf-8') as f:
        json.dump({'passed': sum(1 for r in c.rows if r['ok']), 'total': len(c.rows),
                   'checks': c.rows}, f, ensure_ascii=False, indent=1)
    return 0 if not c.failed() else 1


if __name__ == '__main__':
    sys.exit(main())

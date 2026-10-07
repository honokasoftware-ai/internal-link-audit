#!/usr/bin/env python3
"""Stand the plugin up in a real WordPress and check its screen against numbers computed by hand.

Why this shape: the only honest way to know what the plugin reports is to read the
screen an administrator actually sees. So the fixture is built with wp-cli, the scan
is driven over HTTP by logging in to wp-login.php and pressing the plugin's own
button, and the assertions compare the rendered table against a seven post fixture
whose every number is worked out by hand in EXPECTED below. Expected values are
never taken from the plugin's own output: that would be a tautology that passes no
matter what the plugin does.

    python3 tools/harness.py all          # seed, install, scan over HTTP, verify
    python3 tools/harness.py verify       # verify only (scan again, no reseed)

Needs tools/wp-sandbox to be up (../../tools/wp-sandbox/up.sh).
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.path.abspath(os.path.join(HERE, '..', '..', 'tools', 'wp-sandbox'))
WORK = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'honoka-wp-sandbox')
PORT = os.environ.get('PORT', '8901')
BASE = 'http://127.0.0.1:%s' % PORT
NET, WP, DB = 'honoka-wp-net', 'honoka-wp', 'honoka-wp-db'

# ---------------------------------------------------------------- fixture
# Seven published posts. Every link and image below is written out in full so the
# EXPECTED block underneath can be checked with a pencil.
IMG_NO_ALT = '<img src="/wp-content/uploads/a.png">'
IMG_ALT = '<img src="/wp-content/uploads/b.png" alt="a cat on a wall">'
IMG_EMPTY_ALT = '<img src="/wp-content/uploads/c.png" alt="">'

POSTS = [
    # slug, title, content
    ('alpha', 'Alpha',
     '<p><a href="/beta/">beta</a> and the same post again: '
     '<a href="/beta/#tips">beta tips</a></p>'
     '<p>%s %s</p>' % (IMG_ALT, IMG_NO_ALT)),
    ('beta', 'Beta',
     '<p><a href="/alpha/">alpha</a> <a href="/category/uncategorized/">the archive</a></p>'
     '<p><a href="tel:03-0000-0000">call us</a> '
     '<a href="#top">back to top</a> '
     '<a href="https://example.org/">an outside site</a></p>'),
    ('gamma', 'Gamma',
     '<p><a href="/gamma/">this very post</a> '
     '<a href="mailto:nobody@example.org">mail us</a> '
     '<a href="ftp://127.0.0.1/pub/price.zip">a download over ftp</a></p>'
     '<p>%s</p>' % IMG_EMPTY_ALT),
    ('delta', 'Delta', '<p>No links at all.</p><p>%s %s %s</p>' % (IMG_NO_ALT, IMG_NO_ALT, IMG_NO_ALT)),
    ('epsilon', 'Epsilon',
     '<p><a href="/category/uncategorized/">the archive</a> '
     "<a href='/alpha/'>alpha, written with single quotes</a></p>"
     '<!-- <p><a href="/eta/">eta</a></p> -->'),
    ('zeta', 'Zeta', '[fixture_link]'),
    ('eta', 'Eta', '<p>Nothing here links anywhere and there are no images.</p>'),
]

# Worked out by hand from POSTS above.
#   post      internal links out        images  no alt  posts linking to it
#   alpha     2 (both to beta)           2       1       2 (beta, epsilon)
#   beta      2 (alpha, an archive)      0       0       1 (alpha)
#   gamma     1 (itself)                 1       0       0  <- a self link is not a link to it
#   delta     0                          3       3       1 (zeta, via the shortcode)
#   epsilon   2 (an archive, alpha)      0       0       0
#   zeta      1 (delta)                  1       1       0
#   eta       0                          0       0       0
# tel:, mailto:, #top and example.org are not internal links. Neither is gamma's
# ftp:// link, even though its host is this very site: it is the only link in the
# fixture that the "only http and https" rule has to stop on its own.
# The link to /eta/ inside epsilon is in an HTML comment, so it is not on the page.
# Epsilon's link to alpha is written with single quotes, so a reader that only
# understands double quotes loses it.
# Totals: images 2+0+1+3+0+1+0 = 7, of which 1+0+0+3+0+1+0 = 5 have no alt.
# Internal links 2+2+1+0+2+1+0 = 8. Sorted per post: 0 0 1 1 2 2 2, so the middle
# post has 1. The mean would be 8/7 = 1.1, which is deliberately a different
# number from the median so that confusing the two shows up.
EXPECTED = {
    'posts': 7,
    'orphans': ['Epsilon', 'Eta', 'Gamma', 'Zeta'],   # sorted by title for comparison
    'orphan_count': 4,
    'images': 7,
    'images_no_alt': 5,
    'internal_sum': 8,
    'internal_med': '1.0',
    'zero_internal': 2,                               # delta and eta
}


def sh(cmd, **kw):
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)
    if p.returncode != 0:
        sys.stderr.write('command failed (%d): %s\n%s\n%s\n' % (p.returncode, cmd, p.stdout, p.stderr))
        raise SystemExit(2)
    return p.stdout.strip()


def wpcli(args):
    pw = open(os.path.join(WORK, '.pw')).read().strip()
    cmd = ['docker', 'run', '--rm', '--network', NET, '--volumes-from', WP, '--user', '33:33',
           '-e', 'WORDPRESS_DB_HOST=%s' % DB, '-e', 'WORDPRESS_DB_USER=root',
           '-e', 'WORDPRESS_DB_PASSWORD=%s' % pw, '-e', 'WORDPRESS_DB_NAME=wordpress',
           'wordpress:cli', 'wp'] + args
    return sh(cmd)


def wpcli_try(args):
    """Same as wpcli() but hands back the failure instead of aborting.

    Needed because two of the permission checks expect wp-cli to fail: wp_die()
    inside the plugin makes WP-CLI exit non zero, and that exit code is the
    measurement, not an accident.
    """
    pw = open(os.path.join(WORK, '.pw')).read().strip()
    cmd = ['docker', 'run', '--rm', '--network', NET, '--volumes-from', WP, '--user', '33:33',
           '-e', 'WORDPRESS_DB_HOST=%s' % DB, '-e', 'WORDPRESS_DB_USER=root',
           '-e', 'WORDPRESS_DB_PASSWORD=%s' % pw, '-e', 'WORDPRESS_DB_NAME=wordpress',
           'wordpress:cli', 'wp'] + args
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def seed():
    """Make the site contain exactly the seven fixture posts and nothing else."""
    mu = os.path.join(SANDBOX, 'fixture', 'mu-plugins')
    keep = [f for f in os.listdir(mu) if f.endswith('.php')]
    if keep:
        # Another prototype left files here; run.sh wipes them anyway, but move
        # them out of the way rather than deleting someone else's work.
        os.makedirs('/tmp/ilaudit-mu-backup', exist_ok=True)
        for f in keep:
            os.replace(os.path.join(mu, f), os.path.join('/tmp/ilaudit-mu-backup', f))
    for f in ('90-ilaudit-fixture-shortcode.php', '92-ilaudit-fixture-injector.php'):
        sh(['cp', os.path.join(HERE, 'fixture', f), mu])

    wpcli(['rewrite', 'structure', '/%postname%/', '--hard'])
    wpcli(['rewrite', 'flush', '--hard'])
    ids = wpcli(['post', 'list', '--post_type=post', '--post_status=any', '--format=ids'])
    if ids:
        wpcli(['post', 'delete'] + ids.split() + ['--force'])

    created = {}
    for slug, title, content in POSTS:
        pid = wpcli(['post', 'create', '--post_type=post', '--post_status=publish',
                     '--post_title=%s' % title, '--post_name=%s' % slug,
                     '--post_content=%s' % content, '--porcelain'])
        created[slug] = int(pid)
    return created


def install_plugin():
    dest = '%s:/var/www/html/wp-content/plugins/honoka-internal-link-audit' % WP
    sh(['docker', 'exec', WP, 'rm', '-rf', '/var/www/html/wp-content/plugins/honoka-internal-link-audit'])
    sh(['docker', 'cp', os.path.join(HERE, 'plugin'), dest])
    sh(['docker', 'exec', WP, 'chown', '-R', '33:33', '/var/www/html/wp-content/plugins/honoka-internal-link-audit'])
    wpcli(['plugin', 'activate', 'honoka-internal-link-audit'])
    return wpcli(['plugin', 'get', 'honoka-internal-link-audit', '--field=version'])


# ---------------------------------------------------------------- the real screen
class Admin:
    """Logs in to wp-admin the way a person does and presses the plugin's buttons.

    Takes a user name and password so the same code can sit in a reader's chair as
    well as an administrator's. Everything the permission checks claim is measured
    through this class, over HTTP, with a real login cookie.
    """

    def __init__(self, user='admin', pw=None):
        self.user = user
        self.pw = pw
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [('User-Agent', 'honoka-ilaudit-harness/1.0')]

    def open(self, url, data=None):
        body = urllib.parse.urlencode(data).encode() if data else None
        with self.op.open(urllib.request.Request(url, data=body), timeout=60) as r:
            return r.read().decode('utf-8', 'replace')

    def fetch(self, url, data=None):
        """Like open() but a refusal is an answer, not an exception."""
        body = urllib.parse.urlencode(data).encode() if data else None
        try:
            with self.op.open(urllib.request.Request(url, data=body), timeout=60) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    def login(self):
        pw = self.pw if self.pw is not None else open(os.path.join(WORK, '.adminpw')).read().strip()
        self.open(BASE + '/wp-login.php')     # sets the test cookie
        html = self.open(BASE + '/wp-login.php', {
            'log': self.user, 'pwd': pw, 'wp-submit': 'Log In',
            'redirect_to': BASE + '/wp-admin/', 'testcookie': '1'})
        if 'ERROR' in html or 'wp-login.php' in html and 'loginform' in html:
            raise SystemExit('could not log in to wp-admin as %s' % self.user)
        return self

    def screen(self):
        return self.open(BASE + '/wp-admin/tools.php?page=honoka-internal-link-audit')

    def press(self, html, action):
        nonce = re.search(r'name="_wpnonce" value="([^"]+)"', html)
        if not nonce:
            raise SystemExit('no nonce on the plugin screen (not logged in?)')
        return self.open(BASE + '/wp-admin/tools.php?page=honoka-internal-link-audit',
                         {'ilaudit_action': action, '_wpnonce': nonce.group(1),
                          'ilaudit_go': 'go'})


def run_scan():
    a = Admin()
    a.login()
    html = a.screen()
    if 'Honoka Internal Link Audit' not in html:
        raise SystemExit('the plugin screen did not render')
    html = a.press(html, 'start')
    rounds = 1
    while 'Scan in progress' in html and rounds < 100:
        html = a.press(html, 'continue')
        rounds += 1
    return html, rounds


# ---------------------------------------------------------------- verification
def php_code(src):
    """Drop PHP comments, so a static check reads the code and not its own prose.

    The first version of check V19 failed because the file's own header says there
    is no trial period, and the check matched the word "trial" in that sentence: it
    was reading the promise instead of the code. Stripping // to end of line is only
    safe because no string literal in this file contains a double slash; a plugin
    that embedded a URL in code would need a real tokenizer.
    """
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


def cell(html, label):
    """Read one value out of the summary table by its row label."""
    m = re.search(r'<tr><td>%s</td><td><strong>(.*?)</strong></td></tr>'
                  % re.escape(label), html, re.S)
    return None if not m else re.sub(r'<[^>]+>', '', m.group(1)).strip()


def orphan_titles(html):
    m = re.search(r'Posts no other post links to</h2>(.*?)(?:<h2|$)', html, re.S)
    if not m:
        return None
    return sorted(re.findall(r'<td><a href="[^"]*">([^<]*)</a></td>', m.group(1)))


def orphan_row(html, title):
    m = re.search(r'<td><a href="[^"]*">%s</a></td><td>[^<]*</td><td>([^<]*)</td><td>([^<]*)</td>'
                  % re.escape(title), html)
    return None if not m else (m.group(1).strip(), m.group(2).strip())


# ---------------------------------------------------------------- the permission gate
# readme.txt answers "Who can see the report?" with: "Only users who can manage
# options, which normally means administrators. The screen refuses anyone else."
# Until this block existed that sentence described one argument passed to
# add_management_page() and nothing that had been observed: checks V1 to V19 all
# run as the administrator, so every one of them would still pass if the gate were
# removed. These five sit in a non administrator's chair instead.
#
# Editor is the sharp case, not subscriber: it is the strongest role short of
# administrator and the one with a plausible reason to open a Tools screen. If the
# gate holds for an editor it holds for author and subscriber too.
NONADMIN = (('ilaudit_editor', 'editor'), ('ilaudit_subscriber', 'subscriber'))


_USERS = {}


def ensure_users():
    """Create the two non administrator logins, or reset their passwords.

    Cached: teeth_test.py calls the whole verification once per sabotage, and
    rebuilding two users through wp-cli each time would add minutes for nothing.
    """
    if _USERS:
        return _USERS
    out = {}
    for login, role in NONADMIN:
        pw = __import__('secrets').token_hex(12)
        rc, _, _ = wpcli_try(['user', 'create', login, '%s@example.invalid' % login,
                              '--role=%s' % role, '--user_pass=%s' % pw])
        if rc != 0:                                  # already there from an earlier run
            wpcli(['user', 'update', login, '--user_pass=%s' % pw, '--skip-email'])
            wpcli(['user', 'set-role', login, role])
        out[login] = (role, pw)
    _USERS.update(out)
    return out


def state_option():
    """The one option a scan writes, as text, so before and after can be compared."""
    rc, out, _ = wpcli_try(['option', 'get', ILAUDIT_STATE_OPTION, '--format=json'])
    return out if rc == 0 else '<absent>'


ILAUDIT_STATE_OPTION = 'ilaudit_state'
SCREEN = '/wp-admin/tools.php?page=honoka-internal-link-audit'


def permission_gate(admin_html):
    """Ask for the report as somebody who is not an administrator, and write down what came back.

    Four separate questions, because they can fail independently:
      * does the screen hand over the numbers to a non administrator (GET)
      * does a scan start for a non administrator who replays an administrator's
        nonce (POST) - the nonce is the only token on that form, so a handler that
        checked the nonce and not the capability would run here
      * is the menu item even shown to them
      * does the plugin's own current_user_can() line refuse, or is WordPress'
        menu capability the only thing standing in the way
    The last one matters because WordPress blocks the page before the plugin's
    function is reached, so deleting the plugin's own guard changes nothing an
    HTTP request can see. ilaudit_render() is therefore called directly, as the
    editor, through wp-cli.
    """
    users = ensure_users()
    nonce = re.search(r'name="_wpnonce" value="([^"]+)"', admin_html)
    if not nonce:
        raise SystemExit('no nonce on the administrator screen, so the replay cannot be tried')
    before = state_option()
    seen = {}
    for login, (role, pw) in users.items():
        a = Admin(login, pw).login()
        get_status, get_html = a.fetch(BASE + SCREEN)
        post_status, post_html = a.fetch(BASE + SCREEN, {
            'ilaudit_action': 'start', '_wpnonce': nonce.group(1), 'ilaudit_go': 'go'})
        _, menu_html = a.fetch(BASE + '/wp-admin/tools.php')
        seen[role] = {
            'get_status': get_status,
            'post_status': post_status,
            # the report's own headline row: if this is on the page they were served the report
            'get_showed_report': 'Published posts read' in get_html,
            'post_showed_report': 'Published posts read' in post_html,
            'menu_links_to_screen': 'page=honoka-internal-link-audit' in menu_html,
            'refusal': refusal_words(get_html),
        }
    # Did any of that move the option a scan writes?
    after = state_option()
    rc, _, err = wpcli_try(['eval', 'ilaudit_render();', '--user=ilaudit_editor'])
    return {'roles': seen, 'state_unchanged': before == after,
            'state_before': before[:80], 'state_after': after[:80],
            'own_guard_rc': rc, 'own_guard_said': refusal_words(err)}


def refusal_words(body):
    """Which refusal the visitor was given, so we know whose gate fired."""
    out = []
    if 'You do not have permission to view this report' in body:
        out.append('plugin')          # the line inside ilaudit_render()
    if re.search(r'(?i)you are not allowed to access this page|Sorry, you are not allowed', body):
        out.append('wordpress')       # the menu capability, before our code runs
    return out


def verify(html, rounds, gate=None):
    checks = []

    def ck(name, got, want, why):
        checks.append({'name': name, 'got': got, 'want': want, 'ok': got == want, 'why': why})

    ck('V1 posts read', cell(html, 'Published posts read'), str(EXPECTED['posts']),
       'every published post is read, and nothing else is')
    ck('V2 orphan count', cell(html, 'Posts no other post links to'), str(EXPECTED['orphan_count']),
       'the headline number')
    ck('V3 orphan list', orphan_titles(html), EXPECTED['orphans'],
       'which posts, not just how many')
    ck('V4 images', cell(html, 'Images with no alt attribute'),
       '%d / %d' % (EXPECTED['images_no_alt'], EXPECTED['images']),
       'images with no alt, out of all images')
    ck('V5 internal links total', cell(html, 'Internal links found'), str(EXPECTED['internal_sum']),
       'tel:, mailto:, #anchor and outside links are not internal links')
    ck('V6 internal links median', cell(html, 'Internal links per post (median)'),
       EXPECTED['internal_med'], 'the middle post, with an odd number of posts')
    ck('V7 posts with no link out', cell(html, 'Posts with no internal link out'),
       str(EXPECTED['zero_internal']), 'counted separately from orphans')

    # Each of these fails on its own if one specific rule is dropped.
    ck('V8 shortcodes are expanded', 'Delta' in (orphan_titles(html) or []), False,
       'Delta is linked to only from a shortcode, so it is an orphan unless shortcodes are expanded')
    ck('V9 HTML comments ignored', 'Eta' in (orphan_titles(html) or []), True,
       'the only link to Eta is inside an HTML comment, which is not on the page')
    ck('V10 self link does not rescue', 'Gamma' in (orphan_titles(html) or []), True,
       'Gamma links to itself and nothing else links to it')
    ck('V11 empty alt is not missing', cell(html, 'Images with no alt attribute'),
       '%d / %d' % (EXPECTED['images_no_alt'], EXPECTED['images']),
       'alt="" is correct markup for a decorative image')
    row = orphan_row(html, 'Zeta')
    ck('V12 per row figures', row, ('1', '1'),
       'the orphan table shows that row\'s own link and alt counts')
    ck('V13 two links to one post', 'Beta' in (orphan_titles(html) or []), False,
       'Alpha links to Beta twice; two links, one linking post')
    ck('V14 batching finished', rounds >= 1 and 'Scan in progress' not in html, True,
       'the scan ran to the end over HTTP')
    ck('V25 a third party plugin really does inject into the page',
       injected_marker_on_front_end(), True,
       'the fixture plugin appends a related posts box to every post through the_content, '
       'so V26 is measuring something that is actually there')
    ck('V26 injected content is not counted as the post\'s own',
       (cell(html, 'Internal links found'), cell(html, 'Images with no alt attribute'),
        'Eta' in (orphan_titles(html) or [])),
       (str(EXPECTED['internal_sum']),
        '%d / %d' % (EXPECTED['images_no_alt'], EXPECTED['images']), True),
       'with the injector active the figures and the orphan list are unchanged; running the '
       'the_content chain instead gave 15 links, 12 / 14 images and rescued Eta (2026-10-04). '
       'This is a composite of cells other checks also read, so it trips on any numeric '
       'defect; its own job is to make the injector part of the fixture on purpose')
    ck('V15 nothing on the front end', front_end_clean(), True,
       'the public home page carries no mark from the plugin')

    src = php_code(open(os.path.join(HERE, 'plugin', 'honoka-internal-link-audit.php'),
                        encoding='utf-8').read())
    ck('V16 no request leaves the site',
       sorted(set(re.findall(r'wp_remote_\w+|curl_init|fsockopen|stream_socket_client', src))), [],
       'guideline 7: there is no way for it to track anyone, because it cannot talk out')
    ck('V17 no front end hook',
       sorted(set(re.findall(r'add_(?:action|filter)\(\s*\n?\s*\'([a-z_]+)\'', src))),
       ['admin_menu'],
       'guideline 10: the only hook is the one that adds the admin screen')
    ck('V18 no notice and no nag',
       bool(re.search(r'(?i)admin_notices|add_dashboard_page|wp_admin_notice', src)), False,
       'guideline 11: nothing is pushed at the user outside this plugin\'s own screen')
    ck('V19 nothing is locked or for sale',
       sorted(set(re.findall(r'(?i)premium|licen[cs]e key|upgrade|paywall|trial period|is_pro\b', src))),
       [],
       'guideline 5: no trial, no locked feature')

    # --- the permission gate, measured from a non administrator's chair
    if gate is not None:
        for role in ('editor', 'subscriber'):
            r = gate['roles'][role]
            ck('V20 %s is refused the screen' % role,
               (r['get_showed_report'], r['post_showed_report'], bool(r['refusal'])),
               (False, False, True),
               'the report itself is not served to a %s, by GET or by POST, and they are told why'
               % role)
        ck('V22 an admin nonce does not run a scan', gate['state_unchanged'], True,
           'the only token on the form is the nonce, so capability has to be checked as well')
        ck('V23 the menu item is not shown to them',
           sorted(r for r in ('editor', 'subscriber')
                  if gate['roles'][r]['menu_links_to_screen']), [],
           'a link they cannot follow does not belong in their Tools menu')
        ck('V24 the plugin refuses on its own',
           (gate['own_guard_rc'] != 0, gate['own_guard_said']), (True, ['plugin']),
           'WordPress blocks the page before our code runs, so the plugin\'s own '
           'current_user_can() is only proved by calling ilaudit_render() as an editor')
    return checks


def injected_marker_on_front_end():
    """Is the fixture plugin's appended box actually on a public post page?

    Without this, check V26 would pass for the wrong reason on any day the
    fixture file failed to load: an injection that never happened is trivially
    not counted.
    """
    with urllib.request.urlopen(BASE + '/alpha/', timeout=30) as r:
        html = r.read().decode('utf-8', 'replace')
    return ('You may also like' in html
            and 'fixture-related-posts' in html
            and 'related-thumb.png' in html)


def front_end_clean():
    with urllib.request.urlopen(BASE + '/', timeout=30) as r:
        html = r.read().decode('utf-8', 'replace')
    return not re.search(r'(?i)internal.link.audit|ilaudit|honoka', html)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    info = {}
    if cmd == 'all':
        info['posts'] = seed()
        info['plugin_version'] = install_plugin()
    info['wp_version'] = wpcli(['core', 'version'])
    info['php_version'] = sh(['docker', 'exec', WP, 'php', '-r', 'echo PHP_VERSION;'])
    html, rounds = run_scan()
    gate = permission_gate(html)
    checks = verify(html, rounds, gate)
    out = os.path.join(HERE, 'evidence')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'screen.html'), 'w', encoding='utf-8').write(html)
    passed = sum(1 for c in checks if c['ok'])
    report = {'wp': info.get('wp_version'), 'php': info.get('php_version'),
              'plugin': info.get('plugin_version'), 'rounds': rounds,
              'passed': passed, 'total': len(checks), 'checks': checks,
              'permission_gate': gate}
    json.dump(report, open(os.path.join(out, 'verify.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    for c in checks:
        print('%s %-28s got=%r want=%r  %s' % ('PASS' if c['ok'] else 'FAIL',
                                               c['name'], c['got'], c['want'], c['why']))
    print('\n%d/%d  (WordPress %s, PHP %s)' % (passed, len(checks),
                                               info.get('wp_version'), info.get('php_version')))
    return 0 if passed == len(checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/Users/takeya/Workspace/AutoManagement/venv/bin/python
"""Take the WordPress.org listing screenshot from the real admin screen.

Why a script and not a hand grab: the picture on the listing is a claim about what
the plugin shows. If it is drawn, cropped or taken from an older build it is a false
claim (charter 4). So this logs in to the sandbox as an administrator, opens the
plugin's own screen, and writes the pixels together with the numbers that are on
them, so tools/readme_test.py can check the readme against the same evidence.

    tools/screenshot.py            # needs ../../tools/wp-sandbox to be up and a scan to have run
"""
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'honoka-wp-sandbox')
PORT = os.environ.get('PORT', '8901')
BASE = 'http://127.0.0.1:%s' % PORT
SCREEN = '/wp-admin/tools.php?page=honoka-internal-link-audit'
OUT = os.path.join(HERE, 'assets', 'screenshot-1.png')


def main():
    pw = open(os.path.join(WORK, '.adminpw')).read().strip()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    import tempfile, shutil
    from playwright.sync_api import sync_playwright
    prof = tempfile.mkdtemp(prefix='ilaudit-shot-')
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                prof, channel='chrome', headless=True,
                viewport={'width': 1280, 'height': 900}, locale='en-US')
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(45000)
            pg.goto(BASE + '/wp-login.php', wait_until='load')
            pg.fill('#user_login', 'admin')
            pg.fill('#user_pass', pw)
            pg.click('#wp-submit')
            pg.wait_for_url(re.compile(r'/wp-admin/'), timeout=45000)
            r = pg.goto(BASE + SCREEN, wait_until='load')
            time.sleep(1.0)
            html = pg.content()
            # The collapsed admin menu keeps the picture about the report, not about
            # WordPress' own chrome, and matches the 772px the listing displays at.
            pg.add_style_tag(content='#wpadminbar{display:none!important}'
                                     '#adminmenumain{display:none!important}'
                                     '#wpcontent{margin-left:0!important}'
                                     '#wpfooter{display:none!important}'
                                     '#wpbody-content{padding-bottom:0!important}')
            time.sleep(0.3)
            el = pg.query_selector('#wpbody-content')
            (el or pg).screenshot(path=OUT)
            status = r.status if r else None
            ctx.close()
    finally:
        shutil.rmtree(prof, ignore_errors=True)

    h = hashlib.sha256(open(OUT, 'rb').read()).hexdigest()
    cells = dict(re.findall(r'<tr><td>([^<]+)</td><td><strong>([^<]*)</strong></td></tr>', html))
    man = {
        'url': SCREEN, 'status': status, 'file': os.path.relpath(OUT, HERE),
        'bytes': os.path.getsize(OUT), 'sha256': h,
        'screen_cells': cells,
        'logged_in_as': 'admin',
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    with open(os.path.join(HERE, 'evidence', 'screenshot.json'), 'w') as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: man[k] for k in ('status', 'bytes', 'sha256', 'screen_cells')},
                     ensure_ascii=False, indent=1))
    return 0 if status == 200 and man['bytes'] > 5000 else 1


if __name__ == '__main__':
    sys.exit(main())

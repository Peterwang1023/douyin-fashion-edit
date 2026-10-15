"""Subset the caption fonts to exactly the characters the captions use.

    python fonts.py --project P        (the builders call ensure_fonts() automatically)

Fonts: Noto Serif SC (思源宋体) for the wedding-style captions, Noto Sans SC (思源黑体) Black for
the bold hook, ZCOOL XiaoWei (站酷小薇) + Italiana for the healing / editorial style.
All SIL Open Font License, free for commercial use. Subsets come from the
Google Fonts css2 `text=` API, so a few dozen KB each instead of ~10 MB.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, project_arg  # noqa: E402

FACES = [('Noto Serif SC', 500, 'serif-500'), ('Noto Serif SC', 700, 'serif-700'), ('Noto Serif SC', 900, 'serif-900'),
         ('Noto Sans SC', 500, 'sans-500'), ('Noto Sans SC', 900, 'sans-900'),
         ('ZCOOL XiaoWei', 400, 'xiaowei'),     # 站酷小薇: literary Chinese serif for the healing style
         ('Italiana', 400, 'italiana')]         # thin elegant Latin caps for small English lines
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36'
EXTRA = '0123456789·・—-:：,，.。!！?？ 第套ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def needed_text(pr):
    cfg = pr.load('outfits.json')
    chars = set(json.dumps(cfg, ensure_ascii=False)) | set(EXTRA)
    return ''.join(sorted(c for c in chars if c.isprintable() and c not in '"{}[]\\'))


def ensure_fonts(pr, force=False):
    text = needed_text(pr)
    d = pr.path('assets', 'fonts'); os.makedirs(d, exist_ok=True)
    stamp = os.path.join(d, 'glyphs.txt')
    have = open(stamp, encoding='utf-8').read() if os.path.exists(stamp) else ''
    if not force and set(text) <= set(have) and all(os.path.exists(os.path.join(d, n + '.woff2')) for _, _, n in FACES):
        return
    text = ''.join(sorted(set(text) | set(have)))
    for family, weight, name in FACES:
        fam = family.replace(' ', '+')
        url = ('https://fonts.googleapis.com/css2?family=%s:wght@%d&text=%s' % (fam, weight, urllib.parse.quote(text)) if weight != 400
               else 'https://fonts.googleapis.com/css2?family=%s&text=%s' % (fam, urllib.parse.quote(text)))   # single-weight families
        css = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60).read().decode()
        srcs = re.findall(r'url\((https://[^)]+)\)', css)
        if len(srcs) != 1:
            sys.exit(f'unexpected font response for {family} {weight}')
        blob = urllib.request.urlopen(urllib.request.Request(srcs[0], headers={'User-Agent': UA}), timeout=60).read()
        open(os.path.join(d, name + '.woff2'), 'wb').write(blob)
    open(stamp, 'w', encoding='utf-8').write(text)
    print(f'fonts subset to {len(text)} glyphs')


if __name__ == '__main__':
    ap = project_arg(); ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    ensure_fonts(Project(a.project), a.force)

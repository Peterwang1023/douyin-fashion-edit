"""Create an editing project: a HyperFrames project plus the config skeleton.

    python init_project.py <dir> --brand "某某服饰" [--end-line "关注我 · 每天分享一套穿搭"]

Re-running on an existing project only fills in what is missing.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import npx  # noqa: E402
import json  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('--brand', required=True, help='shop / brand name (kept in config; drawn only with "showBrand": true)')
    ap.add_argument('--end-line', default='关注我 · 每天分享一套穿搭', help='line under the title on the end card')
    a = ap.parse_args()
    root = os.path.abspath(a.dir)

    if not os.path.exists(os.path.join(root, 'hyperframes.json')):
        os.makedirs(os.path.dirname(root), exist_ok=True)
        npx('--yes', 'hyperframes', 'init', root, '--non-interactive', '--example=blank')
    for d in ('config', 'assets/shots', 'assets/shots_beauty', 'assets/bgm/src', 'assets/fonts', 'compositions', 'renders', 'review', 'cache'):
        os.makedirs(os.path.join(root, d), exist_ok=True)

    defaults = {
        'outfits.json': {'brand': a.brand, 'showBrand': False, 'endTitle': '秋冬穿搭', 'endLine': a.end_line, 'outfits': {}, 'combos': {}},
        'sources.json': {}, 'edl.json': {}, 'grade.json': {}, 'music.json': {}, 'avail.json': {},
    }
    for name, data in defaults.items():
        p = os.path.join(root, 'config', name)
        if not os.path.exists(p):
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    # whip-pan transition used by the outfit-change compilations
    if not os.path.exists(os.path.join(root, 'compositions', 'components', 'whip-pan-cut.html')):
        npx('--yes', 'hyperframes', 'add', 'whip-pan-cut', '--no-clipboard', cwd=root, check=False)

    gi = os.path.join(root, '.gitignore')
    if not os.path.exists(gi):
        with open(gi, 'w', encoding='utf-8') as f:
            f.write('assets/shots/\nassets/shots_beauty/\nrenders/\nreview/\ncache/\nsnapshots/\n')
    print(f'project ready: {root}')


if __name__ == '__main__':
    main()

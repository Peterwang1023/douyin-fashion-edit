"""Build -> lint -> render -> review sheet, for single-outfit videos and compilations.

    python render.py single [OUTFIT ...] --project P     (default: every outfit in outfits.json)
    python render.py combo  [COMBO ...]  --project P     (default: every combo)
    python render.py clone  [CLONE ...]  --project P     (default: every clone)

Renders go to <project>/renders/outfit-XX.mp4 and combo-X.mp4; review sheets to <project>/review/.
index.html is regenerated for every item (HyperFrames renders the project's index.html), so
items are rendered one after another. A lint error stops that item.
"""
import argparse
import os
import re
import subprocess
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, project_arg  # noqa: E402
import build_clone  # noqa: E402
import build_combo  # noqa: E402
import build_single  # noqa: E402
import review  # noqa: E402


def hf(pr, *args):
    exe = shutil.which('npx') or shutil.which('npx.cmd')
    r = subprocess.run([exe, '--yes', 'hyperframes', *args], cwd=pr.root, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def one(pr, kind, ident):
    builder = {'single': build_single.build, 'combo': build_combo.build, 'clone': build_clone.build}[kind]
    total = builder(pr, ident)
    code, out = hf(pr, 'lint')
    m = re.search(r'(\d+) error\(s\)', out)
    if code != 0 or (m and int(m.group(1)) > 0):
        print(out)
        print(f'LINT FAILED for {kind} {ident}; not rendering')
        return False
    name = {'single': f'outfit-{ident}', 'combo': f'combo-{ident}', 'clone': f'clone-{ident}'}[kind]
    os.makedirs(pr.path('renders'), exist_ok=True)
    code, out = hf(pr, 'render', '-o', f'renders/{name}.mp4', '--quiet')
    if code != 0 or not os.path.exists(pr.path('renders', f'{name}.mp4')):
        print(out[-3000:])
        print(f'RENDER FAILED for {name}')
        return False
    print(f'rendered renders/{name}.mp4 ({total:.2f}s)')
    {'single': review.single, 'combo': review.combo, 'clone': review.clone}[kind](pr, ident)
    return True


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='kind', required=True)
    for k in ('single', 'combo', 'clone'):
        s = project_arg(sub.add_parser(k)); s.add_argument('ids', nargs='*')
    a = ap.parse_args()
    pr = Project(a.project)
    cfg = pr.load('outfits.json')
    ids = a.ids or sorted(cfg.get({'single': 'outfits', 'combo': 'combos', 'clone': 'clones'}[a.kind], {}))
    bad = [i for i in ids if not one(pr, a.kind, i)]
    if bad:
        sys.exit(f'failed: {bad}')


if __name__ == '__main__':
    main()

"""Review sheets of rendered videos: the frames that matter, side by side, so they can be looked at.

    python review.py single OUTFIT --project P          title, chip shots (in/mid/out), end card
    python review.py combo COMBO --project P            hook, around the first change, each outfit, end card
    python review.py file VIDEO --at 1.2,4.6,9 [--out x.jpg]
    python review.py zoom VIDEO --at 5.0 --box x,y,w,h  2x crop (faces, caption vs head clearance)

Look at every sheet before calling a video done: captions must sit above the head and never
cover the clothes, faces must not be blown out, retouch must look natural, no stray people/phones.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, font, grab_rgb, project_arg  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def overlay_timing(pr, name):
    s = open(pr.path('compositions', name), encoding='utf-8').read()
    return json.loads(s.split('const T = ')[1].split(';')[0])


def sheet(video, times, out, label=''):
    f = font(20); tiles = []
    for t in times:
        a = grab_rgb(video, t, 405, 720)
        if a is not None:
            tiles.append((t, Image.fromarray(a)))
    img = Image.new('RGB', (405 * len(tiles), 744), 'white'); d = ImageDraw.Draw(img)
    for i, (t, im) in enumerate(tiles):
        img.paste(im, (405 * i, 24)); d.text((405 * i + 6, 2), f'{label} @ {t:.2f}s', fill='red', font=f)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out, quality=88)
    print(out)
    return out


def single(pr, oid):
    T = overlay_timing(pr, f'overlay-{oid}.html')
    times = [1.4, T['chipsIn'] + 0.9, (T['chipsIn'] + T['chipsOut']) / 2, T['chipsOut'] - 0.05, T['endIn'] + 1.0, T['total'] - 0.1]
    return sheet(pr.path('renders', f'outfit-{oid}.mp4'), times, pr.path('review', f'render_{oid}.jpg'), oid)


def combo(pr, cid):
    T = overlay_timing(pr, f'combo-{cid}-overlay.html')
    h = T['hookOut']
    times = [0.6, h - 0.25, h - 0.06, h + 0.03] + [(a + b) / 2 for a, b in T['labels']] + [T['total'] - 0.3]
    return sheet(pr.path('renders', f'combo-{cid}.mp4'), times, pr.path('review', f'render_combo_{cid}.jpg'), cid)


def zoom(video, t, box, out):
    x, y, w, h = [int(v) for v in box.split(',')]
    a = grab_rgb(video, t, 1080, 1920)
    im = Image.fromarray(a[y:y + h, x:x + w]); im = im.resize((w * 2, h * 2), Image.LANCZOS)
    im.save(out, quality=90); print(out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = project_arg(sub.add_parser('single')); s.add_argument('outfit')
    s = project_arg(sub.add_parser('combo')); s.add_argument('combo')
    s = sub.add_parser('file'); s.add_argument('video'); s.add_argument('--at', required=True); s.add_argument('--out')
    s = sub.add_parser('zoom'); s.add_argument('video'); s.add_argument('--at', type=float, required=True)
    s.add_argument('--box', default='0,100,1080,900'); s.add_argument('--out')
    a = ap.parse_args()
    if a.cmd == 'single':
        single(Project(a.project), a.outfit)
    elif a.cmd == 'combo':
        combo(Project(a.project), a.combo)
    elif a.cmd == 'file':
        sheet(a.video, [float(x) for x in a.at.split(',')], a.out or os.path.splitext(a.video)[0] + '_sheet.jpg')
    else:
        zoom(a.video, a.at, a.box, a.out or os.path.splitext(a.video)[0] + f'_zoom_{a.at}.jpg')


if __name__ == '__main__':
    main()

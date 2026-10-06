"""Contact sheets for looking at footage (write JPGs into <project>/review/, then view them).

    python contact_sheet.py overview [KEY ...] --project P   2 frames per clip, ~12 clips per sheet -> sort clips by outfit
    python contact_sheet.py strips   [KEY ...] --project P   2 fps strip per clip with timestamps   -> pick shot in/out points
    python contact_sheet.py torso KEY@SEC [KEY@SEC ...]      upper-body crops side by side          -> tell similar garments apart
    python contact_sheet.py edl OUTFIT --project P           middle frame of every EDL shot of one outfit

Keys are source keys from config/sources.json (default: all sources).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MODEL_DIR, Project, duration, font, grab_rgb, project_arg, video_size  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def tile_size(path, short=200):
    w, h = video_size(path)
    return (short, int(short * h / w) // 2 * 2) if h >= w else (int(short * w / h) // 2 * 2, short)


def save(img, pr, name):
    out = pr.path('review', name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, quality=86)
    print(out)


def overview(pr, keys):
    src = pr.sources()
    keys = keys or sorted(src)
    f = font(26)
    for b in range(0, len(keys), 12):
        tiles = []
        for k in keys[b:b + 12]:
            p = src[k]
            tw, th = tile_size(p)
            d = duration(p)
            ims = [grab_rgb(p, d * r, tw, th) for r in (0.3, 0.7)]
            pair = Image.new('RGB', (tw * 2 + 4, th), 'white')
            for i, a in enumerate(ims):
                if a is not None:
                    pair.paste(Image.fromarray(a), (i * (tw + 4), 0))
            ImageDraw.Draw(pair).text((6, 4), k, fill='red', font=f, stroke_width=2, stroke_fill='white')
            tiles.append(pair)
        # flow layout: portrait and landscape pairs pack into rows of at most ~1700 px
        rows, row, x = [], [], 0
        for t in tiles:
            if row and x + t.width > 1700:
                rows.append(row); row, x = [], 0
            row.append(t); x += t.width + 8
        rows.append(row)
        width = max(sum(t.width + 8 for t in r) for r in rows)
        sheet = Image.new('RGB', (width, sum(max(t.height for t in r) + 8 for r in rows)), 'white')
        y = 0
        for r in rows:
            x = 0
            for t in r:
                sheet.paste(t, (x, y)); x += t.width + 8
            y += max(t.height for t in r) + 8
        save(sheet, pr, f'overview_{b // 12}.jpg')


def strips(pr, keys):
    import subprocess
    src = pr.sources()
    keys = keys or sorted(src)
    small, big = font(15), font(24)
    for k in keys:
        p = src[k]
        tw, th = tile_size(p, 125)
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', p, '-vf', f'fps=2,scale={tw}:{th}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                             capture_output=True).stdout
        n = len(raw) // (tw * th * 3)
        frames = [Image.frombytes('RGB', (tw, th), raw[i * tw * th * 3:(i + 1) * tw * th * 3]) for i in range(n)]
        per = max(1, 2000 // tw)
        rows = (n + per - 1) // per
        sheet = Image.new('RGB', (per * tw, rows * (th + 2)), 'white')
        d = ImageDraw.Draw(sheet)
        for i, im in enumerate(frames):
            x, y = (i % per) * tw, (i // per) * (th + 2)
            sheet.paste(im, (x, y))
            d.text((x + 3, y + 2), f'{i / 2:.1f}', fill='yellow', font=small, stroke_width=2, stroke_fill='black')
        d.text((4, th - 30), k, fill='red', font=big, stroke_width=2, stroke_fill='white')
        save(sheet, pr, f'strip_{k}.jpg')


def torso(pr, specs):
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    buf = open(os.path.join(MODEL_DIR, 'pose_landmarker_heavy.task'), 'rb').read()   # buffer: model paths with CJK chars fail
    pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=buf), num_poses=1))
    src = pr.sources(); f = font(26); tiles = []
    for spec in specs:
        k, t = spec.split('@')
        p = src[k]
        w, h = video_size(p)
        sw, sh = (864, int(864 * h / w)) if h >= w else (int(864 * w / h), 864)
        a = grab_rgb(p, float(t), sw, sh)
        im = Image.fromarray(a)
        r = pose.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(a)))
        if r.pose_landmarks:
            q = r.pose_landmarks[0]
            xs = [q[i].x * sw for i in (11, 12, 23, 24)]; ys = [q[i].y * sh for i in (0, 11, 12, 23, 24)]
            cx = sum(xs) / 4; top = min(ys) - 60; bot = max(ys) + 120; hh = bot - top
            im = im.crop((int(cx - hh * 0.45), int(top), int(cx + hh * 0.45), int(bot)))
        im.thumbnail((260, 330)); tiles.append((spec, im))
    sheet = Image.new('RGB', (260 * len(tiles), 370), 'white'); d = ImageDraw.Draw(sheet)
    for i, (spec, im) in enumerate(tiles):
        sheet.paste(im, (i * 260, 36)); d.text((i * 260 + 4, 2), spec, fill='red', font=f)
    save(sheet, pr, 'torso.jpg')


def edl(pr, oid):
    shots = pr.load('edl.json')[oid]; src = pr.sources(); f = font(22); tiles = []
    for i, s in enumerate(shots):
        k, st, d = s[:3]
        tw, th = tile_size(src[k], 240)
        a = grab_rgb(src[k], st + d / 2, tw, th)
        tiles.append((f'{oid}_{i} {k} @{st}+{d}', Image.fromarray(a)))
    sheet = Image.new('RGB', (sum(t.width for _, t in tiles), max(t.height for _, t in tiles) + 30), 'white')
    d = ImageDraw.Draw(sheet); x = 0
    for lab, t in tiles:
        sheet.paste(t, (x, 30)); d.text((x + 4, 4), lab, fill='red', font=f); x += t.width
    save(sheet, pr, f'edl_{oid}.jpg')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('overview', 'strips', 'torso'):
        s = project_arg(sub.add_parser(name)); s.add_argument('keys', nargs='*')
    e = project_arg(sub.add_parser('edl')); e.add_argument('outfit')
    a = ap.parse_args()
    pr = Project(a.project)
    {'overview': lambda: overview(pr, a.keys), 'strips': lambda: strips(pr, a.keys),
     'torso': lambda: torso(pr, a.keys), 'edl': lambda: edl(pr, a.outfit)}[a.cmd]()


if __name__ == '__main__':
    main()

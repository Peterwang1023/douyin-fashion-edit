"""Exposure metering + grade suggestions + before/after sheets.

    python meter.py suggest [OUTFIT ...] --project P     meter the source of every EDL shot, fill missing grade.json
                                                         entries with a suggestion (existing entries are kept)
    python meter.py sheet OUTFIT --project P             before/after sheet of the current grade -> review/grade_<OUTFIT>.jpg
    python meter.py faces [OUTFIT ...] --project P [--rendered shots_beauty]
                                                         face exposure of rendered shots (mean, p95, % clipped)

grade.json: {"03": [[L, W, H], ...]} one triple per EDL shot, see common.grade_filter.
Face metering uses OpenCV's bundled Haar cascades (no download needed); check the reported
numbers against the sheet, a bright sky can be mistaken for a face.
"""
import argparse
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, font, grab_rgb, grade_filter, project_arg, shot_parts  # noqa: E402

_casc = None


def face_box(img):
    global _casc
    import cv2
    if _casc is None:
        _casc = [cv2.CascadeClassifier(cv2.data.haarcascades + n) for n in
                 ('haarcascade_frontalface_default.xml', 'haarcascade_profileface.xml')]
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY); best = None
    for c in _casc:
        for flip in (False, True):
            gg = g[:, ::-1] if flip else g
            for (x, y, w, h) in c.detectMultiScale(gg, 1.1, 4, minSize=(24, 24)):
                if flip:
                    x = img.shape[1] - x - w
                if best is None or w * h > best[2] * best[3]:
                    best = (x, y, w, h)
    return best


def luma(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def face_stats(img, b):
    """mean luma, p95 luma, % clipped (>235), skin warmth (mean R - B) of the inner face box."""
    x, y, w, h = b
    roi = img[y + h // 5:y + h - h // 6, x + w // 5:x + w - w // 5].astype(float)
    Y = luma(roi)
    return Y.mean(), np.percentile(Y, 95), (Y > 235).mean() * 100, (roi[..., 0] - roi[..., 2]).mean()


def measure(path, t0, d):
    Ys, rbs, faces = [], [], []
    for r in (0.2, 0.5, 0.85):
        a = grab_rgb(path, t0 + d * r, 540, 960)
        if a is None:
            continue
        Ys.append(luma(a.astype(float)).mean())
        # scene warmth without the sky: bright blue pixels would make every outdoor shot read "cold"
        f = a.astype(float); sky = (f[..., 2] > f[..., 0] + 20) & (luma(f) > 140)
        rbs.append(float((f[..., 0] - f[..., 2])[~sky].mean()) if (~sky).any() else 0.0)
        fb = face_box(a)
        if fb:
            faces.append(face_stats(a, fb))
    face = np.array(faces).max(0) if faces else None
    return float(np.mean(Ys)), float(np.mean(rbs)), face


def suggest_grade(Y, rb, face):
    """Faces decide when one is found (the subject matters, not the trees or the sky)."""
    L = float(np.clip((120 - Y) / 15, 0.3, 3.0))            # dark / backlit -> lift
    Wm = float(np.clip(1.4 - rb / 30, 0.3, 2.5))            # cool shade / dusk -> warm; golden hour -> barely
    Hl = 0.5
    if face is not None:
        mean, p95, clip, skin_rb = face
        L = float(np.clip((140 - mean) / 15, 0.3, 2.5))      # aim for a face around luma 140
        Wm = float(np.clip(1.2 - (skin_rb - 45) / 40, 0.3, 2.0))   # skin R-B ~45 is neutral-warm
        Hl = 0.5 if clip < 2 else 1.0 if clip < 8 else 1.5 if clip < 20 else 2.2
        if mean > 190:
            Hl = max(Hl, 1.5)
        if clip > 8:
            L = min(L, 1.2)                                  # never lift a face that is already blowing out
    return [round(L, 1), round(Wm, 1), round(Hl, 1)]


def cmd_suggest(pr, outfits):
    edl, grade, src = pr.load('edl.json'), pr.load('grade.json', {}), pr.sources()
    for o in outfits or sorted(edl):
        g = grade.get(o, [])
        for i, s in enumerate(edl[o]):
            k, st, d, _, opts = shot_parts(s)
            Y, rb, face = measure(src[k], st, d * float(opts.get('speed', 1.0)))
            sug = suggest_grade(Y, rb, face)
            ftxt = (f'face mean {face[0]:5.1f} p95 {face[1]:5.1f} clip {face[2]:4.1f}% skin R-B {face[3]:+5.1f}'
                    if face is not None else 'no face found')
            keep = i < len(g)
            print(f'{o}_{i} {k:>6} frameY {Y:5.1f} R-B {rb:+5.1f}  {ftxt}  -> suggest {sug}{"  (kept " + str(g[i]) + ")" if keep else ""}')
            if not keep:
                g.append(sug)
        grade[o] = g[:len(edl[o])]
    pr.save('grade.json', grade)


def cmd_sheet(pr, oid):
    from PIL import Image, ImageDraw
    edl, grade, src = pr.load('edl.json'), pr.load('grade.json'), pr.sources()
    f = font(20); tiles = []
    for i, (s, g) in enumerate(zip(edl[oid], grade[oid])):
        k, st, d, _, opts = shot_parts(s)
        t = st + d * float(opts.get('speed', 1.0)) / 2
        a = grab_rgb(src[k], t, 270, 480)
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', src[k], '-frames:v', '1', '-vf',
                              grade_filter(*g, size='270:480') + ',format=rgb24', '-f', 'rawvideo', '-'], capture_output=True).stdout
        b = np.frombuffer(raw[:270 * 480 * 3], np.uint8).reshape(480, 270, 3)
        tiles.append((f'{oid}_{i} {k} {g}', a, b))
    sheet = Image.new('RGB', (len(tiles) * 546, 510), 'white'); dr = ImageDraw.Draw(sheet)
    for i, (lab, a, b) in enumerate(tiles):
        sheet.paste(Image.fromarray(a), (i * 546, 30)); sheet.paste(Image.fromarray(b), (i * 546 + 272, 30))
        dr.text((i * 546 + 4, 4), lab + '  before | after', fill='red', font=f)
    out = pr.path('review', f'grade_{oid}.jpg'); sheet.save(out, quality=88); print(out)


def cmd_faces(pr, outfits, sub):
    edl = pr.load('edl.json')
    for o in outfits or sorted(edl):
        for i, s in enumerate(edl[o]):
            f = pr.path('assets', sub, f'{o}_{i}_{s[0]}.mp4')
            if not os.path.exists(f):
                continue
            rows = []
            for r in (0.25, 0.6, 0.9):
                a = grab_rgb(f, s[2] * r, 540, 960)
                fb = face_box(a) if a is not None else None
                if fb:
                    rows.append(face_stats(a, fb))
            if rows:
                m = np.array(rows).max(0)
                print(f'{o}_{i} {s[0]:>6}  face mean {m[0]:5.1f} p95 {m[1]:5.1f} clip {m[2]:4.1f}%{"   <-- hot" if m[2] > 8 else ""}')
            else:
                print(f'{o}_{i} {s[0]:>6}  no face found')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = project_arg(sub.add_parser('suggest')); s.add_argument('outfits', nargs='*')
    s = project_arg(sub.add_parser('sheet')); s.add_argument('outfit')
    s = project_arg(sub.add_parser('faces')); s.add_argument('outfits', nargs='*'); s.add_argument('--rendered', default='shots_beauty')
    a = ap.parse_args()
    pr = Project(a.project)
    if a.cmd == 'suggest':
        cmd_suggest(pr, a.outfits)
    elif a.cmd == 'sheet':
        cmd_sheet(pr, a.outfit)
    else:
        cmd_faces(pr, a.outfits, a.rendered)


if __name__ == '__main__':
    main()

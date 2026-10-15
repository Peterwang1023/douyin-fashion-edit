"""Copy a reference video's colour "filter" onto our shots as a 3D LUT.

    python match_look.py build REF.mp4 --name cool --shots c1_0 c1_1 ... --project P [--strength 0.85] [--tone 0.6] [--skin 0.5]
    python match_look.py apply NAME OUTFIT [OUTFIT ...] --project P

build: compares Lab statistics of the reference (frames sampled across the video, black frames skipped)
with our selected shots and writes assets/luts/<NAME>.cube plus review/look_<NAME>.jpg (ours | graded | reference):
    tone curve   L quantiles 2..98 % mapped onto the reference's (black level, contrast, highlight roll-off)
    hue zones    warm (skin, earth, orange), green (foliage) and cool (sky, cyan) colours each move toward the
                 reference's own hue and saturation for that zone, so e.g. a blue sky can turn teal while
                 the midtones turn orange (orange-teal looks); greens follow the warm zone when the
                 reference has almost none (vintage / film looks turn foliage olive)
    split tone   a/b offsets for shadows, mid-tones and highlights, mainly on low-saturation colours
    skin         skin-like colours get only `--skin` of the colour shift, so faces stay natural
--tone sets the tone-curve strength separately (default = --strength). Lower it when the reference is dark
or bright because of its *content* (black outfits, night street) rather than its grade, otherwise our
lighter scenes and faces get crushed.
apply: assets/shots_beauty (else shots) -> assets/shots_look/<NAME>/ for every shot of the outfits;
build_clone.py / build_single.py pick those files up when the config names the look.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, duration, font, grab_rgb, project_arg  # noqa: E402

N = 33
Q = np.linspace(2, 98, 17)


def lab_of(rgb8):
    return cv2.cvtColor(rgb8.astype(np.float32) / 255, cv2.COLOR_RGB2LAB).reshape(-1, 3)


def sample_frames(path, n, t0=0.0, t1=None, w=270, h=480):
    d = duration(path)
    t1 = d if t1 is None else t1
    out = []
    for t in np.linspace(t0 + 0.1, t1 - 0.1, n):
        a = grab_rgb(path, t, w, h)
        if a is not None and a.mean() > 12:          # skip black / fade frames
            out.append(a)
    return out


def band_weights(L):
    sh = np.clip((45 - L) / 25, 0, 1)
    hi = np.clip((L - 60) / 25, 0, 1)
    return sh, np.clip(1 - sh - hi, 0, 1), hi


ZONES = {'warm': (60.0, 55.0), 'green': (135.0, 40.0), 'cool': (225.0, 70.0)}   # Lab hue centre, half width (deg)


def hue_diff(h1, h0):
    return (h1 - h0 + 180.0) % 360.0 - 180.0


def zone_weights(a, b):
    """Soft membership of each colour in the warm / green / cool zones (0 for near-greys)."""
    hue = np.degrees(np.arctan2(b, a)) % 360.0
    ch = np.sqrt(a * a + b * b)
    conf = np.clip((ch - 10) / 10, 0, 1)         # greys and near-greys belong to no zone: they take the reference's base tint
    out = {}
    for k, (c, hw) in ZONES.items():
        d = np.abs(hue_diff(hue, c))
        out[k] = np.clip(np.cos(np.clip(d / hw, 0, 1) * np.pi / 2), 0, 1) ** 2 * conf
    tot = np.maximum(1.0, sum(out.values()))
    return {k: v / tot for k, v in out.items()}, hue, ch


def stats(lab):
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    w = band_weights(L)
    ab = [(float((a * wi).sum() / (wi.sum() + 1e-6)), float((b * wi).sum() / (wi.sum() + 1e-6))) for wi in w]
    zw, hue, ch = zone_weights(a, b)
    zones = {}
    for k, wk in zw.items():
        m = wk * ch
        share = float(wk.mean())
        if m.sum() < 1e-6:
            zones[k] = {'share': 0.0, 'hue': ZONES[k][0], 'chroma': 1.0}
            continue
        rad = np.radians(hue)
        mh = float(np.degrees(np.arctan2((np.sin(rad) * m).sum(), (np.cos(rad) * m).sum())) % 360)   # circular mean
        sel = wk > 0.3
        zones[k] = {'share': share, 'hue': mh, 'chroma': float(np.percentile(ch[sel], 75)) if sel.sum() > 50 else float((ch * wk).sum() / wk.sum())}
    return {'q': np.percentile(L, Q), 'ab': ab, 'chroma': float(np.percentile(ch, 75)), 'zones': zones}


def skin_weight(a, b):
    """1 for typical skin chromaticity (warm hue, moderate chroma), 0 far from it."""
    hue = np.degrees(np.arctan2(b, a)); ch = np.sqrt(a * a + b * b)
    return np.exp(-((hue - 55) / 22) ** 2) * np.clip((ch - 6) / 8, 0, 1) * np.clip((55 - ch) / 15, 0, 1)


def zone_moves(ref, ours):
    """Per zone: (hue rotation in degrees, chroma ratio)."""
    g = float(np.clip(ref['chroma'] / max(ours['chroma'], 1e-3), 0.6, 1.8))
    rz, oz = ref['zones'], ours['zones']
    mv = {}
    for k in ZONES:
        if rz[k]['share'] > 0.02 and oz[k]['share'] > 0.02:
            mv[k] = (float(np.clip(hue_diff(rz[k]['hue'], oz[k]['hue']), -40, 40)),
                     float(np.clip(rz[k]['chroma'] / max(oz[k]['chroma'], 1e-3), 0.6, 2.0)))
        else:
            mv[k] = (0.0, g)
    if rz['green']['share'] <= 0.02 and oz['green']['share'] > 0.02:     # reference has no foliage: greens lean warm
        mv['green'] = (float(np.clip(hue_diff(rz['warm']['hue'], oz['green']['hue']) * 0.3, -30, 30)), min(g, 1.0) * 0.85)
    return mv


def transform(lab, ref, ours, strength, skin, tone):
    L, a, b = lab[:, 0].copy(), lab[:, 1].copy(), lab[:, 2].copy()
    L2 = np.interp(L, ours['q'], ref['q'])                       # tone curve via quantile matching
    L2 = np.clip(L + (L2 - L) * tone, 0, 100)
    sw = skin_weight(a, b) * (1 - skin)                         # how much of the colour shift skin is spared
    zw, hue, ch = zone_weights(a, b)
    mv = zone_moves(ref, ours)
    g = float(np.clip(ref['chroma'] / max(ours['chroma'], 1e-3), 0.6, 1.8))
    zt = np.clip(sum(zw.values()), 0, 1)
    dh = sum(zw[k] * mv[k][0] for k in ZONES) * strength * (1 - sw)
    # zoned colours take their zone's saturation; the rest only a mild share of the global ratio
    # (a reference that is saturated because of its content must not amplify our near-greys)
    kc = sum(zw[k] * mv[k][1] for k in ZONES) + (1 - zt) * (1 + (g - 1) * 0.3)
    kc = 1 + (kc - 1) * strength * (1 - sw)
    rad = np.radians(hue + dh)
    a2, b2 = ch * kc * np.cos(rad), ch * kc * np.sin(rad)
    # near-greys blend toward the reference's base colour at their brightness (split tone: e.g. warm
    # shadows, golden road, teal-grey highlights)
    w = band_weights(L2)
    ta = sum(wi * r[0] for wi, r in zip(w, ref['ab'])); tb = sum(wi * r[1] for wi, r in zip(w, ref['ab']))
    # a real grade tints greys gently; a very saturated band average comes from the reference's content
    # (sunlit leaves, flower fields), so cap the tint at chroma 14
    tm = np.sqrt(ta * ta + tb * tb); kcap = np.minimum(1.0, 14.0 / np.maximum(tm, 1e-6))
    ta, tb = ta * kcap, tb * kcap
    n = np.clip(1.5 * (1 - ch / 22), 0, 1) * (1 - zt) * strength * (1 - sw)
    # pale blue-grey (overcast or hazy sky) keeps most of its own tint: a reference whose highlights are
    # yellow because of sunlit leaves must not paint our sky yellow
    n = n * np.clip(1 + b / 5, 0.25, 1)
    # near-white greys (overcast sky, clouds, white walls) stay close to neutral, like film highlights
    n = n * np.clip((95 - L2) / 25, 0.25, 1)
    return np.stack([L2, a2 + n * (ta - 0.7 * a2), b2 + n * (tb - 0.7 * b2)], 1)


def write_cube(path, ref, ours, strength, skin, tone):
    g = np.linspace(0, 1, N, dtype=np.float32)
    b_, g_, r_ = np.meshgrid(g, g, g, indexing='ij')             # .cube order: red changes fastest
    rgb = np.stack([r_.ravel(), g_.ravel(), b_.ravel()], 1).astype(np.float32)
    lab = cv2.cvtColor(rgb.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    out = cv2.cvtColor(transform(lab, ref, ours, strength, skin, tone).astype(np.float32).reshape(-1, 1, 3), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    out = np.clip(out, 0, 1)
    with open(path, 'w', encoding='ascii') as f:
        f.write(f'TITLE "{os.path.basename(path)}"\nLUT_3D_SIZE {N}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        f.write('\n'.join(f'{x:.6f} {y:.6f} {z:.6f}' for x, y, z in out))
        f.write('\n')


def lut_preview(rgb8, cube):
    """Apply a .cube to an RGB image with trilinear interpolation (preview only; ffmpeg does the real work)."""
    lines = [l for l in open(cube) if l[:1].isdigit() or l[:1] in '.-']
    t = np.array([[float(v) for v in l.split()] for l in lines], np.float32).reshape(N, N, N, 3)   # [b][g][r]
    x = rgb8.astype(np.float32) / 255 * (N - 1)
    i0 = np.floor(x).astype(int).clip(0, N - 2); f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]; fr, fg, fb = f[..., :1], f[..., 1:2], f[..., 2:]
    c = lambda db, dg, dr: t[b0 + db, g0 + dg, r0 + dr]
    out = (((c(0, 0, 0) * (1 - fr) + c(0, 0, 1) * fr) * (1 - fg) + (c(0, 1, 0) * (1 - fr) + c(0, 1, 1) * fr) * fg) * (1 - fb)
           + ((c(1, 0, 0) * (1 - fr) + c(1, 0, 1) * fr) * (1 - fg) + (c(1, 1, 0) * (1 - fr) + c(1, 1, 1) * fr) * fg) * fb)
    return (out * 255).clip(0, 255).astype(np.uint8)


def build(pr, ref, name, keys, strength, skin, tone):
    from PIL import Image, ImageDraw
    ref_frames = sample_frames(ref, 24)
    ours = []
    for k in keys:
        f = pr.path(pr.shot_file(k, prefer_beauty=False))   # graded shots: same colours, never mid-write by beautify
        ours += sample_frames(f, 4, 0, min(duration(f), 6))
    if not ref_frames or not ours:
        sys.exit('no usable frames')
    rs, os_ = stats(np.concatenate([lab_of(x) for x in ref_frames])), stats(np.concatenate([lab_of(x) for x in ours]))
    os.makedirs(pr.path('assets', 'luts'), exist_ok=True)
    cube = pr.path('assets', 'luts', f'{name}.cube')
    write_cube(cube, rs, os_, strength, skin, tone)
    fmt = lambda s: (f"L {s['q'][0]:.0f}/{s['q'][8]:.0f}/{s['q'][-1]:.0f}  ab sh {s['ab'][0][0]:+.1f},{s['ab'][0][1]:+.1f} "
                     f"mid {s['ab'][1][0]:+.1f},{s['ab'][1][1]:+.1f} hi {s['ab'][2][0]:+.1f},{s['ab'][2][1]:+.1f}  chroma {s['chroma']:.1f}  zones "
                     + ' '.join(f"{k} {z['share'] * 100:.0f}%/{z['hue']:.0f}deg/c{z['chroma']:.0f}" for k, z in s['zones'].items()))
    print(f'reference: {fmt(rs)}\nours:      {fmt(os_)}\nwrote {cube}')
    # review sheet: 4 of ours (before | after) + 4 reference frames
    pick = [ours[i] for i in np.linspace(0, len(ours) - 1, 4).astype(int)]
    refs = [ref_frames[i] for i in np.linspace(0, len(ref_frames) - 1, 4).astype(int)]
    f = font(20)
    sheet = Image.new('RGB', (270 * 12 + 40, 520), 'white'); d = ImageDraw.Draw(sheet)
    x = 0
    for a in pick:
        sheet.paste(Image.fromarray(a), (x, 30)); sheet.paste(Image.fromarray(lut_preview(a, cube)), (x + 270, 30)); x += 540
    d.text((4, 4), f'ours: before | after ({name}, strength {strength}, tone {tone}, skin {skin})', fill='red', font=f)
    x += 40; d.text((x + 4, 4), 'reference', fill='red', font=f)
    for a in refs:
        sheet.paste(Image.fromarray(a), (x, 30)); x += 270
    out = pr.path('review', f'look_{name}.jpg'); sheet.save(out, quality=88); print(out)


def apply(pr, name, outfits):
    edl = pr.load('edl.json')
    cube_rel = f'assets/luts/{name}.cube'                       # relative path: no drive-letter colon in the filter
    if not os.path.exists(pr.path(cube_rel)):
        sys.exit(f'no LUT {cube_rel}; run match_look.py build first')
    out_dir = pr.path('assets', 'shots_look', name); os.makedirs(out_dir, exist_ok=True)
    for o in outfits:
        for i in range(len(edl[o])):
            src = pr.shot_file(f'{o}_{i}')
            dst = f'assets/shots_look/{name}/{os.path.basename(src)}'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', f"lut3d='{cube_rel}':interp=tetrahedral,format=yuv420p",
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '15', '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709',
                            '-color_trc', 'bt709', '-colorspace', 'bt709', '-movflags', '+faststart', dst], check=True, cwd=pr.root)
            print(dst, flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = project_arg(sub.add_parser('build')); b.add_argument('ref'); b.add_argument('--name', required=True)
    b.add_argument('--shots', nargs='+', required=True); b.add_argument('--strength', type=float, default=0.85)
    b.add_argument('--skin', type=float, default=0.5, help='share of the colour shift applied to skin tones (0 = none, 1 = full)')
    b.add_argument('--tone', type=float, help='tone-curve strength (default: --strength)')
    p = project_arg(sub.add_parser('apply')); p.add_argument('name'); p.add_argument('outfits', nargs='+')
    a = ap.parse_args()
    pr = Project(a.project)
    if a.cmd == 'build':
        build(pr, a.ref, a.name, a.shots, a.strength, a.skin, a.strength if a.tone is None else a.tone)
    else:
        apply(pr, a.name, a.outfits)


if __name__ == '__main__':
    main()

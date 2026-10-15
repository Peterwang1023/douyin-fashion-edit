"""Style clone of a reference video: same length, same cut points, same music, matched colour look.

    python build_clone.py CLONE --project P      writes index.html, compositions/clone-CLONE-overlay.html, assets/bgm/clone-CLONE.m4a

Config (outfits.json "clones"):
    "A": {"name": "冷调街拍", "reference": "D:/模板库/306d..._raw.mp4", "outfit": "c1", "look": "cool306",
          "music": "reference", "captions": "brand+end", "threshold": 0.25}
- outfit: an EDL outfit whose shots map one-to-one onto the reference's shots (same count); each EDL
  duration should be >= the reference shot length (the builder trims to the reference timing).
- cuts: taken from the reference (scene detection with `threshold`), or give "cuts": [3.9, 8.83, ...].
- music: "reference" = the reference's own soundtrack, start to end (loudness-normalised); or a music.json name.
- look: a LUT made by match_look.py (shots come from assets/shots_look/<look>/); omit to use the plain retouched shots.
- captions: "none" | "brand" (quiet brand line) | "brand+end" (plus an end card over the last ~2.5 s).
"""
import html
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_reference import scene_cuts  # noqa: E402
from common import ASSETS, Project, brand_mode, duration, inject_css, peak_db, project_arg  # noqa: E402
from fonts import ensure_fonts  # noqa: E402


def build(pr, cid):
    cfg, edl = pr.load('outfits.json'), pr.load('edl.json')
    c = cfg['clones'][cid]
    ref = c['reference']
    total = round(duration(ref), 3)
    cuts = c.get('cuts') or scene_cuts(ref, c.get('threshold', 0.25))
    bounds = [0.0] + [float(x) for x in cuts] + [total]
    lens = [round(b - a, 3) for a, b in zip(bounds, bounds[1:])]
    if lens[-1] < 0.6 and len(lens) > 1:          # a fade-to-black tail belongs to the last shot
        lens[-2] += lens.pop()
    shots = edl[c['outfit']]
    if len(shots) != len(lens):
        sys.exit(f'clone {cid}: reference has {len(lens)} shots {lens}, EDL outfit {c["outfit"]} has {len(shots)}')

    look = c.get('look')
    files = []
    for i in range(len(shots)):
        f = pr.shot_file(f'{c["outfit"]}_{i}')
        if look:
            lf = f'assets/shots_look/{look}/{os.path.basename(f)}'
            if not os.path.exists(pr.path(lf)):
                sys.exit(f'{lf} missing; run match_look.py apply {look} {c["outfit"]}')
            f = lf
        if duration(pr.path(f)) < lens[i] - 0.05:
            sys.exit(f'{f} is {duration(pr.path(f)):.2f}s but the reference shot {i} needs {lens[i]:.2f}s')
        files.append(f)

    starts = [round(sum(lens[:i]), 3) for i in range(len(lens))]
    videos = [f'      <video id="shot-{i}" class="clip shot" src="{f}" muted playsinline data-start="{s0:.3f}" '
              f'data-duration="{L:.3f}" data-track-index="0"></video>' for i, (f, s0, L) in enumerate(zip(files, starts, lens))]

    os.makedirs(pr.path('assets', 'bgm'), exist_ok=True)
    bgm = f'assets/bgm/clone-{cid}.wav'   # PCM: no AAC priming delay, so the music stays sample-aligned with the cuts
    if c.get('music', 'reference') == 'reference' and peak_db(ref) < -60:
        sys.exit(f'clone {cid}: the reference soundtrack is silent, there is no music to copy; '
                 f'set "music" to a music.json name (music.py add / generate)')
    if c.get('music', 'reference') == 'reference':
        # the reference's own soundtrack, untouched apart from one static gain to ~-14 LUFS
        # (a dynamic loudnorm would flatten the drops and swells the user liked)
        meas = subprocess.run(['ffmpeg', '-i', ref, '-vn', '-af', 'ebur128=framelog=quiet', '-f', 'null', '-'], capture_output=True,
                              text=True, encoding='utf-8', errors='replace').stderr
        found = re.findall(r'I:\s+(-?[0-9.]+) LUFS', meas)
        gain = (-14.0 - float(found[-1])) if found else 0.0
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', ref, '-vn', '-t', f'{total:.3f}',
                        '-af', f'volume={gain:.2f}dB,alimiter=limit=0.89:level=disabled',
                        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', pr.path(bgm)], check=True)
    else:
        m = pr.load('music.json')[c['music']]
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(m['first_beat']), '-i', pr.path(m['file']), '-t', f'{total:.3f}', '-af',
                        f'aresample=48000,afade=t=in:d=0.04,afade=t=out:st={total - min(1.6, total * 0.25):.3f}:d={min(1.6, total * 0.25):.3f},loudnorm=I=-14:TP=-1.5:LRA=9',
                        '-ac', '2', '-c:a', 'pcm_s16le', pr.path(bgm)], check=True)

    cap = c.get('captions', 'brand')
    timing = {'total': total, 'brand': cap in ('brand', 'brand+end') and brand_mode(cfg)[0],
              'endIn': round(max(starts[-1] + 0.3, total - 2.6), 3) if cap == 'brand+end' else None}
    oid = f'clone-{cid}-overlay'
    ov = open(os.path.join(ASSETS, 'template-clone-overlay.html'), encoding='utf-8').read()
    for k, v in {'{{OID}}': oid, '{{BRAND}}': html.escape(brand_mode(cfg)[1]), '{{END_LINE}}': html.escape(cfg['endLine']),
                 '{{TIMING}}': json.dumps(timing)}.items():
        ov = ov.replace(k, v)
    ensure_fonts(pr)
    open(pr.path('compositions', oid + '.html'), 'w', encoding='utf-8').write(inject_css(ov, brand_mode(cfg)[2]))

    page = open(os.path.join(ASSETS, 'template-index.html'), encoding='utf-8').read()
    host = (f'      <div id="{oid}" data-composition-id="{oid}" data-composition-src="compositions/{oid}.html" '
            f'data-start="0" data-duration="{total:.3f}" data-track-index="2" data-width="1080" data-height="1920"></div>')
    page = re.sub(r'\n      <div\s+id="\{\{OID\}\}".*?></div>', '\n' + host, page, flags=re.S)
    page = (page.replace('{{ROOT_TWEENS}}', '').replace('{{ID}}', f'clone-{cid}').replace('{{TOTAL}}', f'{total:.3f}').replace('{{BGM}}', bgm)
            .replace('{{VIDEOS}}', '\n'.join(videos)))
    open(pr.path('index.html'), 'w', encoding='utf-8').write(page)
    print(f'clone-{cid}: {total:.2f}s  shots {lens}  look {look or "-"}  music {c.get("music", "reference")}')
    return total


if __name__ == '__main__':
    ap = project_arg(); ap.add_argument('clone')
    a = ap.parse_args()
    build(Project(a.project), a.clone)

"""Build one ~15 s single-outfit video: shots cut on the beat + wedding-style captions + music bed.

    python build_single.py OUTFIT --project P      writes index.html, compositions/overlay-OUTFIT.html, assets/bgm/outfit-OUTFIT.m4a

Then: npx hyperframes lint / render (render.py does build -> lint -> render -> review sheet in one go).

Inputs (config/): edl.json, outfits.json (captions, music mood, chipShots), music.json, avail.json.
Every shot becomes a whole number of beats (>= 2), never longer than its rendered file, never
running into footage another shot of the same outfit uses; whole beats are then added (last
shot first) until the video reaches ~targetSeconds (default 15).
"""
import html
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ASSETS, Project, project_arg  # noqa: E402
from fonts import ensure_fonts  # noqa: E402


def snap_cuts(durs, caps, beat, target):
    beats = []
    for d, a in zip(durs, caps):
        n = max(2, round(d / beat))
        while n > 1 and n * beat > a + 1e-6:
            n -= 1
        beats.append(n)
    order = [len(beats) - 1, 0] + list(range(1, len(beats) - 1))
    grown = True
    while sum(beats) * beat < target - beat / 2 and grown:
        grown = False
        for i in order:
            if (beats[i] + 1) * beat <= caps[i] + 1e-6 and beats[i] * beat < durs[i] + 1.2:
                beats[i] += 1
                grown = True
                if sum(beats) * beat >= target - beat / 2:
                    break
    return [round(n * beat, 3) for n in beats]


def music_bed(pr, m, total, out_rel):
    os.makedirs(pr.path('assets', 'bgm'), exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(m['first_beat']), '-i', pr.path(m['file']), '-t', f'{total:.3f}', '-af',
                    'aresample=48000,pan=stereo|c0=c0|c1=c0,afade=t=in:d=0.04,'
                    f'afade=t=out:st={total - 1.6:.3f}:d=1.6,loudnorm=I=-14:TP=-1.5:LRA=9',
                    '-ar', '48000', '-c:a', 'aac', '-b:a', '192k', pr.path(out_rel)], check=True)


def build(pr, oid):
    edl, cfg, music, avail = pr.load('edl.json'), pr.load('outfits.json'), pr.load('music.json'), pr.load('avail.json')
    o = cfg['outfits'][oid]
    if o.get('music') not in music:
        sys.exit(f'outfit {oid}: music "{o.get("music")}" not in music.json ({", ".join(music) or "empty"}); run music.py')
    m = music[o['music']]
    beat = 60.0 / m['bpm']
    shots = edl[oid]
    caps = []
    for i, s in enumerate(shots):
        cap = avail[f'{oid}_{i}']
        if len(s) > 3:                       # explicit max length (someone walks in after it, a phone comes out ...)
            cap = min(cap, s[3])
        for j, t2 in enumerate(shots):       # never run into footage another shot already uses
            if j != i and t2[0] == s[0] and t2[1] > s[1]:
                cap = min(cap, t2[1] - s[1])
        caps.append(cap)
    durs = snap_cuts([s[2] for s in shots], caps, beat, cfg.get('targetSeconds', 15.0))
    total = round(sum(durs), 3)
    starts = [round(sum(durs[:i]), 3) for i in range(len(durs))]

    bgm = f'assets/bgm/outfit-{oid}.m4a'
    music_bed(pr, m, total, bgm)

    videos = []
    for i, (shot, d) in enumerate(zip(shots, durs)):
        f = pr.shot_file(f'{oid}_{i}')
        videos.append(f'      <video id="shot-{i}" class="clip shot" src="{f}" muted playsinline '
                      f'data-start="{starts[i]:.3f}" data-duration="{d:.3f}" data-track-index="0"></video>')

    chips = '\n'.join(
        f'            <div class="chip"><span class="chip-k">{html.escape(k)}</span><span class="chip-dot"></span>'
        f'<span class="chip-v">{html.escape(v)}</span></div>' for k, v in o['items'])
    cs = o.get('chipShots') or [1, min(2, len(shots) - 2)]
    timing = {
        'total': total,
        'titleIn': 0.15,
        'titleOut': round(min(max(starts[1] - 0.35, 2.4), 3.0), 3),       # gone before heads rise into the top zone
        'chipsIn': round(starts[cs[0]] + 0.2, 3),                           # item lines only over full-body shots
        'chipsOut': round(starts[cs[1]] + durs[cs[1]] - 0.45, 3),
        'endIn': round(starts[-1] + 0.2, 3),
    }
    oid_name = f'overlay-{oid}'
    sub = {'{{ID}}': f'outfit-{oid}', '{{OID}}': oid_name, '{{TOTAL}}': f'{total:.3f}', '{{VIDEOS}}': '\n'.join(videos),
           '{{BGM}}': bgm, '{{BRAND}}': html.escape(cfg['brand']), '{{END_LINE}}': html.escape(cfg['endLine']),
           '{{TITLE}}': html.escape(o['title']), '{{SUBTITLE}}': html.escape(o['subtitle']), '{{CHIPS}}': chips,
           '{{TIMING}}': json.dumps(timing)}

    def fill(name):
        t = open(os.path.join(ASSETS, name), encoding='utf-8').read()
        for k, v in sub.items():
            t = t.replace(k, v)
        return t

    ensure_fonts(pr)
    os.makedirs(pr.path('compositions'), exist_ok=True)
    open(pr.path('compositions', oid_name + '.html'), 'w', encoding='utf-8').write(fill('template-overlay.html'))
    open(pr.path('index.html'), 'w', encoding='utf-8').write(fill('template-index.html'))
    print(f'outfit-{oid}: {total:.2f}s  beat {beat:.3f}s  shots {durs}')
    return total


if __name__ == '__main__':
    ap = project_arg(); ap.add_argument('outfit')
    a = ap.parse_args()
    build(Project(a.project), a.outfit)

"""Build an outfit-change compilation ("换装合集") in the style of a reference template.

    python build_combo.py COMBO --project P     writes index.html, compositions/combo-COMBO-*.html, assets/bgm/combo-COMBO.m4a

Shape (all of it configurable per combo in outfits.json "combos", see references/config.md):
    hook shot (beatsPerLook beats) with a bold outlined 2-3 line caption, music held back (low-passed)
    -> drop: one outfit per beatsPerLook beats; each change is a whip pan whose peak lands on the beat
       (transition "whip") or a hard cut on the beat (transition "cut")
    -> the last outfit holds finaleBeats beats; the brand card comes in over its second half.
Shots come from assets/shots_beauty (else assets/shots) via the EDL keys in the combo's segments.
"""
import html
import json
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ASSETS, Project, brand_mode, duration, inject_css, npx, project_arg  # noqa: E402
from fonts import ensure_fonts  # noqa: E402

WHIP = 0.5   # whip window, centred on the cut (peak velocity lands on the beat)
HOOK_TOP, HOOK_LINE = 170, 92


def whip_instance(pr, wid, before, after):
    """Copy of the registry whip-pan-cut component with unique ids and two video slots."""
    comp = pr.path('compositions', 'components', 'whip-pan-cut.html')
    if not os.path.exists(comp):
        npx('--yes', 'hyperframes', 'add', 'whip-pan-cut', '--no-clipboard', cwd=pr.root)
    s = open(comp, encoding='utf-8').read()
    s = s.replace('data-composition-id="whip-pan-cut"', f'data-composition-id="{wid}"')
    s = s.replace('var compositionId = "whip-pan-cut";', f'var compositionId = "{wid}";')
    s = s.replace('<div id="root"', f'<div id="{wid}-root"').replace('#root', f'#{wid}-root')
    s = s.replace('document.getElementById("root")', f'document.getElementById("{wid}-root")')
    s = s.replace('id="wpc-blur"', f'id="{wid}-blur"').replace('url("#wpc-blur")', f'url("#{wid}-blur")')
    s = s.replace('data-duration="1.2"', f'data-duration="{WHIP}"').replace('data-composition-duration="1.2"', f'data-composition-duration="{WHIP}"')
    s = s.replace(f'<div id="{wid}-root" data-composition-id="{wid}"', f'<div id="{wid}-root" data-composition-id="{wid}" data-width="1080" data-height="1920"')
    # the slot videos carry the timing, so the clip wrapper must not (lint: video_nested_in_timed_element)
    s, n = re.subn(r'id="whip-pan-cut-clip"\s+class="wpc-clip clip"\s+data-start="[^"]*"\s+data-duration="[^"]*"\s+data-track-index="[^"]*"',
                   f'id="{wid}-clip" class="wpc-clip"', s)
    if n != 1:
        sys.exit('whip-pan-cut component layout changed; update whip_instance() in build_combo.py')
    s = s.replace('.wpc-seam {', '.wpc-seam {\n            display: none;', 1)   # no accent seam line

    def video(vid, path, mstart):
        return f'<video id="{vid}" src="{path}" muted playsinline data-start="0" data-duration="{WHIP}" data-media-start="{mstart:.3f}"></video>'

    s = re.sub(r'(<div class="wpc-slot" data-slot="before">).*?(</div>\s*</section>)',
               lambda m: m.group(1) + '\n                ' + video(f'{wid}-a', *before) + '\n              ' + m.group(2), s, count=1, flags=re.S)
    s = re.sub(r'(<div class="wpc-slot" data-slot="after">).*?(</div>\s*</section>)',
               lambda m: m.group(1) + '\n                ' + video(f'{wid}-b', *after) + '\n              ' + m.group(2), s, count=1, flags=re.S)
    assert s.count('<video') == 2, wid
    return s


def hair_top(pr, key, t0, t1):
    """Lowest-risk estimate of the highest hair point in [t0, t1] from the retouch tracking cache (None if unknown)."""
    hits = [f for f in os.listdir(pr.path('cache')) if f.startswith(key + '_')] if os.path.isdir(pr.path('cache')) else []
    if not hits:
        return None
    z = np.load(pr.path('cache', hits[0]))
    fa, po = z['faces'], z['poses']
    tops = []
    for t in range(int(t0 * 30), min(int(t1 * 30), len(fa)), 3):
        if not np.isnan(fa[t, 0, 0]):
            fw = np.linalg.norm(fa[t, 234] - fa[t, 454])
            tops.append(fa[t, 10, 1] - 0.35 * fw - 85)            # forehead landmark -> hair top
        elif not np.isnan(po[t, 0, 0]):
            tops.append(po[t, 0, 1] - 0.55 * (po[t, [11, 12], 1].mean() - po[t, 0, 1]) - 85)
    return min(tops) if tops else None


def build(pr, cid):
    cfg, music = pr.load('outfits.json'), pr.load('music.json')
    c = cfg['combos'][cid]
    m = music[c['music']]
    beat = 60.0 / m['bpm']
    bpl = c.get('beatsPerLook', 4)
    look = bpl * beat
    transition = c.get('transition', 'whip')
    segs = [(None, c['hookShot'][0], c['hookShot'][1])] + [tuple(x[:3]) for x in c['segments']]
    labels_txt = [x[3] if len(x) > 3 else cfg['outfits'][x[0]]['items'][0][1] for x in c['segments']]
    lens = [look] * len(segs)
    lens[-1] = c.get('finaleBeats', 2 * bpl) * beat
    starts = [sum(lens[:i]) for i in range(len(segs))]
    total = round(sum(lens), 3)
    pre = WHIP / 2 if transition == 'whip' else 0

    files = [pr.shot_file(k) for _, k, _ in segs]
    for i, ((o, k, off), f, L) in enumerate(zip(segs, files, lens)):
        need = off + L + (pre if i < len(segs) - 1 else 0)
        if duration(pr.path(f)) < need - 0.02:
            sys.exit(f'{k}: shot is {duration(pr.path(f)):.2f}s, needs {need:.2f}s (offset {off}); lower the offset or re-cut the EDL shot longer')
        if i and off < pre:
            sys.exit(f'{k}: offset {off} leaves no pre-roll for the whip (needs >= {pre})')

    n_lines = len(c['hook'])
    hook_bottom = HOOK_TOP + n_lines * HOOK_LINE
    top = hair_top(pr, segs[0][1], segs[0][2], segs[0][2] + look)
    if top is not None and top < hook_bottom + 10:
        print(f'WARNING hook text (bottom ~{hook_bottom}px) may cover the head in {segs[0][1]} (hair top ~{int(top)}px): '
              f'pick a hook shot where she is further away or a later offset')

    oid = f'combo-{cid}'
    for f in os.listdir(pr.path('compositions')):           # stale whip instances from an earlier build
        if f.startswith(oid + '-whip'):
            os.remove(pr.path('compositions', f))
    videos, whips = [], []
    for i, ((o, k, off), f, s0, L) in enumerate(zip(segs, files, starts, lens)):
        videos.append(f'      <video id="seg-{i}" class="clip shot" src="{f}" muted playsinline data-start="{s0:.3f}" '
                      f'data-duration="{L:.3f}" data-media-start="{off:.3f}" data-track-index="0"></video>')
        if i and transition == 'whip':
            wid = f'{oid}-whip{i}'
            poff = segs[i - 1][2]
            s = whip_instance(pr, wid, (files[i - 1], poff + lens[i - 1] - WHIP / 2), (f, off - WHIP / 2))
            open(pr.path('compositions', wid + '.html'), 'w', encoding='utf-8').write(s)
            whips.append(f'      <div id="{wid}" data-composition-id="{wid}" data-composition-src="compositions/{wid}.html" '
                         f'data-variable-values=\'{{"whip_at":0,"direction":"{c.get("whipDirection", "left")}"}}\' data-start="{s0 - WHIP / 2:.3f}" '
                         f'data-duration="{WHIP}" data-track-index="1" data-width="1080" data-height="1920"></div>')

    # music: a downbeat lands exactly on the drop; the hook part is low-passed and quieter
    os.makedirs(pr.path('assets', 'bgm'), exist_ok=True)
    bgm = f'assets/bgm/{oid}.m4a'
    drop = starts[1]
    a0 = m['first_beat'] + c.get('musicOffsetBeats', bpl) * beat - drop
    if a0 < 0:
        a0 += int(np.ceil(-a0 / (bpl * beat))) * bpl * beat
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{a0:.3f}', '-i', pr.path(m['file']), '-t', f'{total:.3f}', '-filter_complex',
                    f'[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,asplit[h][d];'
                    f'[h]atrim=0:{drop:.3f},lowpass=f=500,volume=0.3,afade=t=in:d=0.3,afade=t=out:st={drop - 0.03:.3f}:d=0.03[h1];'
                    f'[d]atrim={drop:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={total - drop - 0.8:.3f}:d=0.8[d1];'
                    f'[h1][d1]concat=n=2:v=0:a=1,loudnorm=I=-14:TP=-1.5:LRA=9[out]',
                    '-map', '[out]', '-ar', '48000', '-c:a', 'aac', '-b:a', '192k', pr.path(bgm)], check=True)

    hook = '\n'.join(f'            <div class="hook-line">{html.escape(t)}</div>' for t in c['hook'])
    labels = '\n'.join(f'          <div id="label-{i}" class="label"><div class="label-n">第 {i + 1} 套</div>'
                       f'<div class="label-t">{html.escape(t)}</div></div>' for i, t in enumerate(labels_txt))
    end_in = round(starts[-1] + look + 0.1, 3)
    timing = {'total': total, 'hookOut': round(starts[1], 3), 'endIn': end_in,
              'labels': [[round(s0 + pre + 0.05, 3), round(min(s0 + L - pre, end_in - 0.1), 3)] for s0, L in zip(starts[1:], lens[1:])]}
    ov = open(os.path.join(ASSETS, 'template-combo-overlay.html'), encoding='utf-8').read()
    for k2, v in {'{{OID}}': f'{oid}-overlay', '{{HOOK_LINES}}': hook, '{{LABELS}}': labels, '{{BRAND}}': html.escape(brand_mode(cfg)[1]),
                  '{{END_LINE}}': html.escape(cfg['endLine']), '{{TIMING}}': json.dumps(timing),
                  '{{HOOK_COLOR}}': c.get('hookColor', '#ffe14a'), '{{HOOK_STROKE}}': c.get('hookStroke', '#111111')}.items():
        ov = ov.replace(k2, v)
    ensure_fonts(pr)
    open(pr.path('compositions', f'{oid}-overlay.html'), 'w', encoding='utf-8').write(inject_css(ov, brand_mode(cfg)[2]))

    page = open(os.path.join(ASSETS, 'template-index.html'), encoding='utf-8').read()
    host = (f'      <div id="{oid}-overlay" data-composition-id="{oid}-overlay" data-composition-src="compositions/{oid}-overlay.html" '
            f'data-start="0" data-duration="{total:.3f}" data-track-index="2" data-width="1080" data-height="1920"></div>')
    page = re.sub(r'\n      <div\s+id="\{\{OID\}\}".*?></div>', '\n' + host, page, flags=re.S)
    page = (page.replace('{{ROOT_TWEENS}}', '').replace('{{ID}}', oid).replace('{{TOTAL}}', f'{total:.3f}').replace('{{BGM}}', bgm)
            .replace('{{VIDEOS}}', '\n'.join(videos) + ('\n\n' + '\n'.join(whips) if whips else '')))
    open(pr.path('index.html'), 'w', encoding='utf-8').write(page)
    print(f'{oid}: {total:.2f}s  beat {beat:.3f}s  look {look:.2f}s  transition {transition}  starts {[round(x, 2) for x in starts]}')
    return total


if __name__ == '__main__':
    ap = project_arg(); ap.add_argument('combo')
    a = ap.parse_args()
    build(Project(a.project), a.combo)

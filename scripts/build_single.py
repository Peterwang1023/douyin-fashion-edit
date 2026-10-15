"""Build one ~15 s single-outfit video: shots cut on the beat + wedding-style captions + music bed.

    python build_single.py OUTFIT --project P      writes index.html, compositions/overlay-OUTFIT.html, assets/bgm/outfit-OUTFIT.m4a

Then: npx hyperframes lint / render (render.py does build -> lint -> render -> review sheet in one go).

Inputs (config/): edl.json, outfits.json (captions, music mood, chipShots), music.json, avail.json.
Every shot becomes a whole number of beats (>= 2), never longer than its rendered file, never
running into footage another shot of the same outfit uses; whole beats are then added (last
shot first) until the video reaches ~targetSeconds (default 15, per outfit or global; never longer
than the music).

Per-outfit options in outfits.json:
    "style": "wedding" (default) | "healing"   caption design (assets/template-overlay.html | template-healing-overlay.html)
    "motion": "kenburns"                        slow push-in / pull-out on every shot (alternating), smooth sub-pixel
    "look": "<lut name>"                        use assets/shots_look/<name>/ (match_look.py apply)
    healing style: "en" (small English line over the title), "lines": [[text, english, fromShot, toShot], ...],
                   "itemShots": [fromShot, toShot] (the "item | item" line); brand-wide "enBrand", "seal".
"""
import html
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ASSETS, Project, brand_mode, duration, inject_css, project_arg, shot_parts  # noqa: E402
from fonts import ensure_fonts  # noqa: E402
from build_combo import hair_top  # noqa: E402

# lowest pixel row each caption block reaches (1080x1920 canvas) for the horizontal (wedding) style
CAPTION_BOTTOM = {'wedding': {'title': 440, 'chips': 480, 'end': 450}}
# healing style is set vertically beside the subject: room needed from the frame edge (px)
SIDE_NEED = {'title': 260, 'lines': 180, 'item': 150, 'end': 270}


def body_room(pr, key, t0, t1, y0=250, y1=950):
    """(left room, right room) in px beside the body, rows y0..y1, robust over the window; None if untracked."""
    import numpy as np
    d = pr.path('cache')
    hits = [f for f in os.listdir(d) if f.startswith(key + '_')] if os.path.isdir(d) else []
    if not hits:
        return None
    z = np.load(os.path.join(d, hits[0]))
    po, fa = z['poses'], z['faces']
    lo, hi = [], []
    for t in range(int(t0 * 30), min(int(t1 * 30) + 1, len(po)), 3):
        pts = []
        if not np.isnan(po[t, 0, 0]):
            pts += [po[t, i, 0] for i in (0, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24) if po[t, i, 2] > 0.3 and y0 <= po[t, i, 1] <= y1]
        if not np.isnan(fa[t, 0, 0]):
            pts += [fa[t, 234, 0] - 30, fa[t, 454, 0] + 30]          # hair is wider than the face oval
        if pts:
            lo.append(min(pts)); hi.append(max(pts))
    if not lo:
        return None
    return float(np.percentile(lo, 8)), float(1080 - np.percentile(hi, 92))


def pick_side(pr, oid, starts, durs, a, b, need, label):
    rooms = []
    for i, (s0, d) in enumerate(zip(starts, durs)):
        lo, hi = max(a, s0), min(b, s0 + d)
        if hi - lo >= 0.1:
            r = body_room(pr, f'{oid}_{i}', lo - s0, hi - s0)
            if r:
                rooms.append(r)
    if not rooms:
        return 'left'
    left, right = min(r[0] for r in rooms), min(r[1] for r in rooms)
    side = 'left' if left - need >= right - need else 'right'
    if max(left, right) < need:
        print(f'WARNING {label} ({a:.1f}-{b:.1f}s): only {int(max(left, right))}px beside the body, needs {need}px '
              f'(pick a shot where she is further away or off-centre)')
    return side


def check_clearance(pr, oid, style, starts, durs, windows):
    """Warn when a caption block would sit on the head (uses the retouch tracking cache)."""
    bad = []
    for name, (a, b) in windows:
        kind = name.split(':')[0]
        bottom = CAPTION_BOTTOM[style].get(kind)
        if bottom is None:
            continue
        for i, (s0, d) in enumerate(zip(starts, durs)):
            lo, hi = max(a, s0), min(b, s0 + d)
            if hi - lo < 0.1:
                continue
            top = hair_top(pr, f'{oid}_{i}', lo - s0, hi - s0)
            if top is not None and top < bottom + 30:
                bad.append(f'{name} over shot {oid}_{i} ({lo:.1f}-{hi:.1f}s): hair top ~{int(top)}px, caption bottom ~{bottom}px')
    for b in bad:
        print('WARNING caption on head: ' + b)
    return bad


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


def chars(text):
    return ''.join('<span class="ch">&nbsp;</span>' if c == ' ' else f'<span class="ch">{html.escape(c)}</span>' for c in text)


def music_bed(pr, m, total, out_rel):
    os.makedirs(pr.path('assets', 'bgm'), exist_ok=True)
    fade = min(0.8, total * 0.1)      # short tail: the video loops on Douyin, a long fade-out reads as "the end" and loses the replay
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(m['first_beat']), '-i', pr.path(m['file']), '-t', f'{total:.3f}', '-af',
                    'aresample=48000,pan=stereo|c0=c0|c1=c0,afade=t=in:d=0.04,'
                    f'afade=t=out:st={total - fade:.3f}:d={fade:.3f},loudnorm=I=-14:TP=-1.5:LRA=9',
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
    parts = [shot_parts(s) for s in shots]
    for i, (k, st, d, mx, opts) in enumerate(parts):
        speed = float(opts.get('speed', 1.0))
        cap = avail[f'{oid}_{i}']
        if mx:                               # explicit max length (someone walks in after it, a phone comes out ...)
            cap = min(cap, mx)
        for j, (k2, st2, *_rest) in enumerate(parts):   # never run into footage another shot already uses
            if j != i and k2 == k and st2 > st:
                cap = min(cap, (st2 - st) / speed)
        caps.append(cap)
    music_len = duration(pr.path(m['file'])) - m['first_beat'] - 0.1
    target = min(float(o.get('targetSeconds', cfg.get('targetSeconds', 15.0))), music_len)
    durs = snap_cuts([p[2] for p in parts], caps, beat, target)
    while sum(durs) > music_len and durs[-1] > 2 * beat:      # never run past the end of the music
        durs[-1] = round(durs[-1] - beat, 3)
    total = round(sum(durs), 3)
    starts = [round(sum(durs[:i]), 3) for i in range(len(durs))]

    bgm = f'assets/bgm/outfit-{oid}.m4a'
    music_bed(pr, m, total, bgm)

    videos, tweens = [], []
    kb = o.get('motion') == 'kenburns'
    for i, (shot, d) in enumerate(zip(shots, durs)):
        f = pr.shot_file(f'{oid}_{i}')
        if o.get('look'):
            lf = f"assets/shots_look/{o['look']}/{os.path.basename(f)}"
            if not os.path.exists(pr.path(lf)):
                sys.exit(f"{lf} missing; run match_look.py apply {o['look']} {oid}")
            f = lf
        v = (f'<video id="shot-{i}" class="clip shot" src="{f}" muted playsinline '
             f'data-start="{starts[i]:.3f}" data-duration="{d:.3f}" data-track-index="0"></video>')
        if kb:   # the timed video sits in an untimed wrapper; the wrapper carries the camera move
            videos.append(f'      <div id="sw-{i}" class="shot-wrap">{v}</div>')
            a, b = (1.0, 1.07) if i % 2 == 0 else (1.07, 1.0)
            tweens.append(f'      tl.fromTo("#sw-{i}", {{ scale: {a} }}, {{ scale: {b}, duration: {d:.3f}, ease: "sine.inOut" }}, {starts[i]:.3f});')
        else:
            videos.append('      ' + v)

    chips = '\n'.join(
        f'            <div class="chip"><span class="chip-k">{html.escape(k)}</span><span class="chip-dot"></span>'
        f'<span class="chip-v">{html.escape(v)}</span></div>' for k, v in o['items'])
    cs = o.get('chipShots') or [1, min(2, len(shots) - 2)]
    timing = {
        'total': total,
        'titleIn': 0.0,                                                    # the title is the hook: on screen within the first second
        'titleOut': round(min(max(starts[1] - 0.35, 2.4), 3.0), 3),       # gone before heads rise into the top zone
        'chipsIn': round(starts[cs[0]] + 0.2, 3),                           # item lines only over full-body shots
        'chipsOut': round(starts[cs[1]] + durs[cs[1]] - 0.45, 3),
        'endIn': round(min(starts[-1] + 0.2, total - 2.0), 3),        # the end card always gets >= 2 s, no longer (completion rate)
    }
    oid_name = f'overlay-{oid}'
    style = o.get('style', 'wedding')
    lines_html = ''
    if style == 'healing':
        def win(a, b):
            return [round(starts[a] + 0.15, 3), round(starts[b] + durs[b] - 0.35, 3)]
        entries = [tuple(x) for x in o.get('lines', [])]
        if o.get('itemShots'):
            a, b = o['itemShots']
            entries.append((' ｜ '.join(v for _, v in o['items']), 'THE LOOK', a, b))
        entries.sort(key=lambda x: x[2])
        timing['lines'] = [win(a, b) for _, _, a, b in entries]
        rows, line_sides = [], []
        for i, ((t, e, a, b), (wa, wb)) in enumerate(zip(entries, timing['lines'])):
            item = e == 'THE LOOK'
            side = pick_side(pr, oid, starts, durs, wa, wb + 0.35, SIDE_NEED['item' if item else 'lines'], f'line {i}')
            line_sides.append(side)
            rows.append(f'        <div id="ln-{i}" class="vb lnb {side}"><div class="v {"v-it" if item else "v-ln"}">{chars(t)}</div>'
                        f'<div class="v v-ln-en">{html.escape(e)}</div></div>')
        lines_html = '\n'.join(rows)
        timing['sides'] = {'title': pick_side(pr, oid, starts, durs, timing['titleIn'], timing['titleOut'] + 0.5, SIDE_NEED['title'], 'title'),
                           'lines': line_sides,
                           'end': pick_side(pr, oid, starts, durs, timing['endIn'], total, SIDE_NEED['end'], 'end card')}
    show_brand, end_title, hide_css = brand_mode(cfg)
    brand = end_title          # what the end card shows; the brand itself only when showBrand is true
    sub = {'{{ID}}': f'outfit-{oid}', '{{OID}}': oid_name, '{{TOTAL}}': f'{total:.3f}', '{{VIDEOS}}': '\n'.join(videos),
           '{{ROOT_TWEENS}}': '\n'.join(tweens), '{{BGM}}': bgm, '{{BRAND}}': html.escape(brand),
           '{{BRAND_CHARS}}': chars(brand), '{{END_LINE}}': html.escape(cfg['endLine']),
           '{{TITLE}}': html.escape(o['title']), '{{TITLE_CHARS}}': chars(o['title']), '{{SUBTITLE}}': html.escape(o['subtitle']),
           '{{CHIPS}}': chips, '{{LINES}}': lines_html, '{{EN}}': html.escape(o.get('en', 'AUTUMN DIARY')),
           '{{EN_BRAND}}': html.escape(cfg.get('enBrand', 'AUTUMN · WINTER')), '{{SEAL}}': html.escape(cfg.get('seal', cfg['brand'][:2]) if show_brand else ''),
           '{{TIMING}}': json.dumps(timing), '{{SIDE_TITLE}}': timing.get('sides', {}).get('title', 'left'),
           '{{SIDE_END}}': timing.get('sides', {}).get('end', 'left')}

    def fill(name):
        t = open(os.path.join(ASSETS, name), encoding='utf-8').read()
        for k, v in sub.items():
            t = t.replace(k, v)
        return t

    ensure_fonts(pr)
    os.makedirs(pr.path('compositions'), exist_ok=True)
    if style == 'wedding':
        check_clearance(pr, oid, style, starts, durs, [('title', (timing['titleIn'], timing['titleOut'] + 0.5)),
                                                       ('end', (timing['endIn'], total)),
                                                       ('chips', (timing['chipsIn'], timing['chipsOut'] + 0.45))])
    tpl = {'wedding': 'template-overlay.html', 'healing': 'template-healing-overlay.html'}[style]
    open(pr.path('compositions', oid_name + '.html'), 'w', encoding='utf-8').write(inject_css(fill(tpl), hide_css))
    open(pr.path('index.html'), 'w', encoding='utf-8').write(fill('template-index.html'))
    print(f'outfit-{oid}: {total:.2f}s  beat {beat:.3f}s  shots {durs}')
    return total


if __name__ == '__main__':
    ap = project_arg(); ap.add_argument('outfit')
    a = ap.parse_args()
    build(Project(a.project), a.outfit)

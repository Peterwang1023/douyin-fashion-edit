"""Break down a reference / template video so its editing can be imitated with our own footage.

    python analyze_reference.py VIDEO --project P [--threshold 0.25]

Writes into <project>/review/ref_<name>/:
    sheet.jpg        4 fps contact sheet with timestamps (read captions, framing, outfit order)
    cut_<n>.jpg      every frame (30 fps) +-0.45 s around the first cuts (read the transition type)
    audio.wav        the soundtrack (mono)
    reference.json   numbers: cuts, shot lengths, tempo, beat phase, how well cuts sit on beats,
                     the hook length / music drop, and suggested build_combo.py parameters
Then follow references/imitate.md to turn this into a combo config.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, duration, font, probe, project_arg, video_size  # noqa: E402
from music import analyze as analyze_audio  # noqa: E402


def scene_cuts(path, thr):
    out = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-vf', f"select='gt(scene,{thr})',showinfo", '-an', '-f', 'null', '-'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    return [round(float(t), 3) for t in re.findall(r'pts_time:([0-9.]+)', out)]


def sheet(path, out, fps=4, tile=180):
    from PIL import Image, ImageDraw
    w, h = video_size(path)
    tw, th = (tile, int(tile * h / w) // 2 * 2) if h >= w else (int(tile * w / h) // 2 * 2, tile)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'fps={fps},scale={tw}:{th}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         capture_output=True).stdout
    n = len(raw) // (tw * th * 3); cols = 10; f = font(14)
    img = Image.new('RGB', (cols * tw, ((n + cols - 1) // cols) * th), 'white'); d = ImageDraw.Draw(img)
    for i in range(n):
        x, y = (i % cols) * tw, (i // cols) * th
        img.paste(Image.frombytes('RGB', (tw, th), raw[i * tw * th * 3:(i + 1) * tw * th * 3]), (x, y))
        d.text((x + 3, y + 3), f'{i / fps:.2f}', fill='yellow', font=f, stroke_width=2, stroke_fill='black')
    img.save(out, quality=88)


def around(path, t, out):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{max(t - 0.45, 0):.3f}', '-t', '0.9', '-i', path,
                    '-vf', 'fps=30,scale=120:-2,tile=14x2', '-frames:v', '1', '-update', '1', out], check=True)


def main():
    ap = project_arg(); ap.add_argument('video'); ap.add_argument('--threshold', type=float, default=0.25)
    a = ap.parse_args()
    pr = Project(a.project)
    name = re.sub(r'[^0-9A-Za-z]+', '', os.path.splitext(os.path.basename(a.video))[0])[:12] or 'ref'
    out = pr.path('review', f'ref_{name}'); os.makedirs(out, exist_ok=True)

    dur = duration(a.video)
    w, h = video_size(a.video)
    fps = probe(a.video, 'stream=r_frame_rate')[0]
    tags = ' '.join(probe(a.video, 'format_tags'))
    editor = 'CapCut/剪映' if ('TEEditor' in tags or 'te_is_reencode' in tags) else ('DJI' if 'DJI' in tags else 'unknown')

    cuts = scene_cuts(a.video, a.threshold)
    bounds = [0.0] + cuts + [dur]
    shots = [round(b - a_, 3) for a_, b in zip(bounds, bounds[1:])]
    sheet(a.video, os.path.join(out, 'sheet.jpg'))
    for i, t in enumerate(cuts[:3]):
        around(a.video, t, os.path.join(out, f'cut_{i}.jpg'))

    wav = os.path.join(out, 'audio.wav')
    has_audio = bool(probe(a.video, 'stream=codec_type')) and 'audio' in ' '.join(probe(a.video, 'stream=codec_type'))
    res = {'file': os.path.abspath(a.video), 'duration': round(dur, 3), 'size': [w, h], 'fps': fps, 'editor': editor,
           'cuts': cuts, 'shot_lengths': shots, 'median_shot': float(np.median(shots)) if shots else None}
    if has_audio:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', a.video, '-vn', '-ac', '1', '-ar', '32000', wav], check=True)
        mus = analyze_audio(wav, quiet=True)
        beat = 60 / mus['bpm']
        import soundfile as sf
        y, sr = sf.read(wav)
        hop = int(sr * 0.25)
        loud = [round(float(20 * np.log10(np.sqrt(np.mean(y[i:i + hop] ** 2)) + 1e-9)), 1) for i in range(0, len(y) - hop, hop)]
        jumps = np.diff(loud)
        drop = round(float((int(np.argmax(jumps[:max(1, len(jumps) // 2)])) + 1) * 0.25), 2) if len(jumps) > 2 else None
        cut_beats = [(t - mus['first_beat']) / beat for t in cuts]
        signed = [(b - round(b)) * beat for b in cut_beats]          # + = cut after the kick
        # a constant offset still means "on the grid": transitions often swap mid-move, a bit before/after the kick
        spacing = [round((b2 - b1) / beat, 2) for b1, b2 in zip(cuts, cuts[1:])]
        res.update({'bpm': mus['bpm'], 'first_beat': mus['first_beat'], 'loudness_0.25s': loud, 'music_drop_s': drop,
                    'cut_positions_in_beats': [round(b, 2) for b in cut_beats],
                    'cut_spacing_in_beats': spacing,
                    'grid_jitter_beats': round(float(np.std([s - round(s) for s in spacing])), 2) if spacing else None,
                    'cuts_on_regular_grid': bool(spacing) and float(np.std([s - round(s) for s in spacing])) < 0.3,
                    'cut_phase_offset_s': round(float(np.median(signed)), 3) if signed else None})
        real = [s for s in shots if s >= 0.6] or shots                # ignore a black / fade tail
        inner = real[1:-1] or real
        bpl = max(1, int(round(float(np.median(inner)) / beat)))
        res['suggest'] = {
            'beatsPerLook': bpl,
            'hook_seconds': cuts[0] if cuts else None,
            'finaleBeats': max(2 * bpl, int(round(real[-1] / beat))) if real else 2 * bpl,
            'music_bpm_target': mus['bpm'],
            'note': 'transition type, caption style and hook wording come from reading sheet.jpg / cut_*.jpg',
        }
    with open(os.path.join(out, 'reference.json'), 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    print(f'{os.path.basename(a.video)}: {dur:.2f}s {w}x{h} @ {fps} ({editor})')
    print(f'cuts ({len(cuts)}): {cuts}')
    print(f'shot lengths: {shots}  median {res["median_shot"]}')
    if has_audio:
        print(f'music ~{res["bpm"]} bpm, first beat {res["first_beat"]}s, drop at ~{res["music_drop_s"]}s')
        print(f'cut spacing in beats: {res["cut_spacing_in_beats"]}  regular grid: {res["cuts_on_regular_grid"]} '
              f'(jitter {res["grid_jitter_beats"]} beats; <0.12 = cut on the beat, 0.12-0.3 = roughly, timed by the action)  '
              f'phase vs kick: {res["cut_phase_offset_s"]:+.2f}s')
        print(f'suggested combo params: {res["suggest"]}')
    print(f'look at: {out}\\sheet.jpg and cut_*.jpg')


if __name__ == '__main__':
    main()

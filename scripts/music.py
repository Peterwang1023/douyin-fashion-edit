"""Background music: generate copyright-free beds locally, analyse tempo / beat phase, register them.

    python music.py presets                                          list mood presets
    python music.py generate MOOD [--seeds 2] [--seconds 20] --project P [--register]
    python music.py analyze FILE [--bpm-hint 125]
    python music.py add NAME FILE --project P [--bpm-hint 100]        copy + analyse + register in config/music.json

music.json: {"warm": {"file": "assets/bgm/src/warm_1.wav", "bpm": 101.4, "first_beat": 0.06}}
first_beat is the time of a kick-drum hit; the builders cut on that grid.

Generated music is MusicGen-small (no HeyGen / no network after the first model download,
~300 MB in the Hugging Face cache). It is fine as a placeholder bed; for reach on Douyin,
tell the user to swap in a trending track at publish time (the cuts are on a known BPM grid).
"""
import argparse
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, project_arg  # noqa: E402

PRESETS = {  # mood -> (prompt, target bpm)
    'warm': ("bright warm acoustic pop, fingerpicked acoustic guitar, soft piano, light claps and shaker, cheerful relaxed groove, 102 bpm, major key, sunny autumn fashion vlog, no vocals", 102),
    'chic': ("chic modern lounge pop, smooth electric piano, deep soft bass, crisp finger snaps, confident elegant walk, 96 bpm, stylish fashion runway, polished, no vocals", 96),
    'dusk': ("gentle romantic piano and strings, soft warm pads, light brushed drums, elegant evening mood, 90 bpm, major key, tender and graceful, no vocals", 90),
    'breeze': ("light breezy acoustic pop, bright acoustic guitar and soft piano, gentle claps and shaker, warm sunny autumn morning, 100 bpm, major key, no vocals", 100),
    'jazz': ("smooth light jazz pop, brushed drums, warm upright bass, mellow electric piano, elegant relaxed stroll, 96 bpm, major key, no vocals", 96),
    'healing': ("healing gentle acoustic music, soft felt piano and warm fingerpicked guitar, light soft percussion, airy pads, peaceful sunny afternoon, hopeful and tender, 96 bpm, major key, no vocals", 96),
    'runway': ("stylish fashion runway house track, punchy four on the floor kick, deep groovy bass, glossy synth chords, confident catwalk energy, 125 bpm, modern trendy, no vocals", 125),
}


def load_mono(path):
    import soundfile as sf
    a, sr = sf.read(path, always_2d=False)
    return (a if a.ndim == 1 else a.mean(1)).astype(np.float64), sr


def analyze(path, bpm_hint=None, quiet=False):
    from scipy.signal import butter, sosfilt
    a, sr = load_mono(path)
    hop, n = 512, 2048
    frames = np.lib.stride_tricks.sliding_window_view(a, n)[::hop] * np.hanning(n)
    lm = np.log1p(np.abs(np.fft.rfft(frames, axis=1)) * 10)
    flux = np.maximum(0, np.diff(lm, axis=0)).sum(1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    ac = np.correlate(flux, flux, 'full')[len(flux) - 1:]
    lags = np.arange(len(ac)); bpm_l = 60 * fps / np.maximum(lags, 1)
    m = (bpm_l >= 70) & (bpm_l <= 150)
    bpm = float(60 * fps / lags[m][np.argmax(ac[m])])
    if bpm_hint:
        for f in (2, 0.5, 1.5, 2 / 3):        # octave errors: prefer the multiple closest to the hint
            if abs(bpm * f - bpm_hint) < abs(bpm - bpm_hint):
                bpm = bpm * f
    beat = 60 / bpm
    # beat phase from the kick band (40-150 Hz): the grid offset with the most low-end energy
    sos = butter(4, [40, 150], btype='band', fs=sr, output='sos')
    k = np.abs(sosfilt(sos, a)); step = int(sr * 0.005)
    env = np.add.reduceat(k, np.arange(0, len(k) - step, step)) / step
    phases = np.arange(0, beat, 0.005)
    nb = int((len(a) / sr) / beat) - 1
    score = [sum(env[min(int(round((p + i * beat) / 0.005)), len(env) - 1)] for i in range(nb)) for p in phases]
    first = float(phases[int(np.argmax(score))])
    clipped = int((np.abs(a) >= 0.999).sum())
    rms = 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9)
    res = {'bpm': round(bpm, 1), 'first_beat': round(first, 3), 'dur': round(len(a) / sr, 2), 'clipped': clipped, 'rms_db': round(float(rms), 1)}
    if not quiet:
        print(f'{os.path.basename(path)}: {res}')
    return res


def generate(pr, mood, seeds, seconds, register):
    import torch
    import soundfile as sf
    from transformers import AutoProcessor, MusicgenConfig, MusicgenForConditionalGeneration
    # transformers 4.5x points MusicgenForConditionalGeneration.config_class at the decoder config,
    # which breaks from_pretrained; load the composite config explicitly.
    MusicgenForConditionalGeneration.config_class = MusicgenConfig
    mid = 'facebook/musicgen-small'
    prompt, target = PRESETS.get(mood, (mood, None))
    name = mood if mood in PRESETS else 'custom'
    proc = AutoProcessor.from_pretrained(mid)
    model = MusicgenForConditionalGeneration.from_pretrained(mid, config=MusicgenConfig.from_pretrained(mid))
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(dev)
    sr = model.config.audio_encoder.sampling_rate
    out_dir = pr.path('assets', 'bgm', 'src'); os.makedirs(out_dir, exist_ok=True)
    cands = []
    for seed in range(1, seeds + 1):
        torch.manual_seed(seed)
        inp = proc(text=[prompt], padding=True, return_tensors='pt').to(dev)
        audio = model.generate(**inp, do_sample=True, guidance_scale=3.5, max_new_tokens=int(seconds * 50))
        f = os.path.join(out_dir, f'{name}_gen{seed}.wav')
        n = 2
        while os.path.exists(f):            # never overwrite a track that may already be registered
            f = os.path.join(out_dir, f'{name}_gen{seed}_{n}.wav'); n += 1
        sf.write(f, audio[0, 0].cpu().numpy(), sr)
        cands.append((f, analyze(f, target)))
    if register:
        # least clipping first, then tempo closest to the target
        f, r = min(cands, key=lambda c: (c[1]['clipped'] > 50, abs(c[1]['bpm'] - (target or c[1]['bpm']))))
        reg(pr, name, f, r)


def reg(pr, name, f, r):
    m = pr.load('music.json', {})
    m[name] = {'file': os.path.relpath(f, pr.root).replace('\\', '/'), 'bpm': r['bpm'], 'first_beat': r['first_beat']}
    pr.save('music.json', m)
    print(f'registered {name}: {m[name]}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('presets')
    g = project_arg(sub.add_parser('generate')); g.add_argument('mood'); g.add_argument('--seeds', type=int, default=2)
    g.add_argument('--seconds', type=float, default=20); g.add_argument('--register', action='store_true')
    n = sub.add_parser('analyze'); n.add_argument('file'); n.add_argument('--bpm-hint', type=float)
    d = project_arg(sub.add_parser('add')); d.add_argument('name'); d.add_argument('file'); d.add_argument('--bpm-hint', type=float)
    a = ap.parse_args()
    if a.cmd == 'presets':
        for k, (p, b) in PRESETS.items():
            print(f'{k:8} {b} bpm  {p}')
    elif a.cmd == 'generate':
        generate(Project(a.project), a.mood, a.seeds, a.seconds, a.register)
    elif a.cmd == 'analyze':
        analyze(a.file, a.bpm_hint)
    else:
        pr = Project(a.project)
        dst_dir = pr.path('assets', 'bgm', 'src'); os.makedirs(dst_dir, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(a.file))
        dst = os.path.join(dst_dir, stem + '.wav')
        if ext.lower() in ('.wav', '.flac'):
            dst = os.path.join(dst_dir, os.path.basename(a.file))
            if os.path.abspath(a.file) != os.path.abspath(dst):
                shutil.copy2(a.file, dst)
        else:   # mp3 / m4a / a video: decode to wav once (also strips any picture stream)
            import subprocess
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', a.file, '-vn', '-ac', '2', '-ar', '44100', dst], check=True)
        reg(pr, a.name, dst, analyze(dst, a.bpm_hint))


if __name__ == '__main__':
    main()

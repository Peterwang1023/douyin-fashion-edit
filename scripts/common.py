"""Shared helpers for every script: project paths, config files, source lookup,
colour-grade filter, small ffmpeg wrappers.

A *project* is a HyperFrames project directory (created by init_project.py) with:
    config/      project.json, sources.json, edl.json, grade.json, outfits.json,
                 music.json, avail.json, retouch.json (optional)
    assets/      shots/ (graded), shots_beauty/ (retouched), bgm/, fonts/
    compositions/, renders/, review/, cache/
Every script takes --project (default: current directory).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL_DIR, 'assets')
W, H = 1080, 1920
MODEL_DIR = os.environ.get('DFE_MODEL_DIR') or os.path.join(os.path.expanduser('~'), '.cache', 'douyin-fashion-edit', 'models')

if hasattr(sys.stdout, 'reconfigure'):  # Chinese file names on a Windows console
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


class Project:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        if not os.path.exists(os.path.join(self.root, 'hyperframes.json')):
            sys.exit(f'not a project directory (no hyperframes.json): {self.root}\n'
                     f'create one with: python {os.path.join(SKILL_DIR, "scripts", "init_project.py")} <dir>')

    def path(self, *p):
        return os.path.join(self.root, *p)

    def cfg_path(self, name):
        return self.path('config', name)

    def load(self, name, default=None):
        p = self.cfg_path(name)
        if not os.path.exists(p):
            if default is None:
                sys.exit(f'missing config/{name} in {self.root}')
            return default
        with open(p, encoding='utf-8') as f:
            return json.load(f)

    def save(self, name, data):
        os.makedirs(self.path('config'), exist_ok=True)
        with open(self.cfg_path(name), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def sources(self):
        return self.load('sources.json', {})

    def source(self, key):
        s = self.sources()
        if key not in s:
            sys.exit(f'unknown source key {key!r}; run sources.py scan first (known: {", ".join(sorted(s)) or "none"})')
        return s[key]

    def shot_file(self, key, prefer_beauty=True):
        """Rendered shot for an EDL key like '03_2' -> 'assets/shots[_beauty]/03_2_<src>.mp4' (project-relative)."""
        for sub in (['shots_beauty', 'shots'] if prefer_beauty else ['shots']):
            d = self.path('assets', sub)
            if os.path.isdir(d):
                hit = sorted(f for f in os.listdir(d) if f.startswith(key + '_') and f.endswith('.mp4'))
                if hit:
                    return f'assets/{sub}/{hit[0]}'
        sys.exit(f'no rendered shot for {key}; run render_shots.py first')


def project_arg(parser=None):
    parser = parser or argparse.ArgumentParser()
    parser.add_argument('--project', default='.', help='project directory (default: .)')
    return parser


def grade_filter(L, Wm, Hl=0.5, size=f'{W}:{H}'):
    """ffmpeg filter chain for the house grade.
    L  lifts shadows/mids (0 none .. 3 strong), for under-exposed / backlit shots
    Wm warms (0 neutral .. 3), cancels the cool cast of shade and dusk
    Hl rolls off highlights (0.5 default .. 2.5), for sun-hit faces and skies; it also warms
       the top end so clipped skin does not turn cyan when pulled down."""
    c = lambda x: round(min(max(x, 0.0), 1.0), 3)
    pts = (f"0/0 0.1/{c(0.1 + 0.035 * L)} 0.25/{c(0.25 + 0.055 * L)} 0.5/{c(0.5 + 0.045 * L - 0.01 * Hl)} "
           f"0.7/{c(0.7 + 0.025 * L - 0.03 * Hl)} 0.85/{c(0.85 + 0.008 * L - 0.05 * Hl)} 0.95/{c(0.95 - 0.045 * Hl)} 1/{c(1 - 0.02 * Hl)}")
    f = [f"scale={size}:flags=lanczos", "format=gbrp16le", f"curves=master='{pts}'"]
    rh, gh, bh = 0.006 * Wm + 0.02 * Hl, 0.004 * Hl, -0.01 * Wm - 0.012 * Hl
    if Wm or Hl:
        f.append(f"colorbalance=rs={0.01 * Wm}:bs={-0.012 * Wm}:rm={0.018 * Wm}:bm={-0.02 * Wm}:rh={rh:.3f}:gh={gh:.3f}:bh={bh:.3f}:pl=1")
    f.append("eq=saturation=1.06")
    if L >= 2:
        f.append(f"hqdn3d={1 + 0.5 * L}:{1 + 0.5 * L}:4:4")
    return ','.join(f)


def brand_mode(cfg):
    """Platform-safe captions: unless outfits.json sets "showBrand": true, no shop name, seal or
    English brand line is drawn anywhere (Douyin flags a shop name / logo as steering viewers to
    off-platform or offline trading). The end card then shows "endTitle" instead of the brand.
    Returns (show_brand, end_title, css_to_hide_brand_elements)."""
    show = bool(cfg.get('showBrand', False))
    end_title = cfg['brand'] if show else cfg.get('endTitle', '秋冬穿搭')
    css = '' if show else ('\n        /* brand-free (platform-safe) mode */\n'
                           '        #brand, #brand-line, .seal, #e3 { display: none !important; }\n')
    return show, end_title, css


def inject_css(page, css):
    return page.replace('<style>', '<style>' + css, 1) if css else page


def shot_parts(s):
    """EDL entry -> (source key, in point s, duration s, max duration or None, options dict).
    Entry forms: [key, in, dur], [key, in, dur, max], [key, in, dur, {"speed": 0.7}], [key, in, dur, max, {...}].
    Durations are timeline (output) seconds; with speed < 1 the shot consumes dur * speed source seconds."""
    opts = s[-1] if isinstance(s[-1], dict) else {}
    rest = [x for x in s[3:] if not isinstance(x, dict)]
    return s[0], float(s[1]), float(s[2]), (float(rest[0]) if rest else None), opts


def peak_db(path):
    """Peak level of the audio in a file (dB), -inf when silent or there is no audio stream."""
    import re
    out = subprocess.run(['ffmpeg', '-i', path, '-vn', '-af', 'astats=metadata=0', '-f', 'null', '-'], capture_output=True,
                         text=True, encoding='utf-8', errors='replace').stderr
    m = re.findall(r'Overall[\s\S]*?Peak level dB:\s*(-?inf|-?[0-9.]+)', out) or re.findall(r'Peak level dB:\s*(-?inf|-?[0-9.]+)', out)
    return float(m[-1]) if m else float('-inf')


def need(tool):
    if not shutil.which(tool):
        sys.exit(f'{tool} not found on PATH')
    return tool


def probe(path, entries='format=duration'):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', entries, '-of', 'csv=p=0', path],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    return [x for x in out.replace('\r', '').split('\n') if x]


def duration(path):
    return float(probe(path)[0])


def video_size(path):
    """Displayed size: phone / DJI Mimo files are often stored landscape with a -90 rotation flag."""
    w, h = probe(path, 'stream=width,height')[0].split(',')[:2]
    rot = probe(path, 'stream_side_data=rotation')
    if any(r.strip().lstrip('-') in ('90', '270') for r in rot):
        w, h = h, w
    return int(w), int(h)


def grab_rgb(path, t, w, h, vf=None):
    """One frame at time t as an RGB numpy array of size (h, w)."""
    import numpy as np
    chain = f'scale={w}:{h}' + (',' + vf if vf else '') + ',format=rgb24'
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{max(t, 0):.3f}', '-i', path, '-frames:v', '1', '-vf', chain,
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    if len(raw) < w * h * 3:
        return None
    return np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3)


def npx(*args, cwd=None, check=True):
    exe = shutil.which('npx') or shutil.which('npx.cmd')
    if not exe:
        sys.exit('npx (Node.js) not found; install Node.js >= 18')
    return subprocess.run([exe, *args], cwd=cwd, check=check)


def font(size):
    from PIL import ImageFont
    for name in ('arial.ttf', 'DejaVuSans.ttf', 'Arial.ttf', '/System/Library/Fonts/Helvetica.ttc'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()

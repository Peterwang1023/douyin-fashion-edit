"""Trim + grade every EDL shot into assets/shots/<outfit>_<i>_<srckey>.mp4 (1080x1920, 30 fps, silent).

    python render_shots.py [OUTFIT ...] --project P [--jobs 3]

Each shot gets up to HANDLE extra seconds of tail (never past the source end) so the
builders can snap cuts to the beat and feed whip transitions. Real lengths go to config/avail.json.
Old files of a re-rendered outfit are removed first (a changed source key would otherwise linger).
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, duration, grade_filter, project_arg  # noqa: E402

HANDLE = 1.5


def main():
    ap = project_arg()
    ap.add_argument('outfits', nargs='*')
    ap.add_argument('--jobs', type=int, default=2, help='parallel ffmpeg encodes')
    a = ap.parse_args()
    pr = Project(a.project)
    edl, grade, src = pr.load('edl.json'), pr.load('grade.json'), pr.sources()
    avail = pr.load('avail.json', {})
    out_dir = pr.path('assets', 'shots'); os.makedirs(out_dir, exist_ok=True)
    jobs = []
    for o in a.outfits or sorted(edl):
        if o not in grade or len(grade[o]) < len(edl[o]):
            sys.exit(f'grade.json has no entry for every shot of {o}; run meter.py suggest {o}')
        for f in os.listdir(out_dir):
            if f.startswith(o + '_'):
                os.remove(os.path.join(out_dir, f))
        for k in [k for k in avail if k.startswith(o + '_')]:
            del avail[k]
        for i, (shot, g) in enumerate(zip(edl[o], grade[o])):
            jobs.append((o, i, shot, g))

    def run(job):
        o, i, shot, g = job
        k, st, d = shot[:3]
        L, Wm, Hl = (list(g) + [0.5])[:3]
        t = round(min(d + HANDLE, duration(src[k]) - st - 0.05), 3)
        out = os.path.join(out_dir, f'{o}_{i}_{k}.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(st), '-i', src[k], '-t', str(t), '-an',
                        '-vf', 'fps=30,' + grade_filter(L, Wm, Hl) + ',format=yuv420p',
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '15', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                        '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-movflags', '+faststart', out],
                       check=True)
        print(f'{o}_{i} {k} {t:.2f}s', flush=True)
        return f'{o}_{i}', t

    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        for key, t in ex.map(run, jobs):
            avail[key] = t
    pr.save('avail.json', dict(sorted(avail.items())))


if __name__ == '__main__':
    main()

"""Copy finished renders into the delivery folder with readable names and verify them.

    python finalize.py --project P --out <deliver dir> [--singles 01 02 ...] [--combos A B] [--covers]

    <out>/单套视频/01_条纹针织开衫.mp4      one video per outfit
    <out>/换装合集/合集A_外套篇.mp4          compilations
    <out>/仿模板视频/仿拍A_冷调街拍.mp4      style clones of reference videos

The shop name is appended (01_条纹针织开衫_<brand>.mp4) only when outfits.json sets "showBrand": true:
some upload pages pre-fill the post text from the file name.

Name parts come from outfits.json: outfits[x].fileName (else the first item's name) and combos[x].name.
Each file is checked for 1080x1920, duration and integrated loudness (target about -14 LUFS).
--covers also saves <out>/封面/<same name>.jpg: the frame at 1.2 s, where the title (or the hook) is fully
on screen, for the custom cover on the Douyin upload page.
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, brand_mode, duration, project_arg, video_size  # noqa: E402


def lufs(path):
    out = subprocess.run(['ffmpeg', '-i', path, '-af', 'ebur128=framelog=quiet', '-f', 'null', '-'], capture_output=True, text=True,
                         encoding='utf-8', errors='replace').stderr
    m = re.findall(r'I:\s+(-?[0-9.]+) LUFS', out)
    return float(m[-1]) if m else None


def safe(s):
    return re.sub(r'[\\/:*?"<>|\s]+', '', s)


def main():
    ap = project_arg()
    ap.add_argument('--out', required=True)
    ap.add_argument('--singles', nargs='*')
    ap.add_argument('--combos', nargs='*')
    ap.add_argument('--clones', nargs='*')
    ap.add_argument('--covers', action='store_true', help='also export a cover image per video into <out>/封面/')
    a = ap.parse_args()
    pr = Project(a.project)
    cfg = pr.load('outfits.json')
    brand = '_' + safe(cfg['brand']) if brand_mode(cfg)[0] else ''
    jobs = []
    for o in (a.singles if a.singles is not None else sorted(cfg['outfits'])):
        src = pr.path('renders', f'outfit-{o}.mp4')
        name = cfg['outfits'][o].get('fileName') or cfg['outfits'][o]['items'][0][1]
        jobs.append((src, os.path.join(a.out, '单套视频', f'{o}_{safe(name)}{brand}.mp4')))
    for c in (a.combos if a.combos is not None else sorted(cfg.get('combos', {}))):
        src = pr.path('renders', f'combo-{c}.mp4')
        jobs.append((src, os.path.join(a.out, '换装合集', f'合集{c}_{safe(cfg["combos"][c].get("name", ""))}{brand}.mp4')))
    for c in (a.clones if a.clones is not None else sorted(cfg.get('clones', {}))):
        src = pr.path('renders', f'clone-{c}.mp4')
        jobs.append((src, os.path.join(a.out, '仿模板视频', f'仿拍{c}_{safe(cfg["clones"][c].get("name", ""))}{brand}.mp4')))
    problems = 0
    for src, dst in jobs:
        if not os.path.exists(src):
            print(f'MISSING render {src}'); problems += 1; continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        w, h = video_size(dst); d = duration(dst); L = lufs(dst)
        flag = '' if (w, h) == (1080, 1920) and L is not None and abs(L + 14) < 1.5 else '   <-- check'
        problems += bool(flag)
        print(f'{os.path.relpath(dst, a.out)}  {w}x{h}  {d:.1f}s  {L} LUFS{flag}')
        if a.covers:
            cover = os.path.join(a.out, '封面', os.path.splitext(os.path.basename(dst))[0] + '.jpg')
            os.makedirs(os.path.dirname(cover), exist_ok=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{min(1.2, d / 3):.2f}', '-i', dst, '-frames:v', '1', '-q:v', '2', cover],
                           check=True)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()

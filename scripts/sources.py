"""Find the original clips, give each a short key, and spot app-cache junk.

    python sources.py scan <dir> [<dir> ...] --project P   register originals in config/sources.json
    python sources.py list --project P                     show registered sources
    python sources.py junk <dir> [--recycle]               list (or send to the recycle bin) preview/thumbnail
                                                           files that sit next to an original

Keys:  DJI_20261004165226_0002_D.MP4 -> 0002      (camera clip number)
       0d48f8ac93ea..._raw.mp4       -> 0d48      (DJI Mimo / app export: first hex chars)
       anything else                 -> short sanitised file stem
A DJI Mimo draft folder keeps, per clip: <hash>_raw.mp4 (the original, full resolution),
<hash>.mp4 (a 540p preview), <hash>.jpg and <hash>_thumb.jpg (thumbnails). Only _raw is footage.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Project, project_arg, probe, video_size  # noqa: E402

VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.mkv')


def info(path):
    try:
        v = probe(path, 'stream=codec_name,width,height,r_frame_rate')[0].split(',')
        d = float(probe(path)[0])
        w, h = video_size(path)      # honours the rotation flag
        return {'codec': v[0], 'w': w, 'h': h, 'fps': v[3], 'dur': round(d, 2)}
    except Exception:
        return None


def candidate_key(path):
    name = os.path.basename(path)
    m = re.match(r'DJI_\d+_(\d{4})_', name, re.I)
    if m:
        return m.group(1)
    m = re.match(r'([0-9a-f]{8,})_raw\.', name, re.I)
    if m:
        return m.group(1)[:4].lower()
    stem = re.sub(r'[^0-9A-Za-z]', '', os.path.splitext(name)[0])
    return (stem[-6:] or 'clip').lower()


def is_app_proxy(path):
    """<hash>.mp4 next to <hash>_raw.mp4 is the app's low-res preview."""
    stem, ext = os.path.splitext(path)
    return ext.lower() in VIDEO_EXT and not stem.endswith('_raw') and os.path.exists(stem + '_raw' + ext)


def walk(dirs):
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in sorted(files):
                yield os.path.join(root, f)


def scan(a):
    pr = Project(a.project)
    src = pr.sources()
    by_path = {os.path.normcase(v): k for k, v in src.items()}
    added = []
    for p in walk(a.dirs):
        if not p.lower().endswith(VIDEO_EXT) or is_app_proxy(p):
            continue
        p = os.path.abspath(p)
        if os.path.normcase(p) in by_path:
            continue
        i = info(p)
        if not i or min(i['w'], i['h']) < 720:
            print(f'skip (not an original / unreadable): {p}')
            continue
        k = candidate_key(p)
        base, n = k, 2
        while k in src:
            if os.path.basename(p).lower().endswith('_raw.mp4') and len(base) == 4:   # widen the hash prefix first
                base = re.match(r'([0-9a-f]+)', os.path.basename(p).lower()).group(1)[:len(base) + 2]
                k = base
            else:
                k = f'{base}{n}'; n += 1
        src[k] = p
        added.append((k, p, i))
    pr.save('sources.json', src)
    for k, p, i in added:
        orient = 'portrait' if i['h'] > i['w'] else 'LANDSCAPE'
        print(f'{k:>8}  {i["w"]}x{i["h"]} {orient:9} {i["codec"]:5} {i["fps"]:>10} {i["dur"]:6.2f}s  {p}')
    print(f'{len(added)} new, {len(src)} total sources')


def junk(a):
    found = []
    for p in walk(a.dirs):
        stem, ext = os.path.splitext(p)
        if is_app_proxy(p):
            i = info(p)
            if i and max(i['w'], i['h']) <= 1280:
                found.append(p)
        elif ext.lower() in ('.jpg', '.jpeg', '.png'):
            base = stem[:-6] if stem.endswith('_thumb') else stem
            if any(os.path.exists(base + '_raw' + e) for e in VIDEO_EXT):
                found.append(p)
    size = sum(os.path.getsize(p) for p in found) / 1e6
    for p in found:
        print(p)
    print(f'{len(found)} preview/thumbnail files, {size:.1f} MB (originals untouched)')
    if a.recycle and found:
        if os.name == 'nt':
            import tempfile
            with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8-sig') as tf:
                tf.write('\n'.join(found))       # paths via a UTF-8 file: console pipes mangle CJK names
            ps = (f"Add-Type -AssemblyName Microsoft.VisualBasic; Get-Content -LiteralPath '{tf.name}' -Encoding UTF8 | "
                  "ForEach-Object { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($_, 'OnlyErrorDialogs', 'SendToRecycleBin') }")
            subprocess.run(['powershell', '-NoProfile', '-Command', ps], check=True)
            os.remove(tf.name)
        else:
            try:
                from send2trash import send2trash
            except ImportError:
                sys.exit('pip install send2trash (refusing to hard-delete)')
            for p in found:
                send2trash(p)
        print('sent to the recycle bin')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = project_arg(sub.add_parser('scan')); s.add_argument('dirs', nargs='+')
    project_arg(sub.add_parser('list'))
    j = sub.add_parser('junk'); j.add_argument('dirs', nargs='+'); j.add_argument('--recycle', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'scan':
        scan(a)
    elif a.cmd == 'junk':
        junk(a)
    else:
        for k, p in sorted(Project(a.project).sources().items()):
            print(f'{k:>8}  {p}')


if __name__ == '__main__':
    main()

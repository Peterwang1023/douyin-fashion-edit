"""Check (and optionally install) everything the skill needs, and download the
MediaPipe models used for retouching.

    python setup_check.py            report only
    python setup_check.py --install  pip-install missing Python packages + download models
"""
import argparse
import importlib
import os
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MODEL_DIR  # noqa: E402

PY_PKGS = [  # (import name, pip name, needed for)
    ('numpy', 'numpy', 'everything'),
    ('PIL', 'pillow', 'contact sheets'),
    ('cv2', 'opencv-python', 'metering, retouch'),
    ('scipy', 'scipy', 'retouch smoothing, beat analysis'),
    ('mediapipe', 'mediapipe', 'retouch (face/pose tracking)'),
    ('soundfile', 'soundfile', 'music generation / analysis'),
    ('transformers', 'transformers', 'music generation (MusicGen)'),
    ('torch', 'torch', 'music generation (MusicGen)'),
]
MODELS = {
    'face_landmarker.task': 'face_landmarker/face_landmarker/float16/1/face_landmarker.task',
    'pose_landmarker_heavy.task': 'pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task',
    'selfie_multiclass_256x256.tflite': 'image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite',
}
MODEL_BASE = 'https://storage.googleapis.com/mediapipe-models/'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--install', action='store_true')
    a = ap.parse_args()
    ok = True

    for tool in ('ffmpeg', 'ffprobe'):
        p = shutil.which(tool)
        print(f'{"OK " if p else "MISSING"} {tool} {p or "(install ffmpeg and put it on PATH)"}')
        ok &= bool(p)
    node = shutil.which('npx') or shutil.which('npx.cmd')
    print(f'{"OK " if node else "MISSING"} npx {node or "(install Node.js >= 18; HyperFrames renders the captions)"}')
    ok &= bool(node)

    missing = []
    for mod, pipname, why in PY_PKGS:
        try:
            m = importlib.import_module(mod)
            print(f'OK  {pipname} {getattr(m, "__version__", "")}')
        except Exception:
            print(f'MISSING {pipname}  (for {why})')
            missing.append(pipname)
    if missing and a.install:
        subprocess.run([sys.executable, '-m', 'pip', 'install', *missing], check=False)
    elif missing:
        print(f'  -> pip install {" ".join(missing)}')
        ok = False

    os.makedirs(MODEL_DIR, exist_ok=True)
    for name, rel in MODELS.items():
        dst = os.path.join(MODEL_DIR, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 100_000:
            print(f'OK  model {name}')
        elif a.install:
            print(f'downloading {name} ...', flush=True)
            urllib.request.urlretrieve(MODEL_BASE + rel, dst)
            print(f'OK  model {name}')
        else:
            print(f'MISSING model {name}  -> run with --install')
            ok = False
    print(f'models: {MODEL_DIR}')

    try:  # the transformers 4.5x MusicGen config bug is patched at runtime by music.py
        import torch
        print(f'torch device: {"cuda (" + torch.cuda.get_device_name(0) + ")" if torch.cuda.is_available() else "cpu (music generation ~3 min per 20 s clip)"}')
    except Exception:
        pass
    print('READY' if ok else 'NOT READY')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()

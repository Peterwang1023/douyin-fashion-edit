"""Natural, temporally stable retouch of the graded shots (assets/shots -> assets/shots_beauty).

    python beautify.py [KEY ...] --project P [--jobs 3] [--force]   KEY like 03_1 (default: every stale shot)
    python beautify.py --preview KEY [KEY ...] --project P          before|after stills (+ face close-up) into review/

Face: wrinkle softening that keeps skin texture, brightening that spares already-bright skin,
less yellow, natural-red lips scaled to the face's own brightness, optional redness calming, soft blush, thin eyeliner,
slightly larger eyes, a smooth jawline slim. Body: slimmer waist/hips/thighs, ~4% longer legs
(extended downward so heads never rise into the caption zone).

Pass 1 tracks every frame (pose -> head crop -> 478-point face mesh; multiclass selfie
segmentation for skin) and caches it in <project>/cache. Pass 2 smooths all tracks over time
(zero-phase, offline), fades every effect in/out where tracking is missing, and applies all
geometry in one combined remap. Tiny or turned-away faces get no eye work at all.
Strengths can be overridden per project in config/retouch.json, e.g. {"eye_big": 0.08}.
"""
import os, subprocess, sys
import numpy as np, cv2
from scipy.ndimage import gaussian_filter1d
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MODEL_DIR, Project, W, H, project_arg  # noqa: E402

PR = None            # set in main()
SRC_DIR = OUT_DIR = CACHE_DIR = None

# default strengths: natural and slight; the subject must stay instantly recognisable
P = dict(
    brighten=9.0,        # L* lift at mid-skin (protects highlights)
    deyellow=0.85,       # b* multiplier on skin
    lip_a=0.55, lip_b=0.40, lip_dark=6.0,  # pull toward natural red (L*41 a*58 b*33)
    blush=7.0,           # a* added at blush centre
    redness=0.0,         # 0..1: share of the face's excess redness (a* above 12) taken out; for flushed / too-pink cheeks
    face_slim=0.065,     # lower face contour moved this fraction toward the face midline (peak)
    waist=0.06, hip=0.05, thigh=0.04, shoulder=0.02,
    legs=0.04,           # hip->ankle lengthening
    smooth=1.0,          # wrinkle softening amount on face skin (0..1)
    texture=0.45,        # share of fine skin texture kept so skin never looks plastic
    tone=0.5,            # evening of redness / spots (a*, b* smoothing)
    liner=0.6,           # eyeliner opacity (dark brown, thin, small wing)
    eye_big=0.13,        # eye enlargement at the eye centre (local magnification)
    smile=0.0,           # mouth-corner lift ("smile lips"), 1.0 ~ 10% of mouth width; off by default
)

FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176,
             149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LIP_OUT = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
EYE_L = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
EYE_R = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
BROW_L = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
BROW_R = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LID_L = [33, 246, 161, 160, 159, 158, 157, 173, 133]    # upper lid, outer -> inner corner
LID_R = [263, 466, 388, 387, 386, 385, 384, 398, 362]
LIP_IN = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
JAW_L = [234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152]   # ear -> chin, left side
JAW_R = [454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152]   # ear -> chin, right side
JAW_K = {234: .02, 93: .04, 132: .05, 58: 1, 172: 1, 136: 1, 150: 1, 149: .8, 176: .6, 148: .4,
         454: .02, 323: .04, 361: .05, 288: 1, 397: 1, 365: 1, 379: 1, 378: .8, 400: .6, 377: .4}


def model(name):
    path = os.path.join(MODEL_DIR, name)
    if not os.path.exists(path):
        sys.exit(f'model {name} missing; run setup_check.py --install')
    # load from a buffer: MediaPipe cannot open model paths containing non-ASCII characters
    return BaseOptions(model_asset_buffer=open(path, 'rb').read())


def read_frames(path):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    while True:
        buf = p.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        yield np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    p.stdout.close(); p.wait()


# ---------------------------------------------------------------- pass 1: track
def track(path):
    pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=model('pose_landmarker_heavy.task'), num_poses=1, min_pose_detection_confidence=0.4))
    face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=model('face_landmarker.task'), num_faces=1, min_face_detection_confidence=0.35,
        min_face_presence_confidence=0.35))
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=model('selfie_multiclass_256x256.tflite'), output_confidence_masks=True))
    poses, faces, skins, faceskins = [], [], [], []
    for fr in read_frames(path):
        small = cv2.resize(fr, (540, 960), interpolation=cv2.INTER_AREA)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(small))
        r = pose.detect(img)
        if r.pose_landmarks:
            pl = np.array([[l.x * W, l.y * H, l.visibility] for l in r.pose_landmarks[0]], np.float32)
        else:
            pl = np.full((33, 3), np.nan, np.float32)
        poses.append(pl)
        # face mesh on a head crop found from the pose (small faces in full-body shots)
        fl = np.full((478, 2), np.nan, np.float32)
        if not np.isnan(pl[0, 0]):
            head = pl[[0, 2, 5, 7, 8], :2]
            c = head.mean(0)
            size = max(np.ptp(head[:, 0]) * 1.6, np.linalg.norm(pl[0, :2] - pl[[11, 12], :2].mean(0)) * 0.9, 40)
            side = int(size * 2.6)
            x0, y0 = int(c[0] - side / 2), int(c[1] - side / 2)
            pad = cv2.copyMakeBorder(fr, side, side, side, side, cv2.BORDER_REPLICATE)
            crop = pad[y0 + side:y0 + 2 * side, x0 + side:x0 + 2 * side]
            crop = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_AREA if side > 512 else cv2.INTER_CUBIC)
            fr_ = face.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop)))
            if fr_.face_landmarks:
                fl = np.array([[x0 + l.x * side, y0 + l.y * side] for l in fr_.face_landmarks[0]], np.float32)
        faces.append(fl)
        s = seg.segment(img).confidence_masks
        body_skin, face_skin = s[2].numpy_view(), s[3].numpy_view()
        skins.append(cv2.resize(body_skin, (270, 480), interpolation=cv2.INTER_AREA).astype(np.float16))
        faceskins.append(cv2.resize(face_skin, (270, 480), interpolation=cv2.INTER_AREA).astype(np.float16))
    return np.array(poses), np.array(faces), np.array(skins, np.float32), np.array(faceskins, np.float32)


def smooth_track(a, sigma):
    """Interpolate NaN gaps per coordinate, then zero-phase gaussian smoothing over time."""
    a = a.copy(); T = a.shape[0]; t = np.arange(T)
    flat = a.reshape(T, -1)
    ok = ~np.isnan(flat[:, 0])
    if ok.sum() == 0:
        return a, np.zeros(T)
    for j in range(flat.shape[1]):
        flat[:, j] = np.interp(t, t[ok], flat[ok, j])
    flat[:] = gaussian_filter1d(flat, sigma, axis=0, mode='nearest')
    # effect strength: 1 while tracked, eased to 0 across tracking gaps (no pops)
    env = np.clip((gaussian_filter1d(ok.astype(np.float32), 3, mode='nearest') - 0.2) / 0.6, 0, 1)
    return flat.reshape(a.shape), env


# ---------------------------------------------------------------- pass 2: edit
def lab(img):
    return cv2.cvtColor(img, cv2.COLOR_RGB2LAB)


def rgb(l):
    return cv2.cvtColor(l, cv2.COLOR_LAB2RGB)


def poly_mask(shape, pts, blur):
    m = np.zeros(shape, np.float32)
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 1.0, lineType=cv2.LINE_AA)
    if blur > 0.3:
        m = cv2.GaussianBlur(m, (0, 0), blur)
    return m


def face_edits(img, fl, env, skin_m):
    """img float32 RGB 0..1 (full frame). Returns edited img and face-slim displacement (dx, dy) or None."""
    fw = np.linalg.norm(fl[234] - fl[454])
    if env <= 0.01 or fw < 20:
        return img, None
    x0, y0 = np.floor(fl.min(0) - fw * 0.6).astype(int)
    x1, y1 = np.ceil(fl.max(0) + np.array([fw * 0.6, fw * 1.3])).astype(int)    # reach down over the neck
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return img, None
    roi = img[y0:y1, x0:x1]
    L = lab(roi)
    o = np.array([x0, y0], np.float32)
    shp = roi.shape[:2]
    oval = poly_mask(shp, fl[FACE_OVAL] - o, fw * 0.02)

    # wrinkle softening: edge-preserving smoothing on face skin only (eyes, brows, lips excluded),
    # with part of the fine texture added back
    feat = np.zeros(shp, np.float32)
    for idx in (EYE_L, EYE_R, BROW_L, BROW_R, LIP_OUT):
        cv2.fillPoly(feat, [np.round(fl[idx] - o).astype(np.int32)], 1.0)
    feat = cv2.dilate(feat, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(fw * 0.05)) | 1,) * 2))
    feat = cv2.GaussianBlur(feat, (0, 0), max(1.0, fw * 0.02))
    sm_face = np.clip(oval - feat, 0, 1) * env * P['smooth']
    Lc = np.ascontiguousarray(L[..., 0])
    base = cv2.bilateralFilter(Lc, 0, 11.0, max(2.0, fw * 0.035))
    fine = Lc - cv2.GaussianBlur(Lc, (0, 0), max(0.6, fw * 0.004))
    L[..., 0] = Lc + (base + fine * P['texture'] - Lc) * sm_face
    for ch in (1, 2):
        c = L[..., ch]
        L[..., ch] = c + (cv2.GaussianBlur(c, (0, 0), max(1.5, fw * 0.02)) - c) * sm_face * P['tone']

    # eyeliner: thin dark-brown line on the upper lash line, thicker at the outer corner,
    # with a short wing; rasterised at 4x and downsampled so it stays clean when thin
    up = fl[10] - fl[152]; up = up / (np.linalg.norm(up) + 1e-6)
    liner = np.zeros(shp, np.float32)
    for lid in (LID_L, LID_R):
        pts = fl[lid]
        ew = np.linalg.norm(pts[0] - pts[-1])
        k_size = np.clip((ew - 10) / 12, 0, 1) * np.clip((ew / fw - 0.12) / 0.06, 0, 1)   # tiny / foreshortened eyes: skip
        if k_size <= 0.01:
            continue
        u = np.linspace(0, 1, len(pts))[:, None]
        t = ew * (0.065 * (1 - u) + 0.018 * u)
        outer, inner = pts[0], pts[-1]
        wd = (outer - inner) / (ew + 1e-6) * 0.9 + up * 0.45; wd /= np.linalg.norm(wd)
        tip = outer + wd * 0.17 * ew
        poly = np.concatenate([(pts - o), (pts + up * t - o)[::-1], [tip - o]])
        S4 = 4
        m4 = np.zeros((shp[0] * S4, shp[1] * S4), np.uint8)
        cv2.fillPoly(m4, [np.round(poly * S4).astype(np.int32)], 255, lineType=cv2.LINE_AA)
        m = cv2.resize(m4, (shp[1], shp[0]), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
        liner = np.maximum(liner, cv2.GaussianBlur(m, (0, 0), max(0.4, ew * 0.012)) * k_size)
    liner *= P['liner'] * env
    L[..., 0] += (20 - L[..., 0]) * liner
    L[..., 1] += (4 - L[..., 1]) * liner
    L[..., 2] += (6 - L[..., 2]) * liner

    # lips: outer minus inner mouth, feathered
    lips = np.clip(poly_mask(shp, fl[LIP_OUT] - o, 0) - poly_mask(shp, fl[LIP_IN] - o, 0), 0, 1)
    lips = cv2.GaussianBlur(lips, (0, 0), max(0.6, fw * 0.006)) * env
    # natural red scaled to the face's own brightness, so lips never glow on a dim face
    skin_L = float(np.median(L[..., 0][oval > 0.5])) if (oval > 0.5).any() else 60.0
    k = float(np.clip(skin_L / 72, 0.5, 1.0))
    L[..., 1] += (52 * k - L[..., 1]) * P['lip_a'] * lips
    L[..., 2] += (28 * k - L[..., 2]) * P['lip_b'] * lips
    L[..., 0] -= P['lip_dark'] * k * lips

    # blush: soft blobs on both cheeks, weakened on the side turned away, clipped to the face
    yy, xx = np.mgrid[0:shp[0], 0:shp[1]].astype(np.float32)
    blush = np.zeros(shp, np.float32)
    nose = fl[1] - o
    for idx in (50, 280):
        c = fl[idx] - o
        vis = np.clip(abs(c[0] - nose[0]) / (0.22 * fw), 0, 1) ** 1.5
        sg = 0.11 * fw
        blush += vis * np.exp(-((xx - c[0]) ** 2 + (yy - c[1]) ** 2) / (2 * sg * sg))
    no_lips = 1 - np.clip(lips * 3, 0, 1)
    if P['redness'] > 0:   # calm natural flush first, so the (lighter) blush lands on even skin
        soft = cv2.GaussianBlur(oval, (0, 0), max(1.0, fw * 0.05))   # wide feather: no edge against neck and ears
        L[..., 1] -= P['redness'] * np.clip(L[..., 1] - 12, 0, None) * soft * no_lips * env
    blush = np.clip(blush, 0, 1) * oval * no_lips * env
    L[..., 1] += P['blush'] * blush
    L[..., 2] += 2.0 * blush
    L[..., 0] -= 1.5 * blush

    # skin brightening (mid-tones only, highlights protected) + less yellow
    # skin mask limited to this ROI with feathered edges, so brightening never stops at a hard line
    hh, ww = shp
    ry = np.minimum(np.arange(hh), np.arange(hh)[::-1])[:, None] / max(1.0, 0.18 * hh)
    rx = np.minimum(np.arange(ww), np.arange(ww)[::-1])[None, :] / max(1.0, 0.18 * ww)
    sm = skin_m[y0:y1, x0:x1] * np.clip(np.minimum(ry, rx), 0, 1)
    # already-bright (sun-lit) skin gets almost no lift, so faces never go back to blown-out
    lift = P['brighten'] * np.sin(np.pi * np.clip(L[..., 0] / 100, 0, 1)) * np.clip((92 - L[..., 0]) / 25, 0, 1) * sm
    L[..., 0] += lift
    L[..., 2] = L[..., 2] * (1 - (1 - P['deyellow']) * sm)
    img = img.copy()
    img[y0:y1, x0:x1] = np.clip(rgb(L), 0, 1)

    # face slim: jaw contour pulled toward the face midline (backward displacement field)
    a, b = fl[168], fl[152]
    axis = (b - a) / (np.linalg.norm(b - a) + 1e-6)
    # the field is very smooth (r = 0.2 face widths), so build it on a coarse grid and upsample
    g = max(1, int(round(0.2 * fw / 6)))
    ys_c = np.arange(0, shp[0], g, dtype=np.float32); xs_c = np.arange(0, shp[1], g, dtype=np.float32)
    yc, xc = np.meshgrid(ys_c, xs_c, indexing='ij')
    dx = np.zeros(yc.shape, np.float32); dy = np.zeros(yc.shape, np.float32); wsum = np.zeros(yc.shape, np.float32)
    # dense, evenly spaced contour samples with a smooth strength profile:
    # 0 under the ear, peak along the lower cheek / jaw angle, easing off toward the chin,
    # so the new jawline stays one continuous curve (no bumps between landmarks)
    r = 0.2 * fw
    for half in (JAW_L, JAW_R):
        pts = fl[half]
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        cum = np.concatenate([[0], np.cumsum(seg)]); length = cum[-1]
        n = max(12, int(length / (0.025 * fw)))
        ss = np.linspace(0, length, n)
        samp = np.stack([np.interp(ss, cum, pts[:, 0]), np.interp(ss, cum, pts[:, 1])], 1)
        spacing = length / (n - 1)
        for (px, py), sv in zip(samp, ss / length):
            k = np.sin(np.pi * min(sv / 0.85, 1.0)) ** 1.3 if sv < 0.85 else 0.25 * (1 - sv) / 0.15
            p = np.array([px, py], np.float32)
            proj = a + axis * np.dot(p - a, axis)
            d = (proj - p) * P['face_slim'] * k * env
            c = p - o
            w = np.exp(-((xc - c[0]) ** 2 + (yc - c[1]) ** 2) / (2 * r * r)) * spacing / (r * 2.5066)
            dx += w * d[0]; dy += w * d[1]; wsum += w
    norm = np.maximum(wsum, 1.0)
    dx = cv2.resize(dx / norm, (shp[1], shp[0]), interpolation=cv2.INTER_LINEAR)
    dy = cv2.resize(dy / norm, (shp[1], shp[0]), interpolation=cv2.INTER_LINEAR)
    # eye enlargement: local magnification around each eye centre (output samples closer to the centre)
    for ring, lid in ((EYE_L, LID_L), (EYE_R, LID_R)):
        ew = np.linalg.norm(fl[lid[0]] - fl[lid[-1]])
        k_size = np.clip((ew - 8) / 10, 0, 1) * np.clip((ew / fw - 0.12) / 0.06, 0, 1)
        if k_size <= 0.01:
            continue
        c = fl[ring].mean(0) - o
        R = 1.15 * ew
        rx, ry = xx - c[0], yy - c[1]
        q = np.clip(1 - (rx * rx + ry * ry) / (R * R), 0, 1) ** 2
        s_ = P['eye_big'] * k_size * env * q
        dx += rx * s_; dy += ry * s_
    # smile lips: lift the two mouth corners up and a touch outward with a smooth local field;
    # fades out on small or turned faces (foreshortened mouth)
    mw = np.linalg.norm(fl[61] - fl[291])
    k_front = float(np.clip((mw / fw - 0.25) / 0.1, 0, 1)) * float(np.clip((mw - 14) / 10, 0, 1))
    if P['smile'] > 0 and k_front > 0.01:
        mid = (fl[61] + fl[291]) / 2
        r = 0.3 * mw
        for idx in (61, 291):
            c = fl[idx] - o
            outw = (fl[idx] - mid) / (np.linalg.norm(fl[idx] - mid) + 1e-6)
            d = (up * 0.10 + outw * 0.03) * mw * P['smile'] * env * k_front
            w = np.exp(-((xx - c[0]) ** 2 + (yy - c[1]) ** 2) / (2 * r * r))
            dx += w * d[0]; dy += w * d[1]
    return img, (x0, y0, dx, dy)


def body_strength(pl, env):
    """Raw per-frame strengths (body slim, leg stretch); smoothed over time by the caller."""
    if env <= 0.01 or np.isnan(pl).any():
        return 0.0, 0.0
    hip_vis = min(pl[23, 2], pl[24, 2])
    hip_y = pl[[23, 24], 1].mean()
    k_body = env * np.clip((hip_vis - 0.3) / 0.4, 0, 1)
    # legs: hips visible and in the upper 80% of frame; feet may run off the bottom edge
    k_legs = k_body * float(hip_y < 0.8 * H)
    return k_body, k_legs


def body_profile(pl, k_body, k_legs):
    """Per-row (y) centre x, half width, slim fraction, plus leg stretch (y_hip, y_ank, delta)."""
    if k_body <= 0.01 or np.isnan(pl).any():
        return (np.array([0, H], np.float32), np.zeros(2), np.ones(2), np.zeros(2)), (0, 0, 0)
    sh, hp, kn, an = [pl[[i, j], :2].mean(0) for i, j in ((11, 12), (23, 24), (25, 26), (27, 28))]
    torso = max(hp[1] - sh[1], 1)
    shw = abs(pl[11, 0] - pl[12, 0]); hipw = abs(pl[23, 0] - pl[24, 0])
    base = max(hipw, 0.35 * torso)
    ys = np.array([sh[1] - 0.25 * torso, sh[1], sh[1] + 0.6 * torso, hp[1], kn[1], an[1]])
    xs = np.array([sh[0], sh[0], (sh[0] + hp[0]) / 2, hp[0], kn[0], an[0]])
    hw = np.array([max(0.6 * shw, 0.3 * torso), max(0.6 * shw, 0.3 * torso), 0.75 * base, 0.95 * base, 0.8 * base, 0.65 * base])
    ss = np.array([0, P['shoulder'], P['waist'], P['hip'], P['thigh'], 0]) * k_body
    order = np.argsort(ys)
    ys, xs, hw, ss = ys[order], xs[order], hw[order], ss[order]
    return (ys, xs, hw, ss), (hp[1], an[1], P['legs'] * k_legs * max(an[1] - hp[1], 0))


def body_maps(prof, legs, up):
    """up: how much of the leg stretch lifts the upper body; the rest extends downward
    (so heads never rise into the caption zone)."""
    ys, xs, hw, ss = prof
    y_hip, y_ank, delta = legs
    yd = np.arange(H, dtype=np.float32)
    # undo the leg stretch (vertical), rows only
    if delta > 0.5:
        Lg = max(y_ank - y_hip, 1.0)
        up = float(np.clip(up, 0, delta)); down = delta - up
        ysrc = np.where(yd < y_hip - up, yd + up,
                        np.where(yd <= y_ank + down, y_hip + (yd - (y_hip - up)) * Lg / (Lg + delta), yd - down))
    else:
        ysrc = yd.copy()
    map_y = np.repeat(ysrc[:, None], W, 1).astype(np.float32)
    # undo the horizontal slim at the source row
    s = np.interp(ysrc, ys, ss, left=0, right=0)
    xc = np.interp(ysrc, ys, xs); h = np.interp(ysrc, ys, hw)
    xg = np.arange(W, dtype=np.float32)
    map_x = np.repeat(xg[None, :], H, 0).astype(np.float32)
    ug = np.linspace(-W * 1.5, W * 1.5, 1200, dtype=np.float32)
    for y in np.nonzero(s > 1e-4)[0]:
        R = 2.4 * h[y]
        au = np.abs(ug)
        f = np.where(au <= h[y], ug * (1 - s[y]),
                     np.where(au < R, np.sign(ug) * (au - s[y] * h[y] * (R - au) / (R - h[y])), ug))
        map_x[y] = xc[y] + np.interp(xg - xc[y], f, ug)
    return map_x, map_y


def process(key):
    src = [f for f in os.listdir(SRC_DIR) if f.startswith(key + '_')][0]
    path = os.path.join(SRC_DIR, src)
    cache = os.path.join(CACHE_DIR, src.replace('.mp4', '.npz'))
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(path):
        z = np.load(cache)
        poses, faces, skins, faceskins = z['poses'], z['faces'], z['skins'], z['faceskins']
    else:
        poses, faces, skins, faceskins = track(path)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        np.savez_compressed(cache, poses=poses, faces=faces, skins=skins.astype(np.float16), faceskins=faceskins.astype(np.float16))
        skins, faceskins = skins.astype(np.float32), faceskins.astype(np.float32)
    T = len(poses)
    pose_s, pose_env = smooth_track(poses[:, :, :2], 2.5)
    vis = gaussian_filter1d(np.nan_to_num(poses[:, :, 2]), 2.0, axis=0, mode='nearest')
    face_s, face_env = smooth_track(faces, 1.6)
    skins = gaussian_filter1d(skins.astype(np.float32), 1.5, axis=0, mode='nearest')
    faceskins = gaussian_filter1d(faceskins.astype(np.float32), 1.5, axis=0, mode='nearest')
    stats = dict(frames=T, pose=float((~np.isnan(poses[:, 0, 0])).mean()), face=float((~np.isnan(faces[:, 0, 0])).mean()))
    return path, src, T, pose_s, vis, pose_env, face_s, face_env, skins, faceskins, stats


def render(key, preview_at=None):
    path, src, T, pose_s, vis, pose_env, face_s, face_env, skins, faceskins, stats = process(key)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, src)
    if preview_at is None:   # a re-cut shot may have a new source key: drop the old file
        for f in os.listdir(OUT_DIR):
            if f.startswith(key + '_') and f != src:
                os.remove(os.path.join(OUT_DIR, f))
    enc = None
    if preview_at is None:
        enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', '30',
                                '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '15', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-movflags', '+faststart', out_path],
                               stdin=subprocess.PIPE)
    stills = []
    ks = np.array([body_strength(np.concatenate([pose_s[t], vis[t][:, None]], 1), pose_env[t]) for t in range(T)])
    k_body = gaussian_filter1d(ks[:, 0], 4, mode='nearest')
    k_legs = gaussian_filter1d(ks[:, 1], 8, mode='nearest')  # strong smoothing: the stretch shifts the upper body
    # how far the upper body may be lifted: keep the head top below the caption zone (y ~ 580)
    lifts = np.zeros(T)
    for t in range(T):
        pl = np.concatenate([pose_s[t], vis[t][:, None]], 1)
        delta = body_profile(pl, k_body[t], k_legs[t])[1][2]
        if face_env[t] > 0.3:
            top = face_s[t][10, 1] - 0.35 * np.linalg.norm(face_s[t][234] - face_s[t][454])
        elif pose_env[t] > 0.01:
            top = pose_s[t][0, 1] - 0.55 * (pose_s[t][[11, 12], 1].mean() - pose_s[t][0, 1])
        else:
            top = H
        lifts[t] = np.clip(top - 580, 0, delta)
    lifts = gaussian_filter1d(lifts, 8, mode='nearest')
    for t, fr in enumerate(read_frames(path)):
        if preview_at is not None and t not in preview_at:
            continue
        img = fr.astype(np.float32) / 255
        fl = face_s[t]
        # skin mask: face skin everywhere, body skin only near the neck and hands
        # masks are built at quarter resolution (the segmentation is 270x480 anyway) and upsampled once
        q4 = 0.25
        near = np.zeros((H // 4, W // 4), np.float32)
        pl = np.concatenate([pose_s[t], vis[t][:, None]], 1)
        if face_env[t] > 0.01 and pose_env[t] > 0.01:
            chin, shm = fl[152], pose_s[t][[11, 12]].mean(0)
            fw = np.linalg.norm(fl[234] - fl[454])
            cv2.ellipse(near, tuple(np.round((chin + (shm - chin) * 0.35) * q4).astype(int)), (int(fw * 0.7 * q4), int(max(fw * 0.6 * q4, 1))), 0, 0, 360, 1.0, -1)
        torso = 40 if pose_env[t] <= 0.01 else max(pose_s[t][[23, 24], 1].mean() - pose_s[t][[11, 12], 1].mean(), 40)
        for wi in (15, 16):
            if pose_env[t] > 0.01 and vis[t][wi] > 0.5:
                cv2.circle(near, tuple(np.round(pose_s[t][wi] * q4).astype(int)), max(1, int(torso * 0.18 * q4)), 1.0, -1)
        near = cv2.GaussianBlur(near, (0, 0), 3)
        skin_m = np.clip(faceskins[t] * face_env[t] + skins[t] * near * pose_env[t], 0, 1)
        skin_m = cv2.resize(cv2.GaussianBlur(skin_m, (0, 0), 0.5), (W, H), interpolation=cv2.INTER_LINEAR)
        img, fdisp = face_edits(img, fl, face_env[t], skin_m)
        prof, legs = body_profile(pl, k_body[t], k_legs[t])
        map_x, map_y = body_maps(prof, legs, min(lifts[t], legs[2]))
        if fdisp is not None:  # compose face-slim field (applied before the body warp)
            x0, y0, dx, dy = fdisp
            full_dx = np.zeros((H, W), np.float32); full_dy = np.zeros((H, W), np.float32)
            full_dx[y0:y0 + dx.shape[0], x0:x0 + dx.shape[1]] = dx
            full_dy[y0:y0 + dy.shape[0], x0:x0 + dy.shape[1]] = dy
            sx = cv2.remap(full_dx, map_x, map_y, cv2.INTER_LINEAR)
            sy = cv2.remap(full_dy, map_x, map_y, cv2.INTER_LINEAR)
            map_x = map_x - sx; map_y = map_y - sy
        out = cv2.remap(img, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        out8 = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
        if enc:
            enc.stdin.write(out8.tobytes())
        else:
            stills.append((t, fr, out8, fl if face_env[t] > 0.3 else None))
    if enc:
        enc.stdin.close(); enc.wait()
    print(key, stats, flush=True)
    return stills


def stale_keys(force):
    keys = []
    marks = [os.path.getmtime(__file__)]
    rj = PR.cfg_path('retouch.json')
    if os.path.exists(rj):
        marks.append(os.path.getmtime(rj))
    for f in sorted(os.listdir(SRC_DIR)):
        if not f.endswith('.mp4'):
            continue
        key = f.rsplit('_', 1)[0]
        out = os.path.join(OUT_DIR, f)
        if force or not os.path.exists(out) or os.path.getmtime(out) < max([os.path.getmtime(os.path.join(SRC_DIR, f))] + marks):
            keys.append(key)
    return keys


def preview(keys):
    from PIL import Image
    for key in keys:
        src = [f for f in os.listdir(SRC_DIR) if f.startswith(key + '_')][0]
        n = int(round(float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                                            os.path.join(SRC_DIR, src)], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout) * 30))
        for t, a, b, fl in render(key, {int(n * 0.3), int(n * 0.6)}):
            out = PR.path('review', f'beauty_{key}_{t}.jpg')
            Image.fromarray(np.concatenate([a, b], 1)).save(out, quality=92)
            print(out)
            if fl is not None:   # face close-up, 2x, before | after
                fw = np.linalg.norm(fl[234] - fl[454]); c = fl.mean(0); r = int(max(fw * 0.9, 60))
                x0, y0 = int(max(c[0] - r, 0)), int(max(c[1] - r, 0))
                x1, y1 = int(min(c[0] + r, W)), int(min(c[1] + r, H))
                im = Image.fromarray(np.concatenate([a[y0:y1, x0:x1], b[y0:y1, x0:x1]], 1))
                im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
                out = PR.path('review', f'beauty_{key}_{t}_face.jpg')
                im.save(out, quality=92)
                print(out)


def main():
    global PR, SRC_DIR, OUT_DIR, CACHE_DIR
    ap = project_arg()
    ap.add_argument('keys', nargs='*')
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--force', action='store_true', help='redo shots that are already up to date')
    ap.add_argument('--jobs', type=int, default=1, help='parallel worker processes (about 1.5 GB RAM each)')
    a = ap.parse_args()
    PR = Project(a.project)
    SRC_DIR, OUT_DIR, CACHE_DIR = PR.path('assets', 'shots'), PR.path('assets', 'shots_beauty'), PR.path('cache')
    os.makedirs(PR.path('review'), exist_ok=True)
    P.update(PR.load('retouch.json', {}))
    if a.preview:
        return preview(a.keys)
    keys = a.keys or stale_keys(a.force)
    if not keys:
        print('all retouched shots are up to date (use --force to redo)')
        return
    if a.jobs > 1 and len(keys) > 1:
        groups = [keys[i::a.jobs] for i in range(a.jobs)]
        procs = [subprocess.Popen([sys.executable, '-u', __file__, '--project', PR.root, *g]) for g in groups if g]
        sys.exit(max(p.wait() for p in procs))
    for key in keys:
        render(key)


if __name__ == '__main__':
    main()

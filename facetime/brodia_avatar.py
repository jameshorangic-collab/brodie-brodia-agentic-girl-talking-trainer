"""Brodia's character video: the practice partner for the job's scenario, then Coach Brodie for the feedback.

Partners (assets/avatar/brodia-avatars.json, `characters`): faceless figurine renders (612x408, transparent) with pixel centres
for the eyes, brows and mouth; this module draws those features on, in the same flat dark ink, the way facetime/avatar.py does
for Brodie's own puppet (that class and its landmarks.json are untouched). Scenario -> character comes from the JSON
(barista = Jess, park = Maya, street = Nadia). Jess's glasses are baked into her render (glassesBaked): no glasses overlay ever.

  - backdrop: a calm vertical gradient in the scenario's tint with a soft glow behind the head (no generated imagery);
  - the figurine is upscaled once (LANCZOS), its cut-off bottom edge faded into the backdrop, and composited onto three
    "breathing" plates (head 0/1/2 steps higher); per frame: copy a plate, draw eyes/brows/mouth with anti-aliased cv2;
  - eyes blink every 2.8-5.5 s (about 130 ms); the mouth is one dark rounded shape: open shapes cycle while the agent's
    audio is playing (speaking=True), a resting smile otherwise; receptivity tweaks the resting brows/mouth (interested a
    little warmer, uninterested flatter).

Coach (`coach` section): brodie-coach.png (default), -hype, -think. 1024x1024, faces BAKED IN: these are only scaled
(LANCZOS) and positioned, never drawn on or edited (brodie-character-kit rule). Gentle idle bob; while speaking a slightly
livelier bob and a small scale pulse. A small "Coach Brodie" label sits top-left, clear of the sprite.

    av = CharacterAvatar('barista', 'neutral', size=(540, 960))
    img = av.frame(speaking=True)               # (H, W, 3) uint8 RGB
    av.phase = 'coach'; av.coach_pose = 'hype'  # after the roleplay ends (the worker does this from FeedbackSession.finished)
    img = av.frame(speaking=True, inset=rgb)    # with a small caller-mirror inset (bottom right)

Worker (facetime/worker.py --avatar / BRODIA_AVATAR=1): run_for_job() publishes ONE video track TRACK_NAME ("brodia-avatar",
SOURCE_CAMERA) and feeds it from one loop; rendering and I420 conversion run in a worker thread. With --mirror as well, the
caller's pose mirror (facetime/brodia_mirror.py, pose lite on the newest caller frame at most --mirror-fps) is drawn as a
corner inset (~28 % of the width) inside the same track; with no (or stalled) caller video there is no inset.
Privacy: as for the mirror, caller frames are processed in memory only; nothing is written or logged.

Offline sheet: .venv/bin/python -m facetime.brodia_avatar [out_dir]
"""
import asyncio, json, math, os, random, sys, threading, time
import numpy as np
import cv2
from PIL import Image
from facetime import ROOT

PARTS = os.environ.get('RTCOACH_AVATAR_DIR', os.path.join(ROOT, 'assets', 'avatar'))
TRACK_NAME = 'brodia-avatar'
SIZES = {'portrait': (540, 960), 'landscape': (960, 540)}      # (W, H), the same shapes as the mirror (--mirror-shape)
SPEAKING_SHAPES = ['small', 'medium', 'o', 'small', 'wide', 'medium', 'o', 'mm']
MOUTH_STEP_S = 0.11
BLINK_EVERY = (2.8, 5.5); BLINK_S = 0.13
BREATH_S = 3.8; BOB_STEPS = 3
INSET_FRAC = 0.28
STALE_S = 3.0

# calm scenario tints: (top, bottom, glow) RGB
TINTS = {
    'barista': ((92, 66, 50), (36, 26, 21), (214, 168, 124)),
    'park':    ((70, 98, 74), (24, 38, 30), (184, 214, 160)),
    'street':  ((66, 74, 104), (22, 25, 38), (196, 178, 214)),
}
COACH_TINT = ((28, 52, 62), (10, 20, 26), (120, 190, 200))

# receptivity -> resting face (units of the JSON feature sizes): brow lift (+ = up), brow arch, smile depth, smile width
MOODS = {
    'interested':   dict(brow_lift=0.35, arch=0.85, smile=0.95, width=1.0),
    'neutral':      dict(brow_lift=0.0, arch=0.6, smile=0.6, width=0.9),
    'uninterested': dict(brow_lift=-0.25, arch=0.25, smile=0.18, width=0.75),
}


def load_spec(parts=PARTS):
    """brodia-avatars.json, validated: every character has a file, scenario, glassesBaked, two eyes, two brows and a mouth."""
    with open(os.path.join(parts, 'brodia-avatars.json')) as f: spec = json.load(f)
    for name, c in spec['characters'].items():
        assert os.path.exists(os.path.join(parts, c['file'])), f'{name}: {c["file"]} missing'
        assert len(c['eyes']) == 2 and len(c['brows']) == 2 and len(c['mouth']) == 2, f'{name}: features incomplete'
        assert isinstance(c.get('glassesBaked'), bool) and c.get('scenario'), f'{name}: glassesBaked/scenario missing'
    for pose in ('default', 'hype', 'think'):
        assert os.path.exists(os.path.join(parts, spec['coach']['poses'][pose]['file'])), f'coach {pose} missing'
    return spec


def character_for(scenario, spec):
    """'barista' -> 'jess' (from the JSON's scenario fields); an unknown scenario -> the park character."""
    by = {c['scenario']: name for name, c in spec['characters'].items()}
    return by.get(scenario) or by.get('park') or next(iter(spec['characters']))


def partner_features(c, spec, s, ox, oy):
    """Adapter: one JSON character's pixel centres and the shared sizes -> feature geometry on the output canvas
    (the source image scaled by s and placed with its top-left at (ox, oy))."""
    z = spec['sizes']; P = lambda p: (ox + p[0] * s, oy + p[1] * s)
    return dict(eyes=[(*P(e), z['eye']['rx'] * s, z['eye']['ry'] * s) for e in c['eyes']],
                brows=[(*P(b), z['brow']['w'] * s, z['brow']['h'] * s) for b in c['brows']],
                mouth=(*P(c['mouth']), z['mouth']['w'] * s, z['mouth']['h'] * s))


def backdrop(size, tint, glow_at):
    """Vertical gradient + a soft radial glow (uint8 RGB)."""
    W, H = size; top, bottom, glow = (np.array(t, np.float32) for t in tint)
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    img = top * (1 - y) + bottom * y
    gx, gy = glow_at; r = 0.55 * max(W, H)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = np.clip(1 - np.hypot(xx - gx, yy - gy) / r, 0, 1)[..., None] ** 2 * 0.28
    img = img * (1 - g) + glow * g
    return np.clip(img + 0.5, 0, 255).astype(np.uint8)


def _over(dst, rgba, x, y):
    """Alpha-composite an RGBA uint8 array onto dst (H, W, 3) at (x, y), clipped; in place."""
    H, W = dst.shape[:2]; h, w = rgba.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1: return dst
    src = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32); a = src[..., 3:4] / 255.0
    roi = dst[y0:y1, x0:x1].astype(np.float32)
    dst[y0:y1, x0:x1] = np.clip(roi * (1 - a) + src[..., :3] * a + 0.5, 0, 255).astype(np.uint8)
    return dst


def _q(p0, p1, p2, n=14):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


SHIFT = 4; ONE = 1 << SHIFT


def _pts(pts):
    return np.round(np.array(pts, np.float64) * ONE).astype(np.int32).reshape(-1, 1, 2)


class CharacterAvatar:
    def __init__(self, scenario='park', receptivity='neutral', size=SIZES['portrait'], parts=PARTS, spec=None, rng=None):
        self.parts = parts; self.spec = spec or load_spec(parts); self.size = W, H = tuple(size)
        self.scenario = scenario if scenario in TINTS else 'park'
        self.receptivity = receptivity if receptivity in MOODS else 'neutral'
        self.name = character_for(self.scenario, self.spec); self.char = self.spec['characters'][self.name]
        self.label = f'{self.name.capitalize()} · {self.scenario.capitalize()}'
        self.ink = tuple(self.spec['featureInk'][k] for k in 'rgb')
        self.rng = rng or random.Random()
        self.phase = 'partner'; self.coach_pose = 'default'
        portrait = H > W
        # partner layout: scale the figurine so the face reads at call size; the face anchor (between eyes and mouth) sits at
        # 42 % (portrait) / 52 % (landscape) of the height
        s = (1.55 * W / 540) if portrait else (1.2 * H / 540)
        ex = sum(e[0] for e in self.char['eyes']) / 2; ey = (self.char['eyes'][0][1] + self.char['mouth'][1]) / 2
        self.s = s
        self.ox = round(W / 2 - ex * s); self.oy = round(H * (0.46 if portrait else 0.54) - ey * s)
        self.step = max(1, round(s))                                   # breathing step in px
        src = Image.open(os.path.join(parts, self.char['file'])).convert('RGBA')
        fig = np.array(src.resize((round(src.width * s), round(src.height * s)), Image.LANCZOS))
        ext = max(0, H - (self.oy + fig.shape[0]))                     # the render is cut off at the bottom: continue the torso
        h0 = fig.shape[0]
        if ext:                                                         # (its last rows, blurred more and more with distance) and fade it out
            e = max(3, round(2 * s)); fig = fig[:-e]; ext += e; h0 -= e        # drop the render's soft edge rows (a visible seam)
            base = fig[-6:].astype(np.float32).mean(axis=0, keepdims=True); base[..., 3] = 255.0 * (base[..., 3] > 8)
            soft = cv2.GaussianBlur(base, (0, 0), sigmaX=5 * s); smooth = cv2.GaussianBlur(base, (0, 0), sigmaX=24 * s)
            k = np.clip(np.linspace(0, 1, ext, dtype=np.float32) / 0.35, 0, 1)[:, None, None]
            rows = soft * (1 - k) + smooth * k
            fig = np.concatenate([fig, np.clip(rows + 0.5, 0, 255).astype(np.uint8)], axis=0)
        fade = max(8, int(h0 * 0.12) + int(ext * 0.75)); tail = ext - int(ext * 0.75)
        ramp = np.ones(fig.shape[0], np.float32); n = fig.shape[0] - tail
        ramp[n - fade:n] = np.linspace(1, 0, fade, dtype=np.float32) ** 1.4; ramp[n:] = 0
        fig[..., 3] = (fig[..., 3].astype(np.float32) * ramp[:, None]).astype(np.uint8)
        self.figure = fig
        self.feat = partner_features(self.char, self.spec, s, self.ox, self.oy)
        self.bg = backdrop(self.size, TINTS[self.scenario], (W / 2, self.oy + ey * s - 0.05 * H))
        self.plates = [_over(self.bg.copy(), fig, self.ox, self.oy - k * self.step) for k in range(BOB_STEPS)]
        # coach: scaled sprites, cached per (pose, scale step)
        self.coach_bg = backdrop(self.size, COACH_TINT, (W / 2, H * 0.45))
        self.coach_box = round(min(W * 0.9, H * 0.78)) if portrait else round(H * 0.84)
        self._coach_cache = {}
        self.t0 = time.monotonic(); self._mouth_i = 0; self._mouth_t = -1.0
        self._blink_at = self.t0 + self.rng.uniform(*BLINK_EVERY)
        self.n = 0; self.ms = 0.0; self.blinks = 0
        self._inset_mask = None

    # ---- partner features ----
    def _eyes(self, img, dy, closed):
        for cx, cy, rx, ry in self.feat['eyes']:
            cy += dy
            if closed:                                                        # a closed lid: a short downward curve
                cv2.polylines(img, [_pts(_q((cx - rx * 1.1, cy), (cx, cy + ry * 0.45), (cx + rx * 1.1, cy)))], False, self.ink,
                              max(2, round(ry * 0.28)), cv2.LINE_AA, SHIFT)
                continue
            cv2.ellipse(img, (round(cx * ONE), round(cy * ONE)), (round(rx * ONE), round(ry * ONE)), 0, 0, 360, self.ink, -1, cv2.LINE_AA, SHIFT)
            gr = max(1.5, rx * 0.3)
            cv2.circle(img, (round((cx - rx * 0.32) * ONE), round((cy - ry * 0.4) * ONE)), round(gr * ONE), (246, 244, 238), -1, cv2.LINE_AA, SHIFT)

    def _brows(self, img, dy, lift=0.0):
        m = MOODS[self.receptivity]
        for i, (cx, cy, w, h) in enumerate(self.feat['brows']):
            y = cy + dy - (m['brow_lift'] + lift) * h
            arch = m['arch'] * h
            cv2.polylines(img, [_pts(_q((cx - w / 2, y + arch * 0.5), (cx, y - arch), (cx + w / 2, y + arch * 0.5)))], False, self.ink,
                          max(2, round(h * 0.75)), cv2.LINE_AA, SHIFT)

    def _mouth(self, img, dy, shape):
        cx, cy, w, h = self.feat['mouth']; cy += dy; half = w / 2; ink = self.ink
        m = MOODS[self.receptivity]; stroke = max(2, round(h * 0.42))
        def curve(span, depth, weight):
            cv2.polylines(img, [_pts(_q((cx - span, cy), (cx, cy + depth * 2), (cx + span, cy)))], False, ink, weight, cv2.LINE_AA, SHIFT)
        def blob(span, rise, depth):                                          # top edge (rise) and bottom edge (depth) curves
            up = _q((cx - span, cy), (cx, cy + rise * 2), (cx + span, cy)); down = _q((cx + span, cy), (cx, cy + depth * 2), (cx - span, cy))
            poly = _pts(up + down)
            cv2.fillPoly(img, [poly], ink, cv2.LINE_AA, SHIFT); cv2.polylines(img, [poly], True, ink, max(2, round(h * 0.3)), cv2.LINE_AA, SHIFT)
        if shape == 'rest': curve(half * m['width'], h * m['smile'] * 0.5, stroke)
        elif shape == 'mm': curve(half * 0.6, h * 0.12, stroke)
        elif shape == 'small': blob(half * 0.55, h * 0.1, h * 0.7)
        elif shape == 'medium': blob(half * 0.8, h * 0.05, h * 1.15)
        elif shape == 'wide': blob(half * 0.95, h * 0.12, h * 1.5)
        elif shape == 'o': cv2.ellipse(img, (round(cx * ONE), round((cy + h * 0.45) * ONE)), (round(half * 0.36 * ONE), round(h * 0.7 * ONE)), 0, 0, 360, ink, -1, cv2.LINE_AA, SHIFT)
        else: curve(half * m['width'], h * m['smile'] * 0.5, stroke)

    def mouth_shape(self, speaking, now):
        if not speaking: return 'rest'
        if now - self._mouth_t > MOUTH_STEP_S:
            self._mouth_i = (self._mouth_i + self.rng.choice((1, 1, 2))) % len(SPEAKING_SHAPES); self._mouth_t = now
        return SPEAKING_SHAPES[self._mouth_i]

    def blinking(self, now):
        if now >= self._blink_at + BLINK_S:
            self._blink_at = now + self.rng.uniform(*BLINK_EVERY)
        if self._blink_at <= now < self._blink_at + BLINK_S:
            if getattr(self, '_last_blink', None) != self._blink_at: self._last_blink = self._blink_at; self.blinks += 1
            return True
        return False

    def partner_frame(self, speaking=False, now=None, mouth=None, blink=None):
        now = time.monotonic() if now is None else now
        k = int((math.sin((now - self.t0) * 2 * math.pi / BREATH_S) + 1) / 2 * (BOB_STEPS - 0.001)); dy = -k * self.step
        img = self.plates[k].copy()
        closed = self.blinking(now) if blink is None else blink
        shape = mouth or self.mouth_shape(speaking, now)
        self._eyes(img, dy, closed)
        self._brows(img, dy, lift=0.18 if shape in ('wide', 'o') else 0.0)
        self._mouth(img, dy, shape)
        return img

    # ---- coach ----
    def coach_sprite(self, pose='default', step=0):
        key = (pose, step)
        if key not in self._coach_cache:
            f = self.spec['coach']['poses'][pose]['file']
            src = Image.open(os.path.join(self.parts, f)).convert('RGBA')
            side = round(self.coach_box * (1 + 0.015 * step))
            self._coach_cache[key] = np.array(src.resize((side, side), Image.LANCZOS))
        return self._coach_cache[key]

    def coach_layout(self, step=0, bob=0):
        W, H = self.size; side = round(self.coach_box * (1 + 0.015 * step))
        cy = H * (0.53 if H > W else 0.53)
        return round(W / 2 - side / 2), round(cy - side / 2 + bob)

    def coach_frame(self, speaking=False, now=None, pose=None, still=False):
        now = time.monotonic() if now is None else now; t = now - self.t0
        pose = pose or self.coach_pose
        if still: step, bob = 0, 0
        elif speaking: step = int((math.sin(t * 2 * math.pi / 0.9) + 1) / 2 * 2.999); bob = round(-abs(math.sin(t * math.pi / 0.45)) * 5 * self.step)
        else: step = 0; bob = round(math.sin(t * 2 * math.pi / BREATH_S) * 3 * self.step)
        img = self.coach_bg.copy(); x, y = self.coach_layout(step, bob)
        _over(img, self.coach_sprite(pose, step), x, y)
        self._label(img, 'Coach Brodie')
        return img

    # ---- labels / inset ----
    def _label(self, img, text):
        from facetime.brodia_mirror import _text, _layout
        W, H = self.size; L = _layout((W, H)); s = max(0.55, L['s'] * 1.2)
        top = int(H * (0.07 if H > W else 0.08))
        _text(img, text, (L['x'], top), 0.75 * s, (255, 255, 255), 1)

    def inset_size(self):
        W, H = self.size; iw = round(W * INSET_FRAC); return iw, round(iw * H / W)

    def _inset(self, img, inset):
        W, H = self.size; ih, iw = inset.shape[:2]
        x = W - iw - round(W * (0.06 if H > W else 0.03)); y = H - ih - round(H * (0.05 if H > W else 0.06))
        b = 2                                                                  # a thin light border, rounded like the inset
        if self._inset_mask is None or self._inset_mask.shape[:2] != (ih, iw):
            r = max(6, iw // 12)
            self._inset_mask = self._rounded(iw, ih, r); self._border_mask = self._rounded(iw + 2 * b, ih + 2 * b, r + b)
        self._blend(img, x - b, y - b, np.full((ih + 2 * b, iw + 2 * b, 3), (236, 240, 236), np.uint8), self._border_mask)
        self._blend(img, x, y, inset, self._inset_mask)
        return img

    @staticmethod
    def _rounded(w, h, r):
        m = np.zeros((h, w), np.uint8)
        cv2.rectangle(m, (r, 0), (w - 1 - r, h - 1), 255, -1); cv2.rectangle(m, (0, r), (w - 1, h - 1 - r), 255, -1)
        for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)): cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
        return (m.astype(np.float32) / 255.0)[..., None]

    @staticmethod
    def _blend(img, x, y, src, a):
        h, w = src.shape[:2]; roi = img[y:y + h, x:x + w]
        roi[:] = (src.astype(np.float32) * a + roi.astype(np.float32) * (1 - a) + 0.5).astype(np.uint8)

    # ---- one frame ----
    def frame(self, speaking=False, now=None, phase=None, inset=None, **kw):
        t = time.perf_counter()
        phase = phase or self.phase
        img = self.coach_frame(speaking, now, **kw) if phase == 'coach' else self.partner_frame(speaking, now, **kw)
        if phase != 'coach': self._label(img, self.label)
        if inset is not None: self._inset(img, inset)
        self.n += 1; self.ms += (time.perf_counter() - t) * 1000
        return img

    def stats(self):
        return dict(frames=self.n, ms_per_frame=round(self.ms / max(self.n, 1), 2), blinks=self.blinks, character=self.name, phase=self.phase)


def feedback_started(job):
    """True once the Brodia roleplay has ended and the coach feedback was asked for (FeedbackSession.finished)."""
    fb = getattr(getattr(job, 'voice', None), 'feedback', None)
    return bool(getattr(fb, 'finished', False))


def agent_speaking(job, window_s=0.15):
    """True while the agent's audio is going out (CuePlayer: a frame with real energy pushed within window_s)."""
    pl = getattr(job, 'player', None)
    try: return bool(pl is not None and pl.speaking(window_s))
    except Exception: return False


# ---- the worker side: one task per job (facetime/worker.py starts it with --avatar) ----
async def run_for_job(job, fps=15.0, shape='portrait', mirror=False, mirror_fps=10.0, variant='lite', pose_loader=None, flip=True):
    """Publish TRACK_NAME and feed it until the job closes. One loop, rendering in a worker thread. With mirror=True the caller's
    pose mirror is a corner inset (pose at most mirror_fps, newest caller frame only). Never raises into the job."""
    from livekit import rtc
    from facetime import brodia_mirror as bm
    fps = max(1.0, min(float(fps or 15.0), 30.0)); size = SIZES.get(shape, SIZES['portrait']); W, H = size
    a = getattr(job, 'a', None)
    scenario = getattr(a, 'brodia_scenario', None) or 'park'; receptivity = getattr(a, 'brodia_receptivity', None) or 'neutral'
    source = None; mir = None; job.avatar_track = None; job.avatar = None
    try:
        av = await asyncio.to_thread(CharacterAvatar, scenario, receptivity, size); job.avatar = av
        source = rtc.VideoSource(W, H)
        track = rtc.LocalVideoTrack.create_video_track(TRACK_NAME, source)
        source.capture_frame(bm.to_video_frame(av.frame()))
        await job.room.local_participant.publish_track(track, rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False, video_encoding=rtc.VideoEncoding(max_framerate=int(fps), max_bitrate=1_200_000)))
        job.avatar_track = track
        print(f'[avatar] published video track {TRACK_NAME} {W}x{H} at {fps:g} fps ({shape}); {av.label} ({receptivity})'
              + ('; caller pose mirror inset' if mirror else '') + '; frames are not stored', flush=True)
        if mirror:
            mir = bm.Mirror(None, av.inset_size(), None, flip); job.mirror = mir
            try: mir.pose = await asyncio.to_thread(pose_loader or bm.load_pose, variant)
            except Exception as e: print(f'[avatar] pose model unavailable ({type(e).__name__}: {e}): raw inset, no skeleton', flush=True)
        period = 1.0 / fps; pose_period = 1.0 / max(1.0, min(float(mirror_fps or 10.0), fps)); loop = asyncio.get_running_loop()
        next_t = loop.time(); last_seq = None; last_pose = -1e9; inset = None
        while not getattr(job, 'closed', False):
            if av.phase != 'coach' and feedback_started(job):
                av.phase = 'coach'; print('[avatar] roleplay over: switching to Coach Brodie for the feedback', flush=True)
            speaking = agent_speaking(job)
            frame = None
            if mir is not None:
                slot = getattr(job, 'latest', None); now = time.monotonic()
                if slot is None or now - slot[2] > STALE_S: inset = None
                elif slot[4] != last_seq and now - last_pose >= pose_period * 0.9: frame = slot[0]; last_seq = slot[4]; last_pose = now
            def render(frame=frame, speaking=speaking):
                nonlocal inset
                if frame is not None:
                    rgb = bm.frame_to_rgb(frame)
                    inset = bm.compose(rgb, mir.landmarks(rgb), None, av.inset_size(), mir.flip, tag=None)
                return bm.to_video_frame(av.frame(speaking=speaking, inset=inset))
            out = await asyncio.to_thread(render)
            if getattr(job, 'closed', False): break
            source.capture_frame(out)
            next_t += period; now = loop.time()
            if next_t < now: next_t = now
            await asyncio.sleep(next_t - now)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f'[avatar] stopped on an error ({type(e).__name__}: {e})', flush=True)
    finally:
        if mir is not None: threading.Thread(target=mir.close, daemon=True, name='avatar-mirror-close').start()
        if source is not None:
            try: await asyncio.wait_for(source.aclose(), 1.0)
            except BaseException: pass
        av_ = getattr(job, 'avatar', None)
        print(f'[avatar] end: {av_.stats() if av_ is not None else "not started"}', flush=True)


def sheet(out_dir):
    """Sample renders for the eye: each partner resting/speaking, receptivity variants, coach poses."""
    os.makedirs(out_dir, exist_ok=True); spec = load_spec(); paths = []
    for scen in ('barista', 'park', 'street'):
        av = CharacterAvatar(scen, 'neutral', spec=spec); now = av.t0 + 0.01
        for nm, kw in (('rest', dict(speaking=False)), ('speaking', dict(mouth='wide')), ('blink', dict(blink=True))):
            p = os.path.join(out_dir, f'{av.name}-{nm}.png'); Image.fromarray(av.frame(now=now, **kw)).save(p); paths.append(p)
    for rec in ('interested', 'neutral', 'uninterested'):
        av = CharacterAvatar('barista', rec, spec=spec); p = os.path.join(out_dir, f'jess-{rec}.png')
        Image.fromarray(av.frame(now=av.t0 + 0.01, blink=False)).save(p); paths.append(p)
    av = CharacterAvatar('park', 'neutral', spec=spec); av.phase = 'coach'
    for pose in ('default', 'hype', 'think'):
        p = os.path.join(out_dir, f'coach-{pose}.png'); Image.fromarray(av.frame(pose=pose, still=True)).save(p); paths.append(p)
    av = CharacterAvatar('street', 'interested', SIZES['landscape'], spec=spec)
    p = os.path.join(out_dir, 'nadia-landscape.png'); Image.fromarray(av.frame(now=av.t0 + 0.01, mouth='medium', blink=False)).save(p); paths.append(p)
    return paths


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', 'tmp', 'avatars')
    for p in sheet(out): print('wrote', p)

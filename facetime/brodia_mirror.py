"""Brodia pose mirror (P17-A): the agent's outgoing video track is the caller's own camera with their live pose skeleton drawn on it.

Why: the FaceTime path expects the agent to publish audio AND video, and a caller can see that pose detection is running. This
is a preview only: no rep count, no exercise bar, no fitness text, no score. A small scenario label (e.g. "Park · Neutral") and a
"pose preview" tag are drawn; before any caller frame arrives (or when the caller's video stalls) a calm placeholder frame is sent.

Per job (started by facetime/worker.py with --mirror / BRODIA_MIRROR=1):
  - publishes one video track TRACK_NAME ("brodia-mirror", SOURCE_CAMERA) as soon as the job is connected;
  - every 1/fps s (default 10) takes the worker's NEWEST received caller frame (job.latest, the same RGB24 frames the vision tee
    and vision notes read), and in a worker thread runs MediaPipe pose (lite, the rtcoach.pose.Pose wrapper vision_notes uses) on
    that one frame, draws the skeleton and the labels and converts to I420; the event loop only captures the result. Older frames
    are skipped, never queued. A pose failure (model missing, a MediaPipe error) shows the raw frame;
  - stops when the job ends (the task is cancelled by CoachJob.aclose); the pose model is closed after any in-flight frame.

Privacy: frames are processed in memory only. Nothing (frames, landmarks, composed images) is written to disk or logged; the composed
frame goes only to the caller's own room as the agent's video track.

Offline check (no LiveKit; writes nothing unless --out):
  .venv/bin/python -m facetime.brodia_mirror --video some_clip.mp4 [--out /tmp/mirror.png] [--shape landscape]
"""
import argparse, asyncio, os, sys, threading, time
import numpy as np
import cv2
from facetime.mirror import CONNECTIONS, VOLT, BLACK, WHITE, VIS

TRACK_NAME = 'brodia-mirror'
SIZES = {'portrait': (540, 960), 'landscape': (960, 540)}       # (W, H); portrait for FaceTime (phone), landscape for desktop browsers
BG = (18, 20, 24)
MUTED = (150, 155, 165)
STALE_S = 3.0             # newest caller frame older than this -> the placeholder ("camera paused")
FONT = cv2.FONT_HERSHEY_DUPLEX


def scenario_label(scenario, receptivity):
    """("park", "neutral") -> "Park · Neutral"; None when not a Brodia session."""
    if not scenario: return None
    return ' · '.join(s.strip().capitalize() for s in (scenario, receptivity) if s)


def _text(img, s, org, scale, color, thick=1, outline=True):
    """Hershey text; ' · ' is drawn as a small dot (Hershey has no middle dot)."""
    x, y = org
    parts = str(s).split(' · ')
    for i, part in enumerate(parts):
        if i:
            gap = int(22 * scale); cv2.circle(img, (x + gap // 2, y - int(9 * scale)), max(2, int(3 * scale)), color, -1, cv2.LINE_AA); x += gap
        if outline: cv2.putText(img, part, (x, y), FONT, scale, BLACK, thick + 3, cv2.LINE_AA)
        cv2.putText(img, part, (x, y), FONT, scale, color, thick, cv2.LINE_AA)
        x += cv2.getTextSize(part, FONT, scale, thick)[0][0]
    return x


def _text_width(s, scale, thick=1):
    parts = str(s).split(' · ')
    return sum(cv2.getTextSize(p, FONT, scale, thick)[0][0] for p in parts) + int(22 * scale) * (len(parts) - 1)


def _layout(size):
    W, H = size
    portrait = H > W
    # FaceTime on a phone: the island covers the top, the self-view the bottom left, "Fill" crops the sides -> keep text inside
    return dict(x=int(W * (0.12 if portrait else 0.04)), top=int(H * (0.14 if portrait else 0.08)), s=W / 720 if portrait else H / 720)


def labels(img, label, tag='pose preview'):
    """The scenario label top-left and a subtle tag under it; nothing else."""
    L = _layout((img.shape[1], img.shape[0])); s = max(0.6, L['s'] * 1.6)
    if label: _text(img, label, (L['x'], L['top']), 0.75 * s, WHITE, 1)
    if tag:
        y = L['top'] + int(30 * s)
        cv2.circle(img, (L['x'] + int(5 * s), y - int(5 * s)), max(2, int(4 * s)), VOLT, -1, cv2.LINE_AA)
        _text(img, tag, (L['x'] + int(16 * s), y), 0.5 * s, WHITE, 1)


def fit(rgb, lm, size):
    """Crop rgb to the output aspect around the person (mean x of the visible landmarks, else the centre) and scale to size.
    Returns (img, (x0, y0, cw, ch)) where the box is the crop in source pixels."""
    W, H = size; h, w = rgb.shape[:2]
    if w * H >= h * W:                                       # source wider than the output: crop the sides
        cw, ch = max(1, int(round(h * W / H))), h; cx = w / 2
        if lm is not None and len(lm):
            v = lm[:, 3] > VIS if lm.shape[1] > 3 else np.ones(len(lm), bool)
            if v.any(): cx = float(np.mean(lm[v, 0]) * w)
        x0 = int(round(min(max(cx - cw / 2, 0), w - cw))); y0 = 0
    else:                                                    # source taller: crop top/bottom, keep the upper part (the face)
        cw, ch = w, max(1, int(round(w * H / W))); x0 = 0; y0 = int(round((h - ch) * 0.3))
    crop = rgb[y0:y0 + ch, x0:x0 + cw]
    return cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA), (x0, y0, cw, ch)


def skeleton(img, lm, box, src_w, src_h):
    """Volt lines over black outlines (facetime/mirror.py style), landmarks with visibility > VIS only; scaled to the frame size."""
    W, H = img.shape[1], img.shape[0]; x0, y0, cw, ch = box; k = max(0.5, min(W, H) / 720)
    pts = []
    for row in lm:
        v = float(row[3]) if len(row) > 3 else 1.0
        pts.append((int((row[0] * src_w - x0) * W / cw), int((row[1] * src_h - y0) * H / ch), v))
    for a, b in CONNECTIONS:
        if a < len(pts) and b < len(pts) and pts[a][2] > VIS and pts[b][2] > VIS:
            cv2.line(img, pts[a][:2], pts[b][:2], BLACK, max(3, int(9 * k)), cv2.LINE_AA)
            cv2.line(img, pts[a][:2], pts[b][:2], VOLT, max(2, int(4 * k)), cv2.LINE_AA)
    for x, y, v in pts[11:]:
        if v > VIS:
            cv2.circle(img, (x, y), max(3, int(8 * k)), BLACK, -1, cv2.LINE_AA); cv2.circle(img, (x, y), max(2, int(5 * k)), VOLT, -1, cv2.LINE_AA)


def compose(rgb, lm=None, label=None, size=SIZES['portrait'], flip=True, tag='pose preview'):
    """Caller RGB frame (h, w, 3 uint8) + landmarks ((33, >=4) normalised [x, y, z, vis, ...] or None) -> (H, W, 3) uint8 RGB.
    flip mirrors the frame (selfie view); the landmarks are flipped with it."""
    src_h, src_w = rgb.shape[:2]
    if flip:
        rgb = rgb[:, ::-1]
        if lm is not None: lm = lm.copy(); lm[:, 0] = 1.0 - lm[:, 0]
    img, box = fit(rgb, lm, size)
    img = np.ascontiguousarray(img)
    if lm is not None: skeleton(img, lm, box, src_w, src_h)
    labels(img, label, tag)
    return img


def placeholder(label=None, size=SIZES['portrait'], message='Waiting for your camera'):
    """The calm frame sent before any caller video (or while it is stalled/off): dark background, the scenario, a line of text."""
    W, H = size; img = np.empty((H, W, 3), np.uint8); img[:] = BG
    s = max(0.6, min(W, H) / 540)
    cv2.circle(img, (W // 2, int(H * 0.42)), int(min(W, H) * 0.12), (40, 44, 52), -1, cv2.LINE_AA)
    cv2.circle(img, (W // 2, int(H * 0.42)), int(min(W, H) * 0.12), VOLT, max(1, int(2 * s)), cv2.LINE_AA)
    for line, sc, col, dy in ((label or 'Brodia practice', 0.9, WHITE, 0.58), (message, 0.6, MUTED, 0.63)):
        tw = _text_width(line, sc * s)
        _text(img, line, ((W - tw) // 2, int(H * dy)), sc * s, col, 1, outline=False)
    return img


def load_pose(variant='lite'):
    from rtcoach.pose import Pose                   # the same wrapper facetime/vision_notes.py uses (VIDEO mode)
    return Pose(variant=variant, video=True)


class Mirror:
    """Thread-safe renderer: render(rgb) runs pose on that one frame and composes. Pose errors fall back to the raw frame."""
    def __init__(self, label=None, size=SIZES['portrait'], pose=None, flip=True):
        self.label = label; self.size = tuple(size); self.pose = pose; self.flip = flip
        self.lock = threading.Lock(); self.t_ms = 0; self.n = 0; self.n_pose = 0; self.pose_errors = 0; self.ms = 0.0; self.pose_ms = 0.0
        self.placeholder_cache = {}

    def landmarks(self, rgb):
        with self.lock:
            if self.pose is None: return None
            t = time.perf_counter()
            self.t_ms = max(self.t_ms + 1, int(time.monotonic() * 1000))    # VIDEO mode needs strictly increasing timestamps
            try:
                lm, _ = self.pose(rgb, self.t_ms); self.n_pose += 1
            except Exception as e:
                self.pose_errors += 1
                if self.pose_errors == 1: print(f'[mirror] pose failed ({type(e).__name__}: {e}); showing the raw frame', flush=True)
                lm = None
            self.pose_ms += (time.perf_counter() - t) * 1000
            return lm

    def render(self, rgb):
        t = time.perf_counter()
        lm = self.landmarks(rgb)
        img = compose(rgb, lm, self.label, self.size, self.flip)
        self.n += 1; self.ms += (time.perf_counter() - t) * 1000
        return img

    def waiting(self, message='Waiting for your camera'):
        if message not in self.placeholder_cache: self.placeholder_cache[message] = placeholder(self.label, self.size, message)
        return self.placeholder_cache[message]

    def close(self):
        with self.lock:                                 # after any frame in flight
            p, self.pose = self.pose, None
        if p is not None:
            try: p.close()
            except Exception: pass

    def stats(self):
        return dict(frames=self.n, pose_frames=self.n_pose, pose_errors=self.pose_errors,
                    ms_per_frame=round(self.ms / max(self.n, 1), 1), pose_ms=round(self.pose_ms / max(self.n_pose, 1), 1))


def frame_to_rgb(frame):
    """rtc.VideoFrame -> (h, w, 3) uint8 (the worker's frames are RGB24 already; padded rows handled)."""
    from livekit import rtc
    if frame.type != rtc.VideoBufferType.RGB24: frame = frame.convert(rtc.VideoBufferType.RGB24)
    buf = np.frombuffer(frame.data, np.uint8); h, w = frame.height, frame.width
    if len(buf) == h * w * 3: return buf.reshape(h, w, 3)
    return buf.reshape(h, len(buf) // h)[:, :w * 3].reshape(h, w, 3)


def to_video_frame(img):
    from livekit import rtc
    h, w = img.shape[:2]
    return rtc.VideoFrame(w, h, rtc.VideoBufferType.RGB24, np.ascontiguousarray(img).tobytes()).convert(rtc.VideoBufferType.I420)


# ---- the worker side: one task per job (facetime/worker.py starts it with --mirror) ----
async def run_for_job(job, fps=10.0, shape='portrait', variant='lite', pose_loader=load_pose, flip=True):
    """Publish TRACK_NAME and feed it until cancelled. Reads job.latest (frame, ts_us, t_mono, t_wall, seq), job.closed, job.room,
    job.a.brodia_scenario/receptivity. Never raises into the job (a failure is logged once and the loop ends)."""
    from livekit import rtc
    fps = max(1.0, min(float(fps or 10.0), 30.0)); size = SIZES.get(shape, SIZES['portrait']); W, H = size
    a = getattr(job, 'a', None)
    mirror = Mirror(scenario_label(getattr(a, 'brodia_scenario', None), getattr(a, 'brodia_receptivity', None)), size, None, flip)
    source = None; job.mirror = mirror; job.mirror_track = None
    try:
        source = rtc.VideoSource(W, H)
        track = rtc.LocalVideoTrack.create_video_track(TRACK_NAME, source)
        source.capture_frame(to_video_frame(mirror.waiting()))                  # something to show the moment the track is up
        await job.room.local_participant.publish_track(track, rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False, video_encoding=rtc.VideoEncoding(max_framerate=int(fps), max_bitrate=1_000_000)))
        job.mirror_track = track
        print(f'[mirror] published video track {TRACK_NAME} {W}x{H} at {fps:g} fps ({shape}; label {mirror.label or "none"}); frames are not stored', flush=True)
        try:
            mirror.pose = await asyncio.to_thread(pose_loader, variant)
        except Exception as e:
            print(f'[mirror] pose model unavailable ({type(e).__name__}: {e}): raw frames, no skeleton', flush=True)
        period = 1.0 / fps; loop = asyncio.get_running_loop(); next_t = loop.time(); last_seq = None; out = None; state = None
        while not getattr(job, 'closed', False):
            slot = job.latest
            fresh = slot is not None and time.monotonic() - slot[2] <= STALE_S
            if fresh and slot[4] != last_seq:
                last_seq = slot[4]; frame = slot[0]
                out = await asyncio.to_thread(lambda: to_video_frame(mirror.render(frame_to_rgb(frame))))
                state = 'live'
            elif not fresh:
                msg = 'Waiting for your camera' if slot is None else 'Camera paused'
                if state != msg: out = to_video_frame(mirror.waiting(msg)); state = msg
            if out is not None: source.capture_frame(out)
            next_t += period; now = loop.time()
            if next_t < now: next_t = now                                      # a slow frame: skip ahead, never burst
            await asyncio.sleep(next_t - now)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f'[mirror] stopped on an error ({type(e).__name__}: {e})', flush=True)
    finally:
        threading.Thread(target=mirror.close, daemon=True, name='mirror-close').start()     # waits for a frame in flight, off the loop
        if source is not None:
            try: await asyncio.wait_for(source.aclose(), 1.0)
            except BaseException: pass
        print(f'[mirror] end: {mirror.stats()}', flush=True)


# ---- offline check ----
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--video', required=True); ap.add_argument('--out', default=None, help='write one composed frame here (optional)')
    ap.add_argument('--shape', default='portrait', choices=list(SIZES)); ap.add_argument('--frames', type=int, default=60)
    ap.add_argument('--label', default='Park · Neutral'); ap.add_argument('--pose', default='lite', choices=['lite', 'full', 'heavy'])
    a = ap.parse_args(argv)
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened(): print('cannot open the video', file=sys.stderr); return 1
    m = Mirror(a.label, SIZES[a.shape], load_pose(a.pose)); img = None; seen = 0
    for _ in range(a.frames):
        ok, bgr = cap.read()
        if not ok: break
        img = m.render(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)); seen += 1
    cap.release(); print(f'{seen} frames: {m.stats()}')
    if a.out and img is not None: cv2.imwrite(a.out, cv2.cvtColor(img, cv2.COLOR_RGB2BGR)); print('wrote', a.out)
    m.close(); return 0


if __name__ == '__main__':
    sys.exit(main())

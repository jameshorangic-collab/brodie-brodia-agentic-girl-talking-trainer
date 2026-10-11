"""Caller-video proof and ONE visible signal for Brodia (P08 + P09): is the caller facing the camera, turned away, or out of frame
(+ P17-B: distance to the camera, crossed arms, sideways lean).

Why one signal: Brodie's vision path is a ~1 fps scene reader, so anything finer (gaze percentages, micro-expressions, mood,
attraction) would be invented. Body/face orientation toward the camera is coarse, low frequency and checkable by anyone who
watches the same video, so it is the primary thing we report; P17-B adds three more signals of the same kind (each a coarse
geometric fact about the pose that anyone watching would agree on, never an interpretation of it). When the pose is unclear we ABSTAIN instead of guessing.

What it does, per job (started by the worker with --vision-notes, see facetime/worker.py):
  - samples the worker's newest received frame (job.latest, the same RGB24 frames the vision tee sends to the model) at
    --vision-notes-fps (default 1);
  - P08 frame proof: a 32x18 grey thumbnail per sample, mean absolute difference against the previous sample; the counters
    (samples, new frames, changed frames) go to stdout every 10 samples and into summary(). A stream that never changes, or a
    frame sequence that stops advancing, shows up here, not as a confident note;
  - P09 observation: MediaPipe pose (lite) on the sample -> classify() -> a label (facing_camera | turned_away | out_of_frame |
    unknown). A label becomes a note only once it holds for STABLE_N of the last WINDOW_N samples; one note per change. Notes are
    emitted as events of type vision_note (job.emit: the JSONL log, job.events, the handlers' on_event) and kept in memory;
  - P17-B extra channels (classify_all; judged only while the orientation sample is facing_camera, each abstains on its own):
    framing too_close | framing_ok | too_far (face size vs sqrt(frame area)), arms arms_crossed | arms_uncrossed (needs both
    elbows and wrists visible and in frame), lean leaning | upright (sideways only; needs both hips visible and in frame, so a
    head-and-torso phone framing abstains). Same STABLE_N of WINDOW_N rule per channel; baseline states (framing_ok,
    arms_uncrossed, upright) are counted but noted only when they end a problem state; observe_all() returns every new note;
  - every SUMMARY_EVERY samples a vision_summary event carries stats(): judged counts, shares and the longest stable stretch
    per label, which facetime/brodia.FeedbackSession turns into at most one strength and one improvement;
  - camera denied / audio-only call: no frame within NO_VIDEO_S of the caller binding -> one vision_note with
    source_verified false and summary() says visual evaluation is unavailable.

NOT inferred, by design: emotion, mood, attraction, interest, confidence, personality, gaze/eye contact, facial expression,
forward slouch. Thresholds are first estimates checked on synthetic landmarks only (scripts/test_brodia_pose_notes.py).

Nothing is stored but text: no frames, thumbnails or landmarks are written anywhere.

VisionNote fields (the shared contract in ivyhacks-brain ops/three-agent-sprint.md):
  observed_at               seconds on the job clock (the same clock as the events' t), when the state first appeared
  source_verified           True only when derived from real received caller frames
  observable_description    a plain phrase, e.g. "turned away from the camera"
  certainty                 "clear" | "uncertain"
  optional_nearby_utterance filled by attach_utterances() from the caller transcript, else None
  (+ signal, frame_seq, samples: for debugging)

Offline check (no LiveKit; a webcam or a video file; prints the notes):
  .venv/bin/python -m facetime.vision_notes --camera 0
  .venv/bin/python -m facetime.vision_notes --video some_clip.mp4
"""
import argparse, asyncio, collections, dataclasses, os, sys, time
import numpy as np

# MediaPipe pose landmark indices
NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SH, R_SH = 0, 2, 5, 7, 8, 11, 12
L_ELB, R_ELB, L_WR, R_WR, L_HIP, R_HIP = 13, 14, 15, 16, 23, 24

VIS_MIN = 0.6           # a landmark counts as visible above this MediaPipe visibility
# Head yaw (primary): |nose x - ear midpoint x| / half the ear distance. Measured with pose lite on 2026-10-10: a frontal portrait
# 0.00 (0.14 mirrored), a head in full profile 1.58 (2.37 mirrored). Between the bands we abstain.
FACING_MAX_YAW = 0.4
TURNED_MIN_YAW = 1.0
MIN_EAR_DIST = 0.01     # ears closer than this (fraction of frame width): yaw is not measurable, use the shoulder fallback
# Shoulder fallback (ears not usable): |nose offset from the shoulder midpoint| / half shoulder width.
MIN_SHOULDER_W = 0.06   # shoulders narrower than this (fraction of frame width) -> too far / too small to judge
FACING_MAX_OFF = 0.35
TURNED_MIN_OFF = 0.85
WINDOW_N = 4            # samples considered for stability
STABLE_N = 3            # samples (of WINDOW_N) that must agree before a label becomes a note
CHANGE_DIFF = 2.0       # mean abs grey difference (0..255) above which two samples count as visibly different
NO_VIDEO_S = 10.0       # caller bound but no frame this long -> visual evaluation unavailable
STALE_S = 3.0           # the newest frame is older than this -> the stream stalled; nothing is classified

# ---- P17-B extra channels (each abstains on its own; sizes use sqrt(frame area) as the unit so landscape and portrait agree) ----
# framing: ear-to-ear distance / sqrt(w*h), judged only while the orientation sample is facing_camera.
CLOSE_MIN_FACE = 0.38   # face this large or larger -> too_close (a webcam portrait at ~60 cm is about 0.15-0.25)
CLOSE_MIN_EYES = 0.15   # ears off-frame/unusable: eye-to-eye distance this large -> too_close (eyes ~0.4 of ear distance)
OK_FACE = (0.08, 0.30)  # comfortable distance band; between the bands we abstain
FAR_MAX_FACE = 0.05     # face this small or smaller -> too_far
FAR_MAX_SHOULDER = 0.12 # ears unusable: shoulder width / sqrt(w*h) this small -> too_far
# arms: both elbows and both wrists visible (ARM_VIS_MIN) and inside the frame; offsets in half shoulder widths from the
# shoulder midline, measured toward the OPPOSITE shoulder (mirror-invariant).
ARM_VIS_MIN = 0.5
CROSS_MIN = 0.2         # both wrists at least this far past the midline, at torso height -> arms_crossed
UNCROSS_MIN = 0.2       # both wrists at least this far on their own side -> arms_uncrossed; anything else abstains
# lean (sideways only; a front camera cannot see a forward slouch): shoulder-midpoint -> hip-midpoint angle from vertical.
# Needs both hips visible and inside the frame, which a head-and-torso phone framing usually is not: then we abstain.
UPRIGHT_MAX_DEG = 8.0
LEAN_MIN_DEG = 15.0
EXTRA_CHANNELS = ('framing', 'arms', 'lean')
CHANNELS = ('orientation',) + EXTRA_CHANNELS
BASELINE = {'framing_ok', 'arms_uncrossed', 'upright'}   # counted every sample, noted only when they END a problem state
SUMMARY_EVERY = 5       # run_for_job emits a vision_summary event every this many samples

DESCRIPTIONS = {
    'facing_camera': 'facing the camera',
    'turned_away': 'turned away from the camera',
    'out_of_frame': 'not visible in the frame',
}
EXTRA_DESCRIPTIONS = {
    'too_close': 'very close to the camera (face fills much of the frame)',
    'too_far': 'far from the camera (small in the frame)',
    'framing_ok': 'at a comfortable distance from the camera',
    'arms_crossed': 'arms crossed in front of the body',
    'arms_uncrossed': 'arms not crossed',
    'leaning': 'torso leaning to one side',
    'upright': 'torso upright',
}
ALL_DESCRIPTIONS = {**DESCRIPTIONS, **EXTRA_DESCRIPTIONS}
UNAVAILABLE = 'Visual evaluation unavailable: no caller video was received (camera off, denied, or an audio-only call).'


@dataclasses.dataclass
class VisionNote:
    observed_at: float
    source_verified: bool
    observable_description: str
    certainty: str                              # 'clear' | 'uncertain'
    optional_nearby_utterance: str | None = None
    signal: str = ''
    frame_seq: int | None = None
    samples: int = 0

    def as_dict(self):
        return dataclasses.asdict(self)


def classify(lm):
    """(33,5) image landmarks [x, y, z, visibility, presence] or None -> (label, margin). margin in 0..1: how far inside its
    band the measurement sits (used for certainty). 'unknown' means abstain."""
    if lm is None: return 'out_of_frame', 1.0
    vis = lm[:, 3]
    sh_ok = vis[L_SH] >= VIS_MIN and vis[R_SH] >= VIS_MIN
    nose_ok = vis[NOSE] >= VIS_MIN
    if not sh_ok and not nose_ok: return 'out_of_frame', 0.5
    if not nose_ok:                                           # shoulders but no face: back or side to the camera
        sw = abs(lm[L_SH, 0] - lm[R_SH, 0])
        return ('turned_away', 0.5) if sw >= MIN_SHOULDER_W * 0.5 else ('unknown', 0.0)
    ed = abs(lm[L_EAR, 0] - lm[R_EAR, 0])
    if vis[L_EAR] >= VIS_MIN and vis[R_EAR] >= VIS_MIN and ed >= MIN_EAR_DIST:
        yaw = abs(lm[NOSE, 0] - (lm[L_EAR, 0] + lm[R_EAR, 0]) / 2) / (ed / 2)
        if yaw <= FACING_MAX_YAW: return 'facing_camera', float(min(1.0, (FACING_MAX_YAW - yaw) / FACING_MAX_YAW + 0.2))
        if yaw >= TURNED_MIN_YAW: return 'turned_away', float(min(1.0, (yaw - FACING_MAX_YAW) / TURNED_MIN_YAW))
        return 'unknown', 0.0
    if not sh_ok: return 'unknown', 0.0                      # a face, no usable ears and no shoulders: not judged
    sw = abs(lm[L_SH, 0] - lm[R_SH, 0])
    if sw < MIN_SHOULDER_W: return 'unknown', 0.0
    off = abs(lm[NOSE, 0] - (lm[L_SH, 0] + lm[R_SH, 0]) / 2) / (sw / 2)
    if off <= FACING_MAX_OFF: return 'facing_camera', float(min(1.0, (FACING_MAX_OFF - off) / FACING_MAX_OFF + 0.2))
    if off >= TURNED_MIN_OFF: return 'turned_away', float(min(1.0, (off - FACING_MAX_OFF) / TURNED_MIN_OFF))
    return 'unknown', 0.0


def _vis(lm, *idx, vmin=VIS_MIN, inside=False):
    ok = all(lm[i, 3] >= vmin for i in idx)
    if ok and inside: ok = all(0.0 <= lm[i, 0] <= 1.0 and 0.0 <= lm[i, 1] <= 1.0 for i in idx)
    return ok


def classify_framing(lm, aspect=1.0, facing=False):
    """too_close | framing_ok | too_far | unknown. Only while facing the camera (a turned head shrinks the ear distance)."""
    if lm is None or not facing: return 'unknown', 0.0
    k = float(np.sqrt(aspect))                                 # x fraction -> fraction of sqrt(w*h)
    if _vis(lm, L_EAR, R_EAR, inside=True) and abs(lm[L_EAR, 0] - lm[R_EAR, 0]) >= MIN_EAR_DIST:
        face = abs(lm[L_EAR, 0] - lm[R_EAR, 0]) * k
        if face >= CLOSE_MIN_FACE: return 'too_close', float(min(1.0, (face - OK_FACE[1]) / OK_FACE[1] + 0.2))
        if face <= FAR_MAX_FACE: return 'too_far', float(min(1.0, (OK_FACE[0] - face) / OK_FACE[0] + 0.2))
        if OK_FACE[0] <= face <= OK_FACE[1]: return 'framing_ok', 0.6
        return 'unknown', 0.0
    if _vis(lm, L_EYE, R_EYE) and abs(lm[L_EYE, 0] - lm[R_EYE, 0]) * k >= CLOSE_MIN_EYES: return 'too_close', 0.5
    if _vis(lm, L_SH, R_SH, inside=True) and abs(lm[L_SH, 0] - lm[R_SH, 0]) * k <= FAR_MAX_SHOULDER: return 'too_far', 0.4
    return 'unknown', 0.0


def classify_arms(lm, aspect=1.0, facing=False):
    """arms_crossed | arms_uncrossed | unknown. Needs both shoulders, elbows and wrists visible and in frame."""
    if lm is None or not facing: return 'unknown', 0.0
    if not (_vis(lm, L_SH, R_SH) and _vis(lm, L_ELB, R_ELB, L_WR, R_WR, vmin=ARM_VIS_MIN, inside=True)): return 'unknown', 0.0
    mid = (lm[L_SH, 0] + lm[R_SH, 0]) / 2; half = abs(lm[L_SH, 0] - lm[R_SH, 0]) / 2
    if half * 2 < MIN_SHOULDER_W: return 'unknown', 0.0
    sh_y = (lm[L_SH, 1] + lm[R_SH, 1]) / 2; sw_y = half * 2 * aspect     # shoulder width in units of frame height
    # how far each wrist sits past the midline toward the opposite shoulder (negative: on its own side)
    lc = (lm[L_WR, 0] - mid) * np.sign(lm[R_SH, 0] - mid) / half
    rc = (lm[R_WR, 0] - mid) * np.sign(lm[L_SH, 0] - mid) / half
    torso = all(sh_y < lm[i, 1] <= sh_y + 2.0 * sw_y for i in (L_WR, R_WR))
    if lc >= CROSS_MIN and rc >= CROSS_MIN and torso: return 'arms_crossed', float(min(1.0, min(lc, rc) + 0.2))
    if lc <= -UNCROSS_MIN and rc <= -UNCROSS_MIN: return 'arms_uncrossed', float(min(1.0, min(-lc, -rc) + 0.2))
    return 'unknown', 0.0


def classify_lean(lm, aspect=1.0, facing=False):
    """upright | leaning | unknown (sideways lean only). Needs both hips visible and inside the frame."""
    if lm is None or not facing: return 'unknown', 0.0
    if not (_vis(lm, L_SH, R_SH) and _vis(lm, L_HIP, R_HIP, inside=True)): return 'unknown', 0.0
    dx = ((lm[L_HIP, 0] + lm[R_HIP, 0]) - (lm[L_SH, 0] + lm[R_SH, 0])) / 2 * aspect
    dy = ((lm[L_HIP, 1] + lm[R_HIP, 1]) - (lm[L_SH, 1] + lm[R_SH, 1])) / 2
    if dy < 0.1: return 'unknown', 0.0                        # hips not clearly below the shoulders
    deg = float(np.degrees(np.arctan2(abs(dx), dy)))
    if deg <= UPRIGHT_MAX_DEG: return 'upright', float(min(1.0, (UPRIGHT_MAX_DEG - deg) / UPRIGHT_MAX_DEG + 0.3))
    if deg >= LEAN_MIN_DEG: return 'leaning', float(min(1.0, (deg - UPRIGHT_MAX_DEG) / LEAN_MIN_DEG + 0.2))
    return 'unknown', 0.0


def classify_all(lm, aspect=1.0):
    """Every channel for one sample: {channel: (label, margin)}. orientation is classify(); the extra channels are judged only
    when the orientation sample is facing_camera, and each abstains ('unknown') on its own when its landmarks are not usable."""
    o = classify(lm); facing = o[0] == 'facing_camera'
    return dict(orientation=o, framing=classify_framing(lm, aspect, facing), arms=classify_arms(lm, aspect, facing),
                lean=classify_lean(lm, aspect, facing))


def thumb(rgb):
    """32x18 grey thumbnail (float32) for the frame-change check; block means, no OpenCV needed."""
    g = rgb.astype(np.float32).mean(axis=2)
    h, w = g.shape
    ys = np.linspace(0, h, 19).astype(int); xs = np.linspace(0, w, 33).astype(int)
    return np.array([[g[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean() for j in range(32)] for i in range(18)], np.float32)


class Observer:
    """Feed it RGB frames (observe) at about 1 fps; it returns a VisionNote when a stable state change happens.
    Pure logic plus an injectable pose callable, so it runs the same live, offline and in tests.

    Four channels (CHANNELS), each with its own WINDOW_N window, STABLE_N rule and state: orientation (the original signal,
    unchanged), framing, arms, lean. Extra-channel baseline states (BASELINE) are counted but noted only when they end a
    problem state, and an extra channel that sees no sample of its state for a whole window forgets it (the wrists left the
    frame: we no longer know the arms are crossed)."""
    def __init__(self, pose=None):
        self.pose = pose                                      # callable(rgb, t_ms) -> (landmarks|None, world) like rtcoach.pose.Pose
        self.windows = {c: collections.deque(maxlen=WINDOW_N) for c in CHANNELS}
        self.window = self.windows['orientation']
        self.states = dict.fromkeys(CHANNELS); self.last_noted = dict.fromkeys(CHANNELS)
        self.segments = {c: [] for c in CHANNELS}             # closed stable stretches: (label, start_t, last_agreeing_t)
        self.current = dict.fromkeys(CHANNELS)                # open stretch per channel: [label, start_t, last_agreeing_t]
        self.notes = []
        self.n_samples = 0; self.n_new = 0; self.n_changed = 0; self.last_seq = None; self.last_thumb = None
        self.channel_counts = {c: collections.Counter() for c in CHANNELS}
        self.counts = self.channel_counts['orientation']; self.unavailable = False
        self.first_t = None; self.last_t = None

    @property
    def state(self): return self.states['orientation']

    def observe(self, rgb, t, seq=None, lm=None):
        """One sample at job-clock time t. lm: precomputed landmarks (tests); else self.pose runs. Returns the first new note
        (orientation first) or None; observe_all() returns every note this sample made."""
        notes = self.observe_all(rgb, t, seq, lm)
        return notes[0] if notes else None

    def observe_all(self, rgb, t, seq=None, lm=None, aspect=None):
        self.n_samples += 1
        if self.first_t is None: self.first_t = t
        self.last_t = t
        if seq is None or seq != self.last_seq:
            self.n_new += 1; self.last_seq = seq
        if rgb is not None:
            th = thumb(rgb)
            if self.last_thumb is not None and float(np.abs(th - self.last_thumb).mean()) > CHANGE_DIFF: self.n_changed += 1
            self.last_thumb = th
            if aspect is None: aspect = rgb.shape[1] / max(1, rgb.shape[0])
            if lm is None and self.pose is not None: lm, _ = self.pose(rgb, int(t * 1000))
        labels = classify_all(lm, aspect or 1.0)
        out = []
        for c in CHANNELS:
            note = self._step(c, *labels[c], t, seq)
            if note is not None: out.append(note)
        return out

    def _step(self, c, label, margin, t, seq):
        self.channel_counts[c][label] += 1
        win = self.windows[c]; win.append((label, margin, t, seq))
        cur = self.current[c]
        if cur is not None and label == cur[0]: cur[2] = t
        if c != 'orientation' and cur is not None and len(win) == WINDOW_N and all(w[0] != cur[0] for w in win):
            self.segments[c].append(tuple(cur)); self.current[c] = None; self.states[c] = None      # lost: forget the state
        labels = [w[0] for w in win]
        top, n = collections.Counter(labels).most_common(1)[0]
        if top == 'unknown' or n < STABLE_N or top == self.states[c]: return None
        agreeing = [w for w in win if w[0] == top]
        clear = 'unknown' not in labels and min(w[1] for w in agreeing) >= 0.3   # no unclear sample in the window, none marginal
        if self.current[c] is not None: self.segments[c].append(tuple(self.current[c]))
        self.current[c] = [top, agreeing[0][2], t]
        self.states[c] = top
        if c != 'orientation' and top in BASELINE and self.last_noted[c] in (None, *BASELINE): return None
        self.last_noted[c] = top
        note = VisionNote(observed_at=round(agreeing[0][2], 1), source_verified=True, observable_description=ALL_DESCRIPTIONS[top],
                          certainty='clear' if clear else 'uncertain', signal=top, frame_seq=agreeing[0][3], samples=n)
        self.notes.append(note)
        return note

    def mark_unavailable(self, t):
        if self.unavailable: return None
        self.unavailable = True
        note = VisionNote(observed_at=round(t, 1), source_verified=False, observable_description='no caller video received',
                          certainty='clear', signal='no_video')
        self.notes.append(note); return note

    def frame_stats(self):
        return dict(samples=self.n_samples, new_frames=self.n_new, changed=self.n_changed)

    def stats(self):
        """Per-call aggregate for the feedback (P17-B), verified frames only. {samples, first_t, last_t, channels: {channel:
        {judged, counts: {label: n}, share: {label: 0..1 of judged}, longest: {label: {seconds, start, end}}}}}. 'longest' comes
        from STABLE stretches (STABLE_N of WINDOW_N), from the first agreeing sample to the last one, so a flicker never counts."""
        ch = {}
        for c in CHANNELS:
            counts = {k: v for k, v in self.channel_counts[c].items() if k != 'unknown'}
            judged = sum(counts.values())
            segs = list(self.segments[c]) + ([tuple(self.current[c])] if self.current[c] is not None else [])
            longest = {}
            for label, start, end in segs:
                if label not in longest or end - start > longest[label]['seconds']:
                    longest[label] = dict(seconds=round(end - start, 1), start=round(start, 1), end=round(end, 1))
            ch[c] = dict(judged=judged, counts=counts, share={k: round(v / judged, 2) for k, v in counts.items()} if judged else {},
                         longest=longest)
        return dict(samples=self.n_samples, first_t=self.first_t, last_t=self.last_t, channels=ch)

    def summary(self):
        """For the end-of-round coach (James P10): plain text built only from what was observed, or the unavailable line."""
        verified = [n for n in self.notes if n.source_verified]
        if not verified:
            if self.n_samples: return (f'Caller video was received ({self.n_samples} samples) but the caller\'s orientation was never clear '
                                       f'enough to judge: no visual feedback.')
            return UNAVAILABLE
        judged = sum(self.counts[k] for k in DESCRIPTIONS)
        parts = [f'{mmss(n.observed_at)} {n.observable_description}' + (' (uncertain)' if n.certainty != 'clear' else '') for n in verified]
        line = 'Camera observations (sampled video frames, body/face orientation, distance, crossed arms, sideways lean only): ' + '; '.join(parts) + '.'
        if judged:
            line += f' Of {judged} samples where the caller could be judged, {self.counts["facing_camera"]} showed them facing the camera.'
        if self.counts['unknown']: line += f' {self.counts["unknown"]} samples were unclear and not judged.'
        for c in EXTRA_CHANNELS:
            cc = self.channel_counts[c]; j = sum(v for k, v in cc.items() if k != 'unknown')
            if j: line += f' {c}: ' + ', '.join(f'{k} {v}' for k, v in cc.most_common() if k != 'unknown') + f' of {j} judged samples.'
        return line


def mmss(t):
    return f'{int(t // 60)}:{int(t % 60):02d}'


def attach_utterances(notes, transcript, window_s=5.0):
    """notes: VisionNote list; transcript: iterable of (t, text) caller lines on the same job clock. Sets
    optional_nearby_utterance to the closest caller line within window_s of each verified note. Returns notes."""
    lines = list(transcript)
    for n in notes:
        if not n.source_verified or not lines: continue
        t, text = min(lines, key=lambda x: abs(x[0] - n.observed_at))
        if abs(t - n.observed_at) <= window_s: n.optional_nearby_utterance = text
    return notes


def frame_to_rgb(frame):
    """rtc.VideoFrame -> (h, w, 3) uint8, as facetime/coach_agent.frame_to_rgb (copied: that module imports torch)."""
    from livekit import rtc
    if frame.type != rtc.VideoBufferType.RGB24: frame = frame.convert(rtc.VideoBufferType.RGB24)
    buf = np.frombuffer(frame.data, np.uint8); h, w = frame.height, frame.width
    if len(buf) == h * w * 3: return buf.reshape(h, w, 3)
    return buf.reshape(h, len(buf) // h)[:, :w * 3].reshape(h, w, 3)          # padded rows


def load_pose(variant='lite'):
    from rtcoach.pose import Pose
    return Pose(variant=variant, video=True)


# ---- the worker side: one task per job (facetime/worker.py starts it with --vision-notes) ----
async def run_for_job(job, fps=1.0, variant='lite'):
    """Samples job.latest (frame, ts_us, t_mono, t_wall, seq) at fps once a caller is bound; emits vision_note events.
    Never raises into the job: a failure is logged once and the observer stops (feedback then says video is unavailable)."""
    try:
        pose = await asyncio.to_thread(load_pose, variant)
    except Exception as e:
        print(f'[vision-notes] pose model unavailable ({type(e).__name__}: {e}): no visual notes', flush=True); return
    obs = job.vision_observer = Observer(pose)
    t0 = job.per.t0 if getattr(job, 'per', None) is not None else job.t0
    period = 1.0 / max(0.2, min(fps, 2.0)); bound_t = None
    print(f'[vision-notes] on: {1 / period:g} fps, pose {variant}; signals: facing camera / turned away / out of frame; distance; crossed arms; sideways lean', flush=True)
    try:
        while not job.closed:
            await asyncio.sleep(period)
            now = time.monotonic(); t = now - t0
            if job.bound is None: continue
            if bound_t is None: bound_t = now
            slot = job.latest
            if slot is None:
                if now - bound_t >= NO_VIDEO_S and (note := obs.mark_unavailable(t)) is not None:
                    print(f'[vision-notes] no caller video {NO_VIDEO_S:g} s after the bind: visual evaluation unavailable', flush=True)
                    job.emit('vision_note', **note.as_dict())
                continue
            frame, _ts, t_mono, _wall, seq = slot
            if now - t_mono > STALE_S: continue
            rgb = frame_to_rgb(frame)
            new_notes = await asyncio.to_thread(obs.observe_all, rgb, t, seq)
            if obs.n_samples % 10 == 0:
                s = obs.frame_stats()
                print(f'[vision-notes] {s["samples"]} samples: {s["new_frames"]} new frames, {s["changed"]} visibly changed; labels {dict(obs.counts)}', flush=True)
            for note in new_notes:
                print(f'[vision-notes] t={note.observed_at:.1f} {note.observable_description} ({note.certainty}, frame {note.frame_seq})', flush=True)
                job.emit('vision_note', **note.as_dict())
            st = obs.stats() if obs.n_samples % SUMMARY_EVERY == 0 else None
            if st is not None and any(v['judged'] for v in st['channels'].values()):
                job.emit('vision_summary', source_verified=True, **st)     # the per-call aggregate the feedback cites (P17-B)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f'[vision-notes] stopped on an error ({type(e).__name__}: {e}); notes so far are kept', flush=True)
    finally:
        try: pose.close()
        except Exception: pass
        print(f'[vision-notes] end: {obs.frame_stats()}; summary: {obs.summary()}', flush=True)


# ---- offline check ----
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--camera', type=int, help='local webcam index')
    src.add_argument('--video', help='a video file')
    ap.add_argument('--fps', type=float, default=1.0)
    ap.add_argument('--seconds', type=float, default=30.0, help='stop after this long (camera) / this much video')
    ap.add_argument('--pose', default='lite', choices=['lite', 'full', 'heavy'])
    a = ap.parse_args(argv)
    import cv2
    cap = cv2.VideoCapture(a.camera if a.camera is not None else a.video)
    if not cap.isOpened(): print('cannot open the source', file=sys.stderr); return 1
    obs = Observer(load_pose(a.pose))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; live = a.camera is not None
    t_start = time.monotonic(); n = 0; next_t = 0.0
    while True:
        ok, bgr = cap.read()
        if not ok: break
        t = (time.monotonic() - t_start) if live else n / src_fps; n += 1
        if t > a.seconds: break
        if t < next_t: continue
        next_t = t + 1.0 / a.fps
        for note in obs.observe_all(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), t, seq=n):
            print(f't={note.observed_at:5.1f}  {note.observable_description}  ({note.certainty})', flush=True)
    cap.release()
    print('frames:', obs.frame_stats()); print('labels:', dict(obs.counts)); print(obs.summary())
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""P17-A pose mirror (facetime/brodia_mirror.py + worker --mirror), offline: no LiveKit server, no API calls.

 A. compose() on a synthetic frame with fake landmarks (skeleton pixels in volt) and with None (no skeleton); both shapes; no fitness text
 B. placeholder() before video; scenario_label()
 C. Mirror.render(): a pose that raises -> the raw frame, no exception
 D. the worker with --mirror --perception off (fake room/ctx from test_worker_shutdown.py): a video track "brodia-mirror"
    (SOURCE_CAMERA) is published at start, placeholder frames before video, rendered frames once a fake caller video arrives,
    the job ends on the caller's leave and the mirror task is done (no leaked task)
 E. (optional) the real MediaPipe pose lite model on frames of a real video: --video PATH, else the first data/tmp/**/*.mp4; skipped
    when no video or no model is present

Run:  .venv/bin/python scripts/test_brodia_mirror.py [--video clip.mp4]
"""
import asyncio, glob, json, os, sys, time
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import tempfile; os.environ['BRODIA_NEXT_CALL_PATH'] = os.path.join(tempfile.mkdtemp(prefix='brodia-test-'), 'next_call.json')
from livekit import rtc
from facetime import brodia_mirror as bm
from facetime.mirror import VOLT

PASS = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg, flush=True); PASS.append(bool(cond)); return cond


def volt_pixels(img):
    return int(np.all(np.abs(img.astype(int) - np.array(VOLT)) < 30, axis=2).sum())


def fake_landmarks():
    """A standing person centred in the frame: shoulders, elbows, wrists, hips, knees, ankles visible."""
    lm = np.zeros((33, 5), np.float32); lm[:, 3] = 0.0
    pts = {0: (.5, .2), 11: (.45, .3), 12: (.55, .3), 13: (.42, .42), 14: (.58, .42), 15: (.40, .52), 16: (.60, .52),
           23: (.46, .55), 24: (.54, .55), 25: (.46, .72), 26: (.54, .72), 27: (.46, .88), 28: (.54, .88)}
    for i, (x, y) in pts.items(): lm[i, :2] = (x, y); lm[i, 3] = 0.95; lm[i, 4] = 0.95
    return lm


def test_compose():
    print('[A] compose', flush=True)
    rgb = np.full((720, 1280, 3), 90, np.uint8)
    for shape, (W, H) in bm.SIZES.items():
        with_lm = bm.compose(rgb, fake_landmarks(), 'Park · Neutral', (W, H))
        without = bm.compose(rgb, None, 'Park · Neutral', (W, H))
        check(with_lm.shape == (H, W, 3) and with_lm.dtype == np.uint8 and without.shape == (H, W, 3), f'{shape}: {W}x{H} RGB uint8')
        nv, n0 = volt_pixels(with_lm), volt_pixels(without)
        check(nv > n0 + 500, f'{shape}: skeleton drawn in volt ({nv} volt px with landmarks, {n0} without: only the tag dot)')
    import inspect
    params = set(inspect.signature(bm.compose).parameters)
    check(not params & {'count', 'target', 'exercise', 'state', 'cue', 'face'}, f'compose() takes no fitness inputs: {sorted(params)}')
    odd = bm.compose(np.zeros((480, 360, 3), np.uint8), fake_landmarks(), None, bm.SIZES['landscape'])
    check(odd.shape == (540, 960, 3), 'portrait source into a landscape track: cropped, no error')


def test_placeholder():
    print('[B] placeholder', flush=True)
    check(bm.scenario_label('park', 'neutral') == 'Park · Neutral' and bm.scenario_label(None, None) is None, 'scenario label "Park · Neutral"')
    img = bm.placeholder('Park · Neutral', bm.SIZES['portrait'])
    check(img.shape == (960, 540, 3) and int(img.std()) > 0 and volt_pixels(img) > 0, 'placeholder: portrait, not blank, volt ring')


def test_pose_failure():
    print('[C] pose failure -> raw frame', flush=True)
    def bad(rgb, t): raise RuntimeError('boom')
    m = bm.Mirror('Barista · Interested', bm.SIZES['landscape'], bad)
    img = m.render(np.full((720, 1280, 3), 120, np.uint8))
    check(img.shape == (540, 960, 3) and m.pose_errors == 1 and m.n == 1, 'render() survives a pose error, frame still composed')
    calls = []
    def good(rgb, t): calls.append(t); return fake_landmarks(), None
    m = bm.Mirror(None, bm.SIZES['portrait'], good); m.render(np.zeros((720, 1280, 3), np.uint8)); m.render(np.zeros((720, 1280, 3), np.uint8))
    check(len(calls) == 2 and calls[1] > calls[0], 'pose timestamps strictly increasing (MediaPipe VIDEO mode)')
    m.close(); check(m.pose is None and m.landmarks(np.zeros((10, 10, 3), np.uint8)) is None, 'close(): pose released, later frames raw')


class RGBFrame:
    """A stand-in rtc.VideoFrame: RGB24 bytes of a grey 640x360 frame."""
    def __init__(self, v):
        self.width, self.height = 640, 360; self.type = rtc.VideoBufferType.RGB24
        self.data = np.full((360, 640, 3), v, np.uint8).tobytes()


async def test_worker():
    print('[D] worker --mirror --perception off: track published, placeholder, frames, clean end', flush=True)
    import test_worker_shutdown as tws
    from facetime import worker
    from facetime.perception import Config
    published = []
    class Local(tws.FakeLocal):
        async def publish_track(self, track, opts): published.append((track, opts))
    room = tws.FakeRoom(); room.local_participant = Local()
    ctx = tws.FakeCtx(room); ctx.job.metadata = json.dumps({'chert_call': 'fake'})
    elog = os.path.join(tempfile.mkdtemp(prefix='brodia-mirror-'), 'events.jsonl')
    job = tws.make_job(ctx, Config(plan='squats:3'), perception='off', event_log=elog)
    job.a.mirror = True; job.a.mirror_fps = 10.0; job.a.mirror_shape = 'portrait'; job.a.brodia_scenario = 'park'; job.a.brodia_receptivity = 'neutral'
    # the real pose loader would need the model; keep D independent of it (E covers the model)
    poses = []
    def fake_pose(rgb, t): poses.append(t); return fake_landmarks(), None
    import facetime.brodia_mirror as mod
    orig_loader = mod.load_pose; mod.load_pose = lambda variant='lite': fake_pose
    run_orig = mod.run_for_job
    async def run_patched(job_, **kw): return await run_orig(job_, pose_loader=lambda v: fake_pose, **kw)
    mod.run_for_job = run_patched
    captured = []
    orig_cap = rtc.VideoSource.capture_frame
    def cap(self, frame, *a, **k): captured.append((frame.width, frame.height)); return orig_cap(self, frame, *a, **k)
    rtc.VideoSource.capture_frame = cap
    class Stream(tws.FakeVideoStream):
        async def __anext__(self):
            ev = await super().__anext__(); ev.frame = RGBFrame(60 + self.n % 100); return ev
    stream = Stream(fps=15.0); job.video_frames = lambda track: stream
    try:
        t = asyncio.create_task(job.run()); await asyncio.sleep(0.6)
        vids = [(tr, o) for tr, o in published if isinstance(tr, rtc.LocalVideoTrack)]
        check(len(vids) == 1 and vids[0][0].name == bm.TRACK_NAME and vids[0][1].source == rtc.TrackSource.SOURCE_CAMERA,
              f'video track published at start: {[(tr.name, rtc.TrackSource.Name(o.source)) for tr, o in vids]}')
        n_before = len(captured)
        check(n_before >= 3 and job.mirror is not None and job.mirror.n == 0 and all(c == (540, 960) for c in captured), f'{n_before} placeholder frames 540x960 before any caller video, no render')
        job.on_track_subscribed(tws.FakeTrack(rtc.TrackKind.KIND_VIDEO), tws.FakePub('camera'), tws.P('chert-bridge-m1'))
        await asyncio.sleep(1.0)
        check(job.mirror.n >= 5 and len(poses) >= 5 and len(captured) > n_before + 5, f'caller video: {job.mirror.n} frames rendered with pose, {len(captured)} captured in all')
        check(job.mirror.label == 'Park · Neutral', f'label {job.mirror.label!r}')
        job.on_participant_disconnected(tws.P('chert-bridge-m1'))
        try: await asyncio.wait_for(t, 5); exc = None
        except Exception as e: exc = e
        check(exc is None and job.closed and job.end_reason == 'caller left' and job.mirror_task.done() and stream.closed, f'job ended ({job.end_reason}), mirror task done, stream closed')
        n_end = len(captured); await asyncio.sleep(0.3)
        check(len(captured) == n_end, 'no frames captured after the job ended')
        left = [x for x in asyncio.all_tasks() if x is not asyncio.current_task() and not x.done() and 'mirror' in x.get_name()]
        check(not left, f'no leaked mirror task ({left})')
    finally:
        rtc.VideoSource.capture_frame = orig_cap; mod.load_pose = orig_loader; mod.run_for_job = run_orig


def test_real_video(path):
    print('[E] real pose lite on a real video', flush=True)
    if not path:
        cands = sorted(glob.glob(os.path.join(ROOT, 'data', 'tmp', '**', '*.mp4'), recursive=True))
        path = cands[0] if cands else None
    if not path or not os.path.exists(path): print('  skip  no test video (pass --video PATH)', flush=True); return
    if not os.path.exists(os.path.join(ROOT, 'models', 'pose_landmarker_lite.task')): print('  skip  models/pose_landmarker_lite.task missing', flush=True); return
    import cv2
    m = bm.Mirror('Street · Interested', bm.SIZES['portrait'], bm.load_pose('lite'))
    cap = cv2.VideoCapture(path); got = 0; lm_seen = 0; img = None
    for _ in range(40):
        ok, bgr = cap.read()
        if not ok: break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); lm = m.landmarks(rgb); lm_seen += lm is not None
        img = bm.compose(rgb, lm, m.label, m.size); got += 1
    cap.release()
    t = time.perf_counter(); n = 20
    for _ in range(n): m.render(rgb)
    ms = (time.perf_counter() - t) / n * 1000
    print(f'        {os.path.basename(path)} {rgb.shape[1]}x{rgb.shape[0]}: pose found on {lm_seen}/{got} frames; render (pose lite + compose) {ms:.1f} ms/frame; {m.stats()}', flush=True)
    check(got > 0 and lm_seen > got // 2 and img is not None and volt_pixels(img) > 200, f'skeleton on a real frame ({lm_seen}/{got} frames with a pose)')
    m.close()


async def main():
    video = sys.argv[sys.argv.index('--video') + 1] if '--video' in sys.argv else None
    test_compose(); test_placeholder(); test_pose_failure()
    await test_worker()
    test_real_video(video)
    n = len(PASS); ok = sum(PASS); print(f'\n{ok}/{n} checks passed' + ('' if ok == n else '  <-- FAILURES'), flush=True)
    return 0 if ok == n else 1


if __name__ == '__main__':
    rc = asyncio.run(main()); sys.stdout.flush(); os._exit(rc)
